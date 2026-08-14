"""Cross-process single-window coordination for Kobee Studio dialogs.

KiCad starts each External Plugin action in its own Python process.  A module
global therefore cannot prevent duplicate Studio windows; use a tiny local
loopback notification channel instead.  The first process owns the metadata
file and listens for focus requests, while later invocations only wake that
window and exit.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class StudioWindowSingleton:
    """Own, or request focus for, the one running Studio editor window."""

    _FILENAME = "studio-window.json"
    _STARTUP_WAIT_SECONDS = 1.0

    def __init__(self, config_dir: Path | str):
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / self._FILENAME
        self._token = os.urandom(24).hex()
        self._server: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._activate: Optional[Callable[[], None]] = None
        self._pending_activation = False
        self._lock = threading.Lock()

    @staticmethod
    def _process_is_alive(pid: object) -> bool:
        try:
            value = int(pid)
            if value <= 0:
                return False
            os.kill(value, 0)
        except (TypeError, ValueError, OSError):
            return False
        return True

    def _read_metadata(self) -> Optional[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _send_activation(metadata: dict) -> bool:
        try:
            port = int(metadata["port"])
            token = str(metadata["token"])
            if not 1 <= port <= 65535 or not token:
                return False
            with socket.create_connection(("127.0.0.1", port), timeout=0.25) as client:
                client.sendall((token + "\n").encode("ascii"))
            return True
        except (KeyError, OSError, ValueError, UnicodeError):
            return False

    def _remove_stale_metadata(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def acquire_or_activate(self) -> bool:
        """Return true for the owner; otherwise request focus and return false."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._STARTUP_WAIT_SECONDS
        while True:
            metadata = self._read_metadata()
            if metadata is None:
                try:
                    descriptor = os.open(
                        str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                    )
                except FileExistsError:
                    continue
                try:
                    self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self._server.bind(("127.0.0.1", 0))
                    self._server.listen(4)
                    self._server.settimeout(0.2)
                    port = self._server.getsockname()[1]
                    payload = {
                        "pid": os.getpid(),
                        "port": port,
                        "token": self._token,
                    }
                    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, sort_keys=True)
                    self._thread = threading.Thread(
                        target=self._listen,
                        name="kobee-studio-window-focus",
                        daemon=True,
                    )
                    self._thread.start()
                    return True
                except Exception:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                    if self._server is not None:
                        self._server.close()
                        self._server = None
                    self._remove_stale_metadata()
                    raise

            if self._send_activation(metadata):
                return False
            if self._process_is_alive(metadata.get("pid")) and time.monotonic() < deadline:
                # The first instance has reserved the file but has not yet
                # finished binding its listener.  Do not race it into a second
                # dialog; retry the focus request briefly.
                time.sleep(0.05)
                continue
            self._remove_stale_metadata()

    def attach(self, activate: Callable[[], None]) -> None:
        """Set the UI-thread focus callback once a dialog has been created."""
        with self._lock:
            self._activate = activate
            pending = self._pending_activation
            self._pending_activation = False
        if pending:
            activate()

    def _dispatch_activation(self) -> None:
        with self._lock:
            callback = self._activate
            if callback is None:
                self._pending_activation = True
                return
        callback()

    def _listen(self) -> None:
        # Keep a local reference: ``release`` clears the public attribute
        # while this daemon is waiting in ``accept``.
        server = self._server
        while not self._stop.is_set() and server is not None:
            try:
                client, _address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with client:
                try:
                    received = client.recv(128).decode("ascii").strip()
                except (OSError, UnicodeError):
                    continue
                if received == self._token:
                    self._dispatch_activation()

    def release(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        metadata = self._read_metadata()
        if metadata and metadata.get("token") == self._token:
            self._remove_stale_metadata()

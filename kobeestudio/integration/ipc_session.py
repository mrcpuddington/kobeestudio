"""Small, testable boundary around KiCad's supported IPC plugin API.

The released 1.2.x plugin uses the SWIG ActionPlugin runtime, while 1.3 and
newer use this IPC boundary. It deliberately contains no ``pcbnew`` or ``wx``
imports, and loads the official ``kicad-python`` client only when an IPC action
is actually launched by KiCad.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable


class IpcUnavailableError(RuntimeError):
    """Raised when the IPC plugin was not launched by a compatible KiCad."""


def unique_client_name(base_name: str = "Kobee Studio", process_id: int | None = None) -> str:
    """Return an IPC identity that cannot inherit another process's commit."""
    return "{} ({})".format(base_name, os.getpid() if process_id is None else process_id)


def _ipc_environment(environ: dict[str, str] | None = None) -> tuple[str, str]:
    """Return the KiCad-owned connection details exposed to IPC actions."""
    values = os.environ if environ is None else environ
    socket_path = values.get("KICAD_API_SOCKET")
    token = values.get("KICAD_API_TOKEN", "")
    if not socket_path:
        raise IpcUnavailableError(
            "This action must be launched from KiCad 9 or newer so it receives "
            "the IPC connection details."
        )
    return socket_path, token


@dataclass
class IpcSession:
    """A thin adapter for the operations Kobee Studio needs from PCB Editor."""

    kicad: Any
    board: Any

    @classmethod
    def connect(
        cls,
        *,
        client_name: str = "Kobee Studio",
        environ: dict[str, str] | None = None,
        client_factory: Callable[..., Any] | None = None,
        socket_path: str | None = None,
        kicad_token: str | None = None,
    ) -> "IpcSession":
        if socket_path is None:
            socket_path, token = _ipc_environment(environ)
        else:
            # Useful for development tools connecting to a known running PCB
            # Editor. KiCad-launched actions always use the environment path.
            token = kicad_token or ""

        if client_factory is None:
            try:
                from kipy import KiCad
            except ImportError as error:
                raise IpcUnavailableError(
                    "The kicad-python dependency is unavailable. Recreate this "
                    "plugin's environment in KiCad Preferences and try again."
                ) from error
            client_factory = KiCad

        try:
            kicad = client_factory(
                socket_path=socket_path,
                kicad_token=token,
                client_name=client_name,
            )
            board = kicad.get_board()
        except Exception as error:
            raise IpcUnavailableError(
                "Kobee Studio could not connect to the active PCB Editor: {}".format(error)
            ) from error
        return cls(kicad=kicad, board=board)

    def version(self) -> str:
        return str(self.kicad.get_version())

    def close(self) -> None:
        close = getattr(self.kicad, "close", None)
        if close is not None:
            close()

    def selected_items(self):
        """Read selection through IPC; used by the later artwork edit adapter."""
        return self.board.get_selection()

    def selected_artwork(self):
        from .ipc_artwork import selected_artwork, selected_legacy_artwork

        selection = self.selected_items()
        current = selected_artwork(selection)
        if current is not None:
            return current
        if len(selection) == 1:
            return selected_legacy_artwork(
                selection,
                self.board.get_selection_as_string(),
            )
        return None

    def begin_commit(self):
        """Start a single undoable PCB operation.

        The placement adapter will use this before it creates or replaces the
        grouped PCB items that make up one Kobee Studio artwork item.
        """
        return self.board.begin_commit()

    def commit(self, transaction, message: str) -> None:
        self.board.push_commit(transaction, message)

    def discard(self, transaction) -> None:
        self.board.drop_commit(transaction)

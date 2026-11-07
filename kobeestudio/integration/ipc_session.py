"""Small, testable boundary around KiCad's supported IPC plugin API.

The released 1.2.x plugin uses the SWIG ActionPlugin runtime, while 1.3 and
newer use this IPC boundary. It deliberately contains no ``pcbnew`` or ``wx``
imports, and loads the official ``kicad-python`` client only when an IPC action
is actually launched by KiCad.
"""

from __future__ import annotations

import os
import re
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
        self.check_write_compatibility()
        return self.board.begin_commit()

    def check_write_compatibility(self) -> None:
        """Avoid KiCad #24966 before sending a transaction to an affected host.

        KiCad 10.0.0–10.0.6 has a null frame in its schematic API handler.
        BeginCommit has no document selector, so even a PCB transaction can
        reach that handler. Python cannot catch the resulting host segfault.
        Recheck at every write: the schematic can open while Studio is open.
        Upstream fix: bdcb150903658e2c8f91b8862f87d950b35c0d1f.
        """
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", self.version())
        if match is None:
            raise IpcUnavailableError("Could not verify the KiCad version before changing the board. Reopen Kobee Studio from PCB Editor.")
        version = tuple(int(part) for part in match.groups())
        if not (10, 0, 0) <= version < (10, 0, 7):
            return
        get_documents = getattr(self.kicad, "get_open_documents", None)
        if get_documents is None:
            return  # Retained adapters without multi-editor IPC routing.
        from kipy.proto.common.types import DocumentType
        from kipy.proto.common import ApiStatusCode
        from kipy.errors import ApiError

        try:
            schematics = get_documents(DocumentType.DOCTYPE_SCHEMATIC)
        except Exception as error:
            # When eeschema has never been opened, no schematic handler is
            # registered at all. KiCad reports AS_UNHANDLED rather than an
            # empty document list; that is the safe PCB-only case.
            if isinstance(error, ApiError) and error.code == ApiStatusCode.AS_UNHANDLED:
                return
            raise IpcUnavailableError(
                "Could not check for KiCad's schematic transaction crash. "
                "Update KiCad to 10.0.7 or newer, or close Schematic Editor and retry."
            ) from error
        if schematics:
            raise IpcUnavailableError(
                "KiCad {} can crash when a plug-in changes the PCB while Schematic Editor is open. "
                "Close Schematic Editor and retry, or update KiCad to 10.0.7 or newer. "
                "No board changes were sent."
                .format(self.version())
            )

    def commit(self, transaction, message: str) -> None:
        self.board.push_commit(transaction, message)

    def discard(self, transaction) -> None:
        self.board.drop_commit(transaction)

    def board_tools(self):
        from .board_tools import BoardToolsService
        return BoardToolsService(self)

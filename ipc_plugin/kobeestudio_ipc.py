"""Kobee Studio IPC action entry point.

KiCad launches this file from the PCM package in an isolated Python
environment and provides KICAD_API_SOCKET and KICAD_API_TOKEN.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PLUGIN_ROOT.parent
if (SOURCE_ROOT / "kobeestudio").is_dir() and str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import wx

from kobeestudio.core.legacy_adapter import build_footprint_payload
from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.integration.ipc_artwork import IpcArtworkPlacement
from kobeestudio.integration.ipc_session import IpcSession, IpcUnavailableError
from kobeestudio.integration.platform_branding import (
    configure_application_branding,
    configure_process_identity,
    configure_window_branding,
)
from kobeestudio.ui.main_dialog import MainDialog


BRAND_ICON = next(
    (
        path
        for path in (
            PLUGIN_ROOT / "kobeestudio" / "resources" / "kobee-studio-app-icon.png",
            SOURCE_ROOT / "kobeestudio" / "resources" / "kobee-studio-app-icon.png",
            PLUGIN_ROOT / "kobeestudio" / "resources" / "kobee-bee.png",
            SOURCE_ROOT / "kobeestudio" / "resources" / "kobee-bee.png",
        )
        if path.is_file()
    ),
    PLUGIN_ROOT / "kobee-toolbar-48.png",
)


def main() -> int:
    """Open the existing editor and place its artwork through KiCad IPC."""
    configure_process_identity()
    app = wx.App(False)
    configure_application_branding(app, BRAND_ICON)
    session = None
    try:
        session = IpcSession.connect(client_name="Kobee Studio")
        placement = IpcArtworkPlacement(session)
        config_dir = Path(wx.StandardPaths.Get().GetUserConfigDir()) / "kobee-studio"
        config_dir.mkdir(parents=True, exist_ok=True)

        def place(dialog, _buzzard):
            feature = None
            if dialog.artwork.header is not None:
                feature = {"kind": "pin_header_2_54", "data": dialog.artwork.header.to_dict()}
            elif dialog.artwork.component_callout is not None:
                feature = {
                    "kind": (
                        "component_array"
                        if dialog.artwork.component_callout.array_count > 1
                        else "component_callout"
                    ),
                    "data": dialog.artwork.component_callout.to_dict(),
                }
            payload = build_footprint_payload(
                dialog.CurrentSettings(),
                document=dialog.artwork.document,
                feature=feature,
            )
            placement.place(
                dialog.artwork,
                payload,
                dialog.output_layer,
                old_footprint=dialog.updateFootprint,
            )
            dialog.EndModal(wx.ID_OK)

        geometry = TextGeometry()
        dialog = MainDialog(
            None,
            str(config_dir / "ipc-config.json"),
            geometry.buzzard,
            place,
            editor_session=session,
            build_label="IPC",
        )
        configure_window_branding(dialog, BRAND_ICON, wx)
        app.SetTopWindow(dialog)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
    except Exception as error:
        traceback.print_exc()
        print("Kobee Studio IPC startup failed: {}".format(error), file=sys.stderr)
        wx.MessageBox(str(error), "Kobee Studio IPC", wx.OK | wx.ICON_ERROR)
        return 1
    finally:
        if session is not None:
            session.close()
        app.Destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Kobee Studio ActionPlugin entry point for KiCad 10.0.x."""

from __future__ import annotations

import base64
import json
import logging
import os
import platform
from pathlib import Path

import pcbnew
import wx

from .integration.kicad_compatibility import KiCadCompatibility
from .integration.platform_branding import configure_window_branding
if os.environ.get("KOBEE_USE_LEGACY_EDITOR"):
    from .ui.main_dialog import MainDialog
else:
    from .ui.editor_v2 import MainDialog
from .version import __version__


class KobeeStudioPlugin(pcbnew.ActionPlugin):
    """Generate and place PCB labels without clipboard paste."""

    def defaults(self):
        self.name = "Kobee Studio: Create PCB Artwork"
        self.category = "Modify PCB"
        self.description = "Create polished PCB labels, icons, and connector callouts"
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).resolve().parent / "resources" / "kobee-bee.png")

    def __init__(self):
        super(KobeeStudioPlugin, self).__init__()
        self.compatibility = KiCadCompatibility()
        self.logger = self._make_logger()
        self.config_file = self._config_file()

    def _config_file(self):
        path = Path(wx.StandardPaths.Get().GetUserConfigDir()) / "kobee-studio"
        path.mkdir(parents=True, exist_ok=True)
        return str(path / "config.json")

    def _make_logger(self):
        logger = logging.getLogger("kobee_studio")
        if logger.handlers:
            return logger
        logger.setLevel(logging.INFO)
        logger.propagate = False
        path = Path(wx.StandardPaths.Get().GetUserConfigDir()) / "kobee-studio"
        path.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(path / "kobeestudio.log"), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        return logger

    def _diagnostics(self):
        self.logger.info(
            "Kobee Studio=%s KiCad=%s Python=%s OS=%s wx=%s",
            __version__,
            self.compatibility.version(),
            platform.python_version(),
            platform.platform(),
            wx.version(),
        )

    def _log_dependency_versions(self):
        import fontTools
        import svg2mod

        self.logger.info(
            "Dependencies fontTools=%s svg2mod=%s",
            getattr(fontTools, "__version__", "bundled"),
            getattr(svg2mod, "__version__", "bundled"),
        )

    def _show_error(self, title, error):
        self.logger.exception("%s: %s", title, error)
        wx.MessageBox("{}\n\nSee the Kobee Studio log in KiCad's user configuration directory.".format(error), title, wx.OK | wx.ICON_ERROR)

    def Run(self):
        self._diagnostics()
        try:
            # Import here so a missing bundled dependency becomes a visible
            # KiCad dialog instead of making the ActionPlugin vanish at load.
            from .core.text_geometry import TextGeometry

            geometry = TextGeometry()
            self._log_dependency_versions()
            while True:
                dialog = MainDialog(None, self.config_file, geometry.buzzard, self._generate_and_place)
                icon_path = (
                    Path(__file__).resolve().parent
                    / "resources"
                    / "kobee-studio-platform-icon.png"
                )
                configure_window_branding(dialog, icon_path, wx)
                try:
                    dialog.ShowModal()
                    restart_requested = bool(getattr(dialog, "restart_requested", False))
                finally:
                    dialog.Destroy()
                if not restart_requested:
                    break
        except Exception as error:
            self._show_error("Kobee Studio could not start", error)

    def _generate_and_place(self, dialog, buzzard):
        try:
            if not dialog.polys:
                dialog.EndModal(wx.ID_CANCEL)
                return
            from .core.legacy_adapter import build_footprint_payload
            from .core.studio_artwork import serialize_artwork

            layer = dialog.output_layer
            feature = None
            if dialog.artwork.header is not None:
                feature = {
                    "kind": "pin_header_2_54",
                    "data": dialog.artwork.header.to_dict(),
                }
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
            parameters = base64.b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("ascii")
            footprint_data = serialize_artwork(
                dialog.artwork, parameters, layer, output_layers=dialog.output_layers
            )
            footprint = self.compatibility.parse_footprint(footprint_data)
            self.compatibility.place(footprint, dialog.updateFootprint)
            self.logger.info("Placed label layers=%s primitive_count=%s", dialog.output_layers, len(dialog.polys))
            dialog.EndModal(wx.ID_OK)
        except Exception as error:
            self._show_error("Kobee Studio placement failed", error)


plugin = None


def register_plugin():
    global plugin
    plugin = KobeeStudioPlugin()
    plugin.register()
    return plugin


try:
    register_plugin()
except Exception:
    # KiCad reports plugin import errors itself.  Avoid using stderr because it
    # can be None in KiCad 10 and used to trigger recursive logging failures.
    logging.getLogger("kobee_studio.bootstrap").exception("Kobee Studio registration failed")

"""Regression checks for the isolated KiCad IPC migration foundation."""

from __future__ import annotations

import json
import importlib.util
import struct
import unittest
from pathlib import Path

from kobeestudio.core.composition import CompositionDocument
from kobeestudio.core.shape_geometry import Point
from kobeestudio.core.studio_artwork import StudioArtwork, StrokePath
from kobeestudio.integration.ipc_artwork import (
    METADATA_FIELD_NAME,
    artwork_polygons,
    decode_metadata,
    encode_metadata,
    selected_artwork,
    selected_legacy_artwork,
    IpcArtworkPlacement,
)
from kobeestudio.integration.ipc_session import (
    IpcSession,
    IpcUnavailableError,
    unique_client_name,
)


ROOT = Path(__file__).resolve().parents[1]


class _Board:
    def __init__(self):
        self.commit = object()
        self.messages = []
        self.created = []
        self.updated = []
        self.moved = []

    def get_selection(self):
        return ["selected"]

    def begin_commit(self):
        return self.commit

    def push_commit(self, transaction, message):
        self.messages.append(("push", transaction, message))

    def drop_commit(self, transaction):
        self.messages.append(("drop", transaction))

    def create_items(self, item):
        self.created.append(item)
        return list(item) if isinstance(item, (tuple, list)) else [item]

    def get_items_by_id(self, ids):
        requested = {getattr(item_id, "value", str(item_id)) for item_id in ids}
        candidates = []
        for batch in self.created + self.updated:
            candidates.extend(batch if isinstance(batch, (tuple, list)) else (batch,))
        return [
            item for item in candidates
            if getattr(getattr(item, "id", None), "value", None) in requested
        ]

    def remove_items(self, item):
        self.messages.append(("remove", item))

    def update_items(self, item):
        self.updated.append(item)
        return list(item) if isinstance(item, (tuple, list)) else [item]

    def add_to_selection(self, item):
        self.messages.append(("select", item))

    def interactive_move(self, item_id):
        self.moved.append(item_id.value)


class _Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.board = _Board()
        self.closed = False

    def get_board(self):
        return self.board

    def get_version(self):
        return "10.0.5"

    def close(self):
        self.closed = True


class _FakeId:
    def __init__(self, value):
        self.value = value

    def CopyFrom(self, other):
        self.value = other.value


class _FakeProto:
    def __init__(self, item_id):
        self.id = _FakeId(item_id)


class _FakeDefinition:
    def __init__(self, definition_id="definition-id"):
        self.proto = _FakeProto(definition_id)
        self.items = [object()]


class _PlacedFootprint:
    def __init__(
        self,
        item_id="placed-footprint-id",
        definition_id="definition-id",
        locked=False,
    ):
        self.proto = _FakeProto(item_id)
        self.definition = _FakeDefinition(definition_id)
        self.position = "position"
        self.orientation = "orientation"
        self.locked = locked

    @property
    def id(self):
        return self.proto.id


class _MinimalPlacement(IpcArtworkPlacement):
    def _api(self):
        return {}

    def build_footprint(self, artwork, payload, output_layer, output_layers=None):
        return _PlacedFootprint()

    @staticmethod
    def _angle_from_degrees(value):
        class FakeAngle:
            degrees = float(value)
        return FakeAngle()


class IpcMigrationTests(unittest.TestCase):
    def test_project_asset_context_uses_only_a_saved_board_filename(self):
        from kobeestudio.ui.editor_v2 import _active_board_path

        class Session:
            class board:
                name = str(ROOT / "example.kicad_pcb")

        self.assertEqual(ROOT / "example.kicad_pcb", _active_board_path(Session()))
        Session.board.name = "unsaved.kicad_pcb"
        self.assertIsNone(_active_board_path(Session()))
        Session.board.name = "/tmp/not-a-board.txt"
        self.assertIsNone(_active_board_path(Session()))

    def test_ui2_editor_is_used_by_both_plugin_entrypoints(self):
        for relative_path in (
            "kobeestudio/plugin.py",
            "ipc_plugin/kobeestudio_ipc.py",
        ):
            with self.subTest(entrypoint=relative_path):
                source = (ROOT / relative_path).read_text()
                self.assertIn("ui.editor_v2 import MainDialog", source)
                self.assertIn("KOBEE_USE_LEGACY_EDITOR", source)

    def test_ui2_editor_owns_its_layout_and_caches_preview_geometry(self):
        source = (ROOT / "kobeestudio/ui/editor_v2.py").read_text()
        themed_source = (ROOT / "kobeestudio/ui/themed_controls.py").read_text()
        self.assertIn("class StudioEditorDialog(wx.Dialog):", source)
        self.assertNotIn("class StudioEditorDialog(UpstreamDialog)", source)
        self.assertIn("class PreviewCanvas(wx.Panel):", source)
        self.assertIn("self._cache", source)
        self.assertIn("self._timer.StartOnce(300)", source)
        self.assertIn("self._preview_fingerprint", source)
        self.assertIn("wx.PostEvent(self, command)", source)
        self.assertNotIn("ProcessWindowEvent", source)
        self.assertNotIn("ProcessWindowEvent", themed_source)
        self.assertGreaterEqual(themed_source.count("wx.PostEvent"), 6)
        self.assertIn("dc.SetUserScale(self._zoom, self._zoom)", source)
        self.assertIn("self._size_timer.StartOnce(80)", source)
        self.assertNotIn("Reparent(", source)
        self.assertNotIn("Clear(delete_windows=True)", source)
        self.assertNotIn(".Update()", source)
        self.assertIn("Never unwind through wx's native paint callback", source)
        self.assertIn(
            "isinstance(control, (wx.Choice, ThemedChoice, PickerButton, SegmentedChoice))",
            source,
        )
        self.assertIn("page._schedule_layout(scroll_to_top=True)", source)
        self.assertIn("self.content = wx.ScrolledWindow", source)
        self.assertIn("self.content_panel = wx.Panel", source)
        self.assertIn("card = SettingsCard(self.content_panel, title)", source)
        self.assertIn("self.content_panel.Layout()", source)
        self.assertIn("self.columns_sizer.CalcMin().height", source)
        self.assertIn("self.content.SetVirtualSize(content_size)", source)
        self.assertIn("self.content.ShowScrollbars(never, never)", source)
        self.assertNotIn("self.columns_sizer.SetItemProportion", source)
        self.assertIn("right_column_item.SetProportion", source)
        self.assertIn("field_label.Wrap(92)", source)
        self.assertIn("workspace.Add(self.pages, 1", source)
        self.assertIn("workspace.Add(preview_panel, 1", source)
        self.assertIn('return "Container"', source)
        self.assertIn("ThemedCheckBox", source)
        self.assertIn("_kobee_auto_value_resolver", source)
        self.assertIn("preview_controls = wx.BoxSizer(wx.VERTICAL)", source)
        self.assertIn("preview_layer_row = wx.BoxSizer(wx.HORIZONTAL)", source)
        self.assertIn("preview_zoom_row = wx.BoxSizer(wx.HORIZONTAL)", source)
        self.assertIn("style |= wx.TE_MULTILINE | wx.VSCROLL", source)
        self.assertNotIn('self.editor.ShowScrollbars(never, never)', source)
        self.assertIn("control.ShowEnd()", source)
        self.assertIn("payload.SetMaxLength(48)", source)
        self.assertIn("caption.SetMaxLength(32)", source)
        self.assertIn("readable_text.SetMaxLength(96)", source)
        self.assertIn("class BrandedHeader(wx.Panel):", source)
        self.assertIn("icon=family", source)
        self.assertIn('("labels", "Standard", "Label")', source)
        self.assertIn('("labels", "Variables", "Label")', source)
        labels = [
            line for line in source.splitlines()
            if line.strip().startswith('("labels",')
        ]
        self.assertEqual('    ("labels", "Variables", "Label"),', labels[-1])
        self.assertIn('("labels", "Connector Overlay", "2.54 mm Pin Header")', source)
        self.assertIn('("graphics", "Imported Graphic", "Imported Graphic")', source)
        self.assertIn('("board_tools", "Cleanup", "Board Tools")', source)
        self.assertIn('("labels", "Component Callout", "Component Callout")', source)
        self.assertIn('("labels", "Component Array", "Component Array")', source)
        self.assertIn('("codes", "QR Code", "QR / Barcode")', source)
        self.assertIn('("codes", "Barcode", "QR / Barcode")', source)
        self.assertIn('"End treatment"', source)
        self.assertIn('"Long edges"', source)
        self.assertIn("def _update_container_ui", source)
        self.assertIn("def _update_machine_code_ui", source)
        self.assertIn("self.pages.ChangeSelection", source)
        self.assertIn("self.Freeze()", source)
        self.assertIn("self.request_preview()", source)
        self.assertIn("wx.CallAfter(self._apply_scheduled_layout)", source)
        self.assertIn("def DoGetBestSize(self):", source)
        self.assertIn("# which squeezes this final action row down to a thin, unusable strip.", source)
        self.assertIn("callback=self._choose_preset", source)
        self.assertIn("callback=self._choose_icon", source)
        self.assertIn('"Settings",', source)
        settings_source = (ROOT / "kobeestudio/ui/settings_dialog.py").read_text()
        self.assertIn("class SettingsDialog(wx.Dialog):", settings_source)
        self.assertIn("Include unsaved settings", settings_source)
        self.assertIn("Save and back up", settings_source)
        self.assertIn("def _preferences_from_controls", settings_source)
        self.assertIn("SymbolAssetId", source)
        self.assertIn("MEASUREMENT_SETTING_KEYS", source)
        self.assertIn("wx.CallAfter(self.callback, None)", source)
        self.assertIn("def _update_card_layout", source)
        self.assertIn("bind_numeric_mousewheel_guard(self)", themed_source)
        self.assertIn("def _bind_numeric_mousewheel_guards", (ROOT / "kobeestudio/ui/main_dialog.py").read_text())
        self.assertIn('("Label", "Label + symbol", "Symbol only"), "Label", rows=2', source)
        self.assertIn('title.replace("&", "and").upper()', source)
        self.assertNotIn('control.SetBackgroundColour(_palette()["active"])', source)

    def test_every_geometry_control_is_connected_to_live_preview(self):
        source = (ROOT / "kobeestudio/ui/main_dialog.py").read_text()
        bindings = source.split("def _bind_live_artwork_controls", 1)[1].split(
            "def _on_live_artwork_changed", 1
        )[0]
        expected_controls = (
            "m_FeatureSizeCtrl",
            "m_ShapeDirectionChoice",
            "m_IconHeightCtrl",
            "m_IconGapCtrl",
            "m_SubtitleFontChoice",
            "m_SubtitleHeightCtrl",
            "m_SubtitleLineSpacingCtrl",
            "m_SubtitleGapCtrl",
            "m_UnderlineThicknessCtrl",
            "m_UnderlineGapCtrl",
            "m_HeaderPadClearanceCtrl",
            "m_HeaderOpeningEndPaddingCtrl",
            "m_HeaderLeadingPaddingCtrl",
            "m_HeaderTrailingPaddingCtrl",
            "m_HeaderLabelPaddingCtrl",
            "m_HeaderPinOuterPaddingCtrl",
            "m_HeaderPinToLabelGapCtrl",
            "m_HeaderLabelOuterPaddingCtrl",
            "m_HeaderCrossSizeCtrl",
            "m_ComponentPositionChoice",
            "m_ComponentWidthCtrl",
            "m_ComponentHeightCtrl",
            "m_ComponentClearanceCtrl",
            "m_ComponentCutoutRadiusCtrl",
            "m_ComponentTextGapCtrl",
            "m_ComponentMinWidthCtrl",
            "m_ComponentMinHeightCtrl",
            "m_ComponentArrayCountCtrl",
            "m_ComponentArrayPitchCtrl",
            "m_MachineCodeModuleSizeCtrl",
            "m_MachineCodeBarHeightCtrl",
            "m_MachineCodeCaptionHeightCtrl",
            "m_MachineCodeFramePaddingCtrl",
            "m_MachineCodeContentHeightCtrl",
            "m_MachineCodeContentGapCtrl",
        )
        for control in expected_controls:
            with self.subTest(control=control):
                self.assertIn(control, bindings)

    def test_manifest_declares_supported_ipc_runtime(self):
        manifest = json.loads((ROOT / "ipc_plugin/plugin.json").read_text())
        self.assertEqual("https://go.kicad.org/api/schemas/v1", manifest["$schema"])
        self.assertEqual(
            "com.github.mrcpuddington.kobeestudio",
            manifest["identifier"],
        )
        self.assertEqual("python", manifest["runtime"]["type"])
        self.assertEqual("Kobee Studio", manifest["name"])
        action = manifest["actions"][0]
        self.assertEqual("kobeestudio_ipc.py", action["entrypoint"])
        self.assertEqual(["pcb"], action["scopes"])
        self.assertEqual("Create PCB Artwork", action["name"])
        expected_icons = ["kobee-toolbar-24.png", "kobee-toolbar-48.png"]
        self.assertEqual(expected_icons, action["icons-light"])
        self.assertEqual(expected_icons, action["icons-dark"])
        action_names = {item["identifier"]: item for item in manifest["actions"]}
        self.assertEqual("kobeestudio_add_designator.py", action_names["add-designator"]["entrypoint"])
        self.assertEqual("kobeestudio_remove_designators.py", action_names["remove-designators"]["entrypoint"])
        self.assertEqual("kobeestudio_remove_silkscreen.py", action_names["remove-silkscreen"]["entrypoint"])
        for icon_name, expected_size in zip(expected_icons, (24, 48)):
            icon_path = ROOT / "ipc_plugin" / icon_name
            icon_data = icon_path.read_bytes()
            self.assertEqual(b"\x89PNG\r\n\x1a\n", icon_data[:8])
            self.assertEqual(
                (expected_size, expected_size),
                struct.unpack(">II", icon_data[16:24]),
            )

        app_icon_data = (
            ROOT / "kobeestudio/resources/kobee-studio-app-icon.png"
        ).read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", app_icon_data[:8])
        app_icon_size = struct.unpack(">II", app_icon_data[16:24])
        self.assertGreaterEqual(app_icon_size[0], 1024)
        self.assertEqual(app_icon_size[0], app_icon_size[1])

    def test_pcm_metadata_matches_ipc_manifest_and_catalog_icon_rules(self):
        manifest = json.loads((ROOT / "ipc_plugin/plugin.json").read_text())
        metadata = json.loads((ROOT / "pcm/metadata_template.json").read_text())
        self.assertEqual(manifest["identifier"], metadata["identifier"])
        self.assertEqual("ipc", metadata["versions"][0]["runtime"])
        self.assertEqual("1.5.0", metadata["versions"][0]["version"])
        self.assertEqual("development", metadata["versions"][0]["status"])
        icon_data = (ROOT / "pcm/resources/icon.png").read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", icon_data[:8])
        self.assertEqual((64, 64), struct.unpack(">II", icon_data[16:24]))

    def test_ipc_requirements_use_kicad_bundled_wxpython(self):
        requirements = (ROOT / "ipc_plugin/requirements.txt").read_text()
        self.assertIn("kicad-python", requirements)
        self.assertIn("Pillow", requirements)
        self.assertIn("Brotli", requirements)
        self.assertIn("certifi", requirements)
        self.assertNotIn("wxPython", requirements)

    def test_pcm_builder_places_ipc_manifest_in_plugin_subdirectory(self):
        source = (ROOT / "pcm/build.py").read_text()
        self.assertIn('PLUGIN_DIR = PLUGINS / "com.github.mrcpuddington.kobeestudio"', source)
        self.assertIn('PLUGIN_DIR / filename', source)
        self.assertIn('"plugin.json"', source)
        self.assertNotIn('PLUGINS / filename', source)

    def test_windows_settings_scroller_uses_a_content_panel(self):
        """Keep the generated sizer out of wx.ScrolledWindow directly.

        Windows validates a window's native parent and containing sizer at a
        later layout pass.  Putting the legacy generated tree directly on the
        scroller made a text-height spinner edit capable of reaching an
        invalid ownership assertion.
        """
        source = (ROOT / "kobeestudio/ui/main_dialog.py").read_text()
        self.assertIn("settings_content = wx.Panel(scroller)", source)
        self.assertIn("settings_content.SetSizer(legacy_root)", source)
        self.assertIn("scroller_sizer.Add(settings_content", source)
        self.assertNotIn("scroller.SetSizer(legacy_root)", source)

    def test_new_numeric_dialogs_and_custom_pitch_keep_wheel_and_unit_guards(self):
        editor = (ROOT / "kobeestudio/ui/editor_v2.py").read_text()
        settings = (ROOT / "kobeestudio/ui/settings_dialog.py").read_text()
        self.assertIn('"HeaderCustomPitchCtrl",', editor)
        self.assertIn("custom_pitch.Bind(wx.EVT_TEXT, self._on_header_custom_pitch_changed)", editor)
        self.assertIn("Maximum label height at", editor)
        self.assertNotIn("wx.SpinCtrlDouble(self, min=0.1, max=1000", settings)
        self.assertIn("ThemedSpinCtrlDouble(self, min=0.1, max=1000", settings)

    def test_designator_action_uses_main_window_controls_and_live_preview(self):
        source = (ROOT / "kobeestudio/ui/editor_v2.py").read_text()
        entry = (ROOT / "ipc_plugin/kobeestudio_ipc.py").read_text()
        self.assertIn('"DesignatorScopeChoice"', source)
        self.assertIn('"Preview reference"', source)
        self.assertIn("self.prepare_designators()", source)
        self.assertIn("self._selection_timer.Start(450)", source)
        self.assertIn("self.designator_footer_button.Show(tool == \"Designators\")", source)
        self.assertNotIn('"Refresh board selection"', source)
        self.assertIn('self._tool != "Designators"', source)
        self.assertNotIn('wx.CallAfter(dialog.run_add_designators, "single")', entry)

    def test_ipc_session_uses_the_connection_details_from_kicad(self):
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "/tmp/api.sock", "KICAD_API_TOKEN": "secret"},
            client_factory=_Client,
        )
        self.assertEqual("/tmp/api.sock", session.kicad.kwargs["socket_path"])
        self.assertEqual("secret", session.kicad.kwargs["kicad_token"])
        self.assertEqual(["selected"], session.selected_items())
        transaction = session.begin_commit()
        session.commit(transaction, "Place Kobee Studio artwork")
        self.assertEqual(
            [("push", transaction, "Place Kobee Studio artwork")], session.board.messages
        )
        session.close()
        self.assertTrue(session.kicad.closed)

    def test_development_connection_accepts_kicads_empty_external_token(self):
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "ipc:///tmp/kicad/api.sock", "KICAD_API_TOKEN": ""},
            client_factory=_Client,
        )
        self.assertEqual("", session.kicad.kwargs["kicad_token"])

        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "ipc:///tmp/kicad/api.sock"},
            client_factory=_Client,
        )
        self.assertEqual("", session.kicad.kwargs["kicad_token"])

    def test_ipc_session_fails_clearly_outside_kicad(self):
        with self.assertRaises(IpcUnavailableError):
            IpcSession.connect(environ={}, client_factory=_Client)

    def test_each_plugin_process_has_a_unique_ipc_commit_identity(self):
        self.assertEqual("Kobee Studio (1234)", unique_client_name(process_id=1234))
        self.assertNotEqual(
            unique_client_name(process_id=1234),
            unique_client_name(process_id=5678),
        )

    def test_front_and_bottom_artwork_use_the_existing_mirror_rule(self):
        polygon = (Point(-2.0, -1.0), Point(1.0, -1.0), Point(1.0, 2.0))
        artwork = StudioArtwork(
            filled_polygons=(polygon,),
            strokes=(StrokePath(polygon, 0.2),),
            guides=(),
            document=CompositionDocument(objects=()),
        )
        front = artwork_polygons(artwork, "F.SilkS")
        bottom = artwork_polygons(artwork, "B.SilkS")
        self.assertEqual(polygon, front[0].points)
        self.assertEqual(tuple(Point(-p.x, p.y) for p in reversed(polygon)), bottom[0].points)
        self.assertTrue(front[0].filled)
        self.assertFalse(front[1].filled)
        self.assertEqual(0.2, front[1].stroke_width_mm)

    def test_ipc_artwork_can_be_offset_to_the_interactive_origin(self):
        polygon = (Point(9.0, 18.0), Point(11.0, 18.0), Point(10.0, 22.0))
        artwork = StudioArtwork(
            filled_polygons=(polygon,),
            strokes=(StrokePath(polygon, 0.2),),
            guides=(),
            document=CompositionDocument(objects=(), origin=Point(10.0, 20.0)),
        )
        shifted = artwork_polygons(artwork, "F.SilkS", offset=Point(-10.0, -20.0))
        self.assertEqual(
            (Point(-1.0, -2.0), Point(1.0, -2.0), Point(0.0, 2.0)),
            shifted[0].points,
        )

    def test_new_ipc_artwork_enters_interactive_move(self):
        artwork = StudioArtwork(
            filled_polygons=((Point(-1.0, -1.0), Point(1.0, -1.0), Point(0.0, 1.0)),),
            strokes=(),
            guides=(),
            document=CompositionDocument(objects=()),
        )
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "/tmp/api.sock", "KICAD_API_TOKEN": "secret"},
            client_factory=_Client,
        )
        placed = _MinimalPlacement(session).place(
            artwork,
            {"format": "kobee-studio-composition", "legacy_settings": {}},
            "F.SilkS",
        )
        self.assertIsInstance(placed, _PlacedFootprint)
        self.assertEqual(["placed-footprint-id"], session.board.moved)
        self.assertEqual(
            [
                (
                    "push",
                    session.board.commit,
                    "Place Kobee Studio artwork",
                ),
                ("select", placed),
            ],
            session.board.messages,
        )

    def test_updated_ipc_artwork_keeps_existing_position_without_interactive_move(self):
        artwork = StudioArtwork(
            filled_polygons=((Point(-1.0, -1.0), Point(1.0, -1.0), Point(0.0, 1.0)),),
            strokes=(),
            guides=(),
            document=CompositionDocument(objects=()),
        )
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "/tmp/api.sock", "KICAD_API_TOKEN": "secret"},
            client_factory=_Client,
        )
        old = _PlacedFootprint(
            item_id="existing-footprint-id",
            definition_id="existing-definition-id",
            locked=True,
        )
        placed = _MinimalPlacement(session).place(
            artwork,
            {"format": "kobee-studio-composition", "legacy_settings": {}},
            "F.SilkS",
            old_footprint=old,
        )
        self.assertEqual([], session.board.moved)
        self.assertEqual([], session.board.created)
        self.assertEqual([placed], session.board.updated)
        self.assertEqual("existing-footprint-id", placed.id.value)
        self.assertEqual("existing-definition-id", placed.definition.proto.id.value)
        self.assertTrue(placed.locked)
        self.assertNotIn(("remove", old), session.board.messages)
        self.assertEqual("position", placed.position)
        self.assertEqual("orientation", placed.orientation)

    def test_variable_text_update_is_atomic_and_keeps_footprint_identity(self):
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "/tmp/api.sock", "KICAD_API_TOKEN": "secret"},
            client_factory=_Client,
        )
        old = _PlacedFootprint(
            item_id="existing-variable-id",
            definition_id="existing-variable-definition",
            locked=True,
        )
        placement = _MinimalPlacement(session)
        placement.build_variable_footprint = lambda *_args, **_kwargs: _PlacedFootprint()
        placed = placement.place_variable_text(
            {"VariableTemplateText": "${REVISION}"},
            {"feature": {"kind": "variable_label"}},
            "F.SilkS",
            old_footprint=old,
        )
        self.assertEqual([], session.board.created)
        self.assertEqual([placed], session.board.updated)
        self.assertEqual("existing-variable-id", placed.id.value)
        self.assertEqual("existing-variable-definition", placed.definition.proto.id.value)
        self.assertEqual("position", placed.position)
        self.assertEqual("orientation", placed.orientation)
        self.assertTrue(placed.locked)
        self.assertEqual(
            "Update Kobee Studio variable label",
            next(item[2] for item in session.board.messages if item[0] == "push"),
        )

    def test_new_ipc_artwork_can_defer_move_until_modal_is_closed(self):
        artwork = StudioArtwork(
            filled_polygons=((Point(-1.0, -1.0), Point(1.0, -1.0), Point(0.0, 1.0)),),
            strokes=(),
            guides=(),
            document=CompositionDocument(objects=()),
        )
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "/tmp/api.sock", "KICAD_API_TOKEN": "secret"},
            client_factory=_Client,
        )
        placement = _MinimalPlacement(session)
        placed = placement.place(
            artwork,
            {"format": "kobee-studio-composition", "legacy_settings": {}},
            "F.SilkS",
            start_interactive_move=False,
        )
        self.assertEqual([], session.board.moved)
        placement.start_interactive_move(placed)
        self.assertEqual(["placed-footprint-id"], session.board.moved)

    def test_designator_batch_verifies_artwork_before_hiding_native_reference(self):
        class Attributes: angle = 32.5
        class Text:
            position = "native-reference-position"
            attributes = Attributes()
        class Field:
            text = Text(); visible = True
        class Source:
            reference_field = Field()
        artwork = StudioArtwork(
            filled_polygons=((Point(0,0),Point(1,0),Point(0,1)),), strokes=(), guides=(),
            document=CompositionDocument(objects=()),
        )
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET":"/tmp/api.sock","KICAD_API_TOKEN":"secret"}, client_factory=_Client,
        )
        existing = _PlacedFootprint("existing-designator", "existing-definition")
        created, updated = _MinimalPlacement(session).place_designators(((Source(),artwork,{},"F.SilkS",existing),))
        placed = session.board.updated[0][0]
        self.assertEqual((0,1),(created,updated))
        self.assertEqual("native-reference-position",placed.position)
        self.assertAlmostEqual(32.5,placed.orientation.degrees)
        self.assertEqual("existing-designator",placed.id.value)
        self.assertFalse(Source.reference_field.visible)
        pushes=[item for item in session.board.messages if item[0]=="push"]
        self.assertEqual(2,len(pushes))
        self.assertEqual("Create Kobee Studio designators", pushes[0][2])
        self.assertEqual("Hide native footprint references", pushes[1][2])

    def test_designator_verification_failure_never_hides_native_reference(self):
        class Attributes: angle = 0
        class Text: position = "position"; attributes = Attributes()
        class Field: text = Text(); visible = True
        class Source: reference_field = Field()
        artwork = StudioArtwork(
            filled_polygons=((Point(0,0),Point(1,0),Point(0,1)),),
            strokes=(), guides=(), document=CompositionDocument(objects=()),
        )
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET":"/tmp/api.sock","KICAD_API_TOKEN":"secret"}, client_factory=_Client,
        )
        placement = _MinimalPlacement(session)
        placement.build_footprint = lambda *_args, **_kwargs: _PlacedFootprint()
        empty = placement.build_footprint(None, None, None)
        empty.definition.items = []
        placement.build_footprint = lambda *_args, **_kwargs: empty
        with self.assertRaisesRegex(RuntimeError, "Native references were left visible"):
            placement.place_designators(((Source(), artwork, {}, "F.SilkS", None),))
        self.assertTrue(Source.reference_field.visible)

    @unittest.skipUnless(importlib.util.find_spec("kipy"), "kicad-python is not installed")
    def test_real_kipy_designator_keeps_visible_geometry_at_reference_anchor(self):
        from kipy.board_types import FootprintInstance
        from kipy.geometry import Vector2
        from kipy.proto.board.board_types_pb2 import BoardLayer
        from kipy.util import to_mm

        source = FootprintInstance()
        source.reference_field.text.value = "R17"
        source.reference_field.text.position = Vector2.from_xy_mm(42.0, 27.5)
        source.reference_field.text.attributes.angle = 37.0
        source.reference_field.layer = BoardLayer.BL_F_SilkS
        source.reference_field.visible = True
        source.layer = BoardLayer.BL_F_Cu
        artwork = StudioArtwork(
            filled_polygons=((Point(-1,-0.5),Point(1,-0.5),Point(0,0.5)),),
            strokes=(), guides=(), document=CompositionDocument(objects=()),
        )
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET":"/tmp/api.sock","KICAD_API_TOKEN":"secret"}, client_factory=_Client,
        )
        created, updated = IpcArtworkPlacement(session).place_designators(
            ((source, artwork, {"feature":{"kind":"designator_label"}}, "F.SilkS", None),)
        )
        generated = session.board.created[0][0]
        self.assertEqual((1, 0), (created, updated))
        self.assertAlmostEqual(42.0, to_mm(generated.position.x))
        self.assertAlmostEqual(27.5, to_mm(generated.position.y))
        self.assertAlmostEqual(37.0, generated.orientation.degrees)
        self.assertTrue(generated.definition.shapes)
        self.assertFalse(source.reference_field.visible)

    def test_partial_designator_creation_discards_transaction(self):
        class Attributes: angle = 0
        class Text: position = "position"; attributes = Attributes()
        class Field: text = Text(); visible = True
        class Source: reference_field = Field()
        artwork=StudioArtwork(filled_polygons=((Point(0,0),Point(1,0),Point(0,1)),),strokes=(),guides=(),document=CompositionDocument(objects=()))
        session=IpcSession.connect(environ={"KICAD_API_SOCKET":"/tmp/api.sock","KICAD_API_TOKEN":"secret"},client_factory=_Client)
        session.board.create_items=lambda items: []
        with self.assertRaisesRegex(RuntimeError,"rolled back"):
            _MinimalPlacement(session).place_designators(((Source(),artwork,{},"F.SilkS",None),))
        self.assertTrue(any(item[0]=="drop" for item in session.board.messages))
        self.assertTrue(Source.reference_field.visible)

    def test_metadata_round_trip_reopens_selected_artwork(self):
        payload = {
            "format": "kobee-studio-composition",
            "legacy_settings": {"MultiLineText": "POWER", "HeightCtrl": "1.2"},
        }
        self.assertEqual(payload, decode_metadata(encode_metadata(payload)))

        class Text:
            value = encode_metadata(payload)

        class Field:
            name = METADATA_FIELD_NAME
            text = Text()

        class Definition:
            items = [Field()]

        class Footprint:
            definition = Definition()

        loaded, footprint = selected_artwork([Footprint()])
        self.assertEqual("POWER", loaded["MultiLineText"])
        self.assertTrue(loaded["_LoadedFootprintSettings"])
        self.assertIsInstance(footprint, Footprint)

    def test_released_swig_footprint_metadata_opens_through_ipc(self):
        payload = {
            "format": "kobee-studio-composition",
            "legacy_settings": {"MultiLineText": "OLD LABEL", "StudioModeChoice": "Label"},
        }
        footprint = object()
        sexpr = '(footprint "kobee-studio" (tags "kb_params={}"))'.format(
            encode_metadata(payload)
        )
        loaded, selected = selected_legacy_artwork([footprint], sexpr)
        self.assertEqual("OLD LABEL", loaded["MultiLineText"])
        self.assertTrue(loaded["_LoadedFootprintSettings"])
        self.assertIs(footprint, selected)

    @unittest.skipUnless(importlib.util.find_spec("kipy"), "kicad-python is not installed")
    def test_variable_footprint_keeps_raw_native_kicad_text(self):
        from kipy.board_types import BoardText
        from kipy.proto.board.board_types_pb2 import BoardLayer
        from kipy.proto.common import types as common_types
        from kipy.util import to_mm

        settings = {
            "VariableTemplateText": "${BOARD_NAME}\nRev ${REVISION}",
            "HeightCtrl": 1.4,
            "NativeTextWidthCtrl": 1.1,
            "NativeStrokeWidthCtrl": 0.2,
            "LineSpacingCtrl": 1.25,
            "AlignmentChoice": "Right",
            "NativeBoldCheckbox": True,
            "NativeUnderlineCheckbox": True,
            "NativeKeepUprightCheckbox": True,
        }
        footprint = IpcArtworkPlacement(session=None).build_variable_footprint(
            settings,
            {
                "format": "kobee-studio-composition",
                "legacy_settings": settings,
                "feature": {"kind": "variable_label"},
            },
            "F.SilkS",
            output_layers=("F.SilkS", "B.SilkS"),
        )
        texts = [item for item in footprint.definition.items if isinstance(item, BoardText)]
        self.assertEqual(2, len(texts))
        self.assertTrue(all(item.value == "${BOARD_NAME}\nRev ${REVISION}" for item in texts))
        self.assertTrue(all(item.attributes.multiline for item in texts))
        self.assertEqual(BoardLayer.BL_F_SilkS, texts[0].layer)
        self.assertFalse(texts[0].attributes.mirrored)
        self.assertEqual(BoardLayer.BL_B_SilkS, texts[1].layer)
        self.assertTrue(texts[1].attributes.mirrored)
        self.assertAlmostEqual(1.4, to_mm(texts[0].attributes.size.y))
        self.assertAlmostEqual(1.1, to_mm(texts[0].attributes.size.x))
        self.assertAlmostEqual(0.2, to_mm(texts[0].attributes.stroke_width))
        self.assertEqual(common_types.HorizontalAlignment.HA_RIGHT, texts[0].attributes.horizontal_alignment)
        self.assertEqual(METADATA_FIELD_NAME, footprint.definition.items[-1].name)
        self.assertEqual(
            "variable_label",
            decode_metadata(footprint.definition.items[-1].text.value)["feature"]["kind"],
        )
        self.assertGreater(footprint.proto.ByteSize(), 0)

    @unittest.skipUnless(importlib.util.find_spec("kipy"), "kicad-python is not installed")
    def test_real_kicad_python_wrappers_build_an_ipc_footprint(self):
        polygon = (Point(-1.0, -0.5), Point(1.0, -0.5), Point(0.0, 0.5))
        artwork = StudioArtwork(
            filled_polygons=(polygon,),
            strokes=(),
            guides=(),
            document=CompositionDocument(objects=()),
        )
        placement = IpcArtworkPlacement(session=None)
        footprint = placement.build_footprint(
            artwork,
            {"format": "kobee-studio-composition", "legacy_settings": {}},
            "F.SilkS",
        )
        self.assertEqual(2, len(footprint.definition.items))
        self.assertEqual(METADATA_FIELD_NAME, footprint.definition.items[-1].name)
        self.assertTrue(footprint.attributes.not_in_schematic)
        self.assertGreater(footprint.proto.ByteSize(), 0)
        second = placement.build_footprint(
            artwork,
            {"format": "kobee-studio-composition", "legacy_settings": {}},
            "F.SilkS",
        )
        self.assertNotEqual(footprint.definition.id.name, second.definition.id.name)

    @unittest.skipUnless(importlib.util.find_spec("kipy"), "kicad-python is not installed")
    def test_ipc_footprint_repeats_artwork_on_each_selected_output_layer(self):
        polygon = (Point(-1.0, -0.5), Point(1.0, -0.5), Point(0.0, 0.5))
        artwork = StudioArtwork(
            filled_polygons=(polygon,), strokes=(), guides=(), document=CompositionDocument(objects=())
        )
        footprint = IpcArtworkPlacement(session=None).build_footprint(
            artwork,
            {"format": "kobee-studio-composition", "legacy_settings": {}},
            "F.SilkS",
            output_layers=("F.SilkS", "B.Mask", "F.Cu"),
        )
        # One polygon for every target plus the metadata field.
        self.assertEqual(4, len(footprint.definition.items))
        self.assertEqual(METADATA_FIELD_NAME, footprint.definition.items[-1].name)


if __name__ == "__main__":
    unittest.main()

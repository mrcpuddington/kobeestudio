"""Exercise real editor controls with tools/run_tests.py (wxApp required)."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import wx

from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.ui.editor_v2 import StudioEditorDialog
from kobeestudio.ui.settings_dialog import SettingsDialog, PngTraceDialog
from kobeestudio.ui.themed_controls import ThemedListBox, ThemedActionButton
from kobeestudio.ui.theme import is_dark_mode, set_appearance_preference
from kobeestudio.core.app_preferences import AppPreferences, AppPreferencesStore


@unittest.skipUnless(wx.GetApp(), "run tools/run_tests.py to initialize wx")
class EditorWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.TemporaryDirectory(prefix="kobee-workflow-test-")
        cls.dialog = StudioEditorDialog(None, str(Path(cls.data.name) / "config.json"),
                                       TextGeometry().buzzard, lambda *_: None)

    @classmethod
    def tearDownClass(cls):
        cls.dialog.Destroy()
        wx.Yield()
        cls.data.cleanup()

    def tearDown(self):
        self.dialog._timer.Stop()

    def make_settings(self):
        return SettingsDialog(
            self.dialog, preferences_store=self.dialog.preferences_store,
            profile_store=self.dialog.profile_store, global_asset_store=self.dialog.global_asset_store,
            global_label_store=self.dialog.global_label_store, project_label_store=None,
            current_module="labels", preferences_changed=lambda *_: None,
            project_asset_store=None, symbol_catalog=self.dialog.symbol_catalog,
        )

    def test_late_font_completions_are_ignored_after_destroy(self):
        dialog = self.make_settings()
        dialog.Destroy()
        wx.Yield()
        # These callbacks used to dereference dead native controls.
        dialog._font_catalog_finished([], None)
        dialog._font_repair_finished(None, OSError("offline"))
        dialog._font_install_finished([], [])
        dialog._font_preview_ready(0, "Roboto", 400, "normal", "R1", None, OSError("offline"))

    def test_settings_buttons_accept_native_clicks_without_event_arguments(self):
        import inspect
        dialog = self.make_settings()
        try:
            pending = [dialog]
            while pending:
                control = pending.pop()
                pending.extend(control.GetChildren())
                if isinstance(control, ThemedActionButton):
                    with self.subTest(button=control.GetLabel()):
                        inspect.signature(control.callback).bind()
            dialog.available_font_list.SetSelection(wx.NOT_FOUND)
            dialog.available_action_button.Enable()
            with patch("wx.MessageBox", return_value=wx.OK) as message:
                dialog.available_action_button._on_click(None)
                self.assertIn("Select a font", message.call_args[0][0])
            with patch("kobeestudio.ui.settings_dialog.threading.Thread") as worker:
                dialog.refresh_catalog_button._on_click(None)
                worker.return_value.start.assert_called_once()
                self.assertIn("Refreshing", dialog.font_status.GetLabel())
            with patch.object(dialog, "_component_dialog") as component:
                dialog._add_component()
                component.assert_called_once()
        finally:
            dialog.Destroy()

    def test_editor_destruction_stops_child_preview_timers(self):
        dialog = StudioEditorDialog(None, str(Path(self.data.name) / "config.json"),
                                    TextGeometry().buzzard, lambda *_: None)
        timer = dialog.preview._size_timer
        timer.StartOnce(60000)
        dialog.Destroy()
        self.assertFalse(timer.IsRunning())
        wx.Yield()
        dialog._missing_font_finished(None, None)

    def test_repaired_font_replaces_missing_preview_snapshot(self):
        dialog = self.make_settings()
        missing = SimpleNamespace(face_id="repair-test", renderer_name="repair-renderer", missing=True)
        repaired = SimpleNamespace(face_id=missing.face_id, renderer_name=missing.renderer_name,
                                   missing=False, display_name="Repaired font")
        dialog._preview_font = {"kind": "google", "face": missing, "renderer": missing.renderer_name}
        try:
            with patch.object(dialog, "_start_font_preview") as preview:
                dialog._font_repair_finished(repaired, None)
                self.assertIs(repaired, dialog._preview_font["face"])
                preview.assert_called_once_with()
            self.assertTrue(dialog.restart_editor)
        finally:
            dialog.Destroy()

    def test_font_repair_keeps_a_different_font_selected_and_previewed(self):
        dialog = self.make_settings()
        repaired = SimpleNamespace(face_id="repair-test", renderer_name="repair-renderer",
                                   missing=False, display_name="Repaired font")
        item = dialog._activated_fonts[0]
        dialog.activated_font_list.SetSelection(0)
        dialog._preview_font = item
        try:
            with patch.object(dialog, "_start_font_preview") as preview:
                dialog._font_repair_finished(repaired, None)
                preview.assert_not_called()
            self.assertEqual(item["renderer"], dialog._selected_activated_font()["renderer"])
            self.assertIs(item, dialog._preview_font)
        finally:
            dialog.Destroy()

    def test_late_png_preview_is_ignored_after_destroy(self):
        from PIL import Image
        source = Path(self.data.name) / "trace.png"
        Image.new("RGBA", (4, 4), (0, 0, 0, 255)).save(source)
        dialog = PngTraceDialog(self.dialog, source)
        generation = dialog._preview_generation
        dialog.Destroy()
        wx.Yield()
        dialog._finish_preview(generation, None, OSError("missing source"))

    def test_missing_font_completion_does_not_change_another_tools_typeface(self):
        self.dialog._select_tool("Standard")
        renderer = self.dialog.active_page._selected_font_renderer(self.dialog.active_page.controls["FontComboBox"])
        face = SimpleNamespace(renderer_name=renderer, path=Path(__file__).resolve().parents[1] / "kobeestudio/fonts" / (renderer + ".ttf"))
        self.dialog._select_tool("Component Callout")
        choice = self.dialog.active_page.controls["FontComboBox"]
        choice.SetStringSelection(self.dialog.active_page._font_label("UbuntuMono-B"))
        before = choice.GetStringSelection()
        self.dialog._missing_font_finished(face, None, "Standard", renderer)
        self.assertEqual(before, choice.GetStringSelection())

    def test_modal_close_stops_timers_and_discards_pending_results(self):
        dialog = self.make_settings()
        try:
            dialog._font_preview_timer.StartOnce(60000)
            before = dialog.font_status.GetLabel()
            wx.CallAfter(dialog.EndModal, wx.ID_CANCEL)
            self.assertEqual(wx.ID_CANCEL, dialog.ShowModal())
            self.assertFalse(dialog._font_preview_timer.IsRunning())
            dialog._font_catalog_finished([], None)
            self.assertEqual(before, dialog.font_status.GetLabel())
        finally:
            dialog.Destroy()

    def test_optional_project_data_failure_does_not_break_saving_preferences(self):
        with patch("kobeestudio.ui.settings_dialog.ProjectDataSettingsPage", side_effect=ValueError("bad catalog")):
            dialog = self.make_settings()
        try:
            with patch.object(dialog, "EndModal") as end, patch.object(dialog, "_save_preferences", return_value=True):
                dialog._on_ok()
                end.assert_called_once_with(wx.ID_OK)
        finally:
            dialog.Destroy()

    def test_empty_library_disables_selection_only_actions(self):
        dialog = self.make_settings()
        try:
            self.assertFalse(dialog.add_variant_button.IsEnabled())
            self.assertFalse(dialog.delete_upload_button.IsEnabled())
            self.assertFalse(dialog.edit_png_button.IsEnabled())
            self.assertTrue(dialog.upload_png_button.IsEnabled())
        finally:
            dialog.Destroy()

    def test_appearance_change_keeps_existing_window_on_one_palette(self):
        old_preferences = self.dialog.preferences
        try:
            set_appearance_preference("dark")
            with patch("wx.MessageBox"):
                self.dialog._on_preferences_changed(replace(old_preferences, appearance="light"))
            self.assertTrue(is_dark_mode(wx))
        finally:
            self.dialog.preferences = old_preferences
            set_appearance_preference(old_preferences.appearance)

    def test_library_restart_preserves_unsaved_forms_layers_and_navigation(self):
        self.dialog._select_tool("Standard")
        self.dialog.active_page.controls["MultiLineText"].ChangeValue("UNSAVED LABEL")
        self.dialog.active_page._show_section("Typography")
        self.dialog._select_tool("Barcode")
        self.dialog._set_output_layers(("F.SilkS", "B.Mask"), "B.Mask")
        state = self.dialog.capture_session_state()
        restored = StudioEditorDialog(None, str(Path(self.data.name) / "config.json"),
                                      TextGeometry().buzzard, lambda *_: None)
        try:
            restored.restore_session_state(state)
            self.assertEqual("Barcode", restored._tool)
            self.assertEqual(("F.SilkS", "B.Mask"), restored.output_layers)
            self.assertEqual("B.Mask", restored.output_layer)
            standard = restored.page_by_tool["Standard"]
            self.assertEqual("UNSAVED LABEL", standard.controls["MultiLineText"].GetValue())
            self.assertTrue(standard.section_buttons["Typography"].active)
            self.assertTrue(restored.place_button.IsShown())
        finally:
            restored.Destroy()
            self.dialog._select_tool("Standard")
            self.dialog.active_page.controls["MultiLineText"].ChangeValue("LABEL")

    def test_non_artwork_pages_can_capture_and_restore_a_session(self):
        for tool in ("Project Data", "Cleanup"):
            self.dialog._select_tool(tool)
            state = self.dialog.capture_session_state()
            self.dialog.restore_session_state(state)
            self.assertEqual(tool, self.dialog._tool)
            self.assertFalse(self.dialog.place_button.IsShown())

    def test_project_data_reloads_keep_native_fields_readable(self):
        from kobeestudio.core.project_data import ProjectData, ProjectDataCatalog, ProjectDataStore
        from kobeestudio.ui.project_data_ui import ProjectDataPage

        project = Path(self.data.name) / "acceptance.kicad_pro"
        editor = SimpleNamespace(
            project_path=project, project_data_store=ProjectDataStore(project),
            project_data=ProjectData.empty(), project_data_catalog=ProjectDataCatalog.empty(),
            project_data_recovery_error=None, project_data_record_exists=False,
        )
        def luminance(colour):
            channels = [value / 255 for value in colour.Get()[:3]]
            linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
            return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

        try:
            for appearance in ("light", "dark"):
                set_appearance_preference(appearance)
                page = ProjectDataPage(self.dialog, editor)
                try:
                    # Selection, saving and syncing rebuild the entire page.
                    page.reload(editor.project_data, editor.project_data_catalog)
                    for child in page.GetChildren():
                        if isinstance(child, (wx.StaticText, wx.TextCtrl)):
                            foreground = luminance(child.GetForegroundColour())
                            background = luminance(child.GetBackgroundColour() if isinstance(child, wx.TextCtrl) else page.GetBackgroundColour())
                            ratio = (max(foreground, background) + .05) / (min(foreground, background) + .05)
                            self.assertGreaterEqual(ratio, 4.5, (appearance, child.GetLabel()))
                finally:
                    page.Destroy()
        finally:
            set_appearance_preference(self.dialog.preferences.appearance)

    def test_project_data_buttons_invoke_handlers_and_copy_selected_token(self):
        import inspect
        from kobeestudio.core.project_data import ProjectData, ProjectDataCatalog, ProjectDataStore
        from kobeestudio.ui.project_data_ui import ProjectDataPage

        project = Path(self.data.name) / "acceptance.kicad_pro"
        editor = SimpleNamespace(
            project_path=project, project_data_store=ProjectDataStore(project),
            project_data=ProjectData.empty(), project_data_catalog=ProjectDataCatalog.empty(),
            project_data_recovery_error=None, project_data_record_exists=False,
            _file_text_variables=lambda: {},
        )
        page = ProjectDataPage(self.dialog, editor)
        try:
            buttons = {child.GetLabel(): child for child in page.GetChildren() if isinstance(child, ThemedActionButton)}
            # Every painted button calls its callback without an event argument.
            for label, button in buttons.items():
                with self.subTest(button=label):
                    inspect.signature(button.callback).bind()
            with patch("wx.MessageBox", return_value=wx.OK) as message:
                buttons["How Project Data works"]._on_click(None)
                self.assertIn("Global fields", message.call_args[0][0])
                buttons["Preview KiCad changes"]._on_click(None)
                self.assertIn("KOBEE_PROJECT_PROJECT_NAME", message.call_args[0][0])
            page.variable_list.SetSelection(0)
            with patch("wx.TheClipboard") as clipboard:
                clipboard.Open.return_value = True
                buttons["Copy selected token"]._on_click(None)
                self.assertEqual("${KOBEE_GLOBAL_COMPANY_NAME}", clipboard.SetData.call_args[0][0].GetText())
                clipboard.Close.assert_called_once()
            editor.project_data = ProjectData.empty().with_checkpoint({
                "default_revision": "A", "default_issue_date": "2026-11-06", "default_status": "Draft",
            })
            page.reload(editor.project_data, editor.project_data_catalog)
            page.history.SetSelection(0)
            with patch("wx.MessageBox", return_value=wx.OK) as message:
                details = next(child for child in page.GetChildren() if isinstance(child, ThemedActionButton) and child.GetLabel() == "View selected details")
                details._on_click(None)
                self.assertIn("Revision: A", message.call_args[0][0])
        finally:
            page.Destroy()

    def test_every_artwork_tool_has_a_valid_initial_preview(self):
        for tool in ("Standard", "Connector Overlay", "Component Callout", "Component Array", "QR Code", "Barcode"):
            with self.subTest(tool=tool):
                self.dialog._select_tool(tool)
                self.dialog.request_preview(immediate=True)
                self.assertIsNone(self.dialog.error)
                self.assertIsNotNone(self.dialog.artwork)
                self.assertTrue(self.dialog.place_button.IsEnabled())

    def test_invalid_input_disables_placement_and_recovers_after_edit(self):
        self.dialog._select_tool("Standard")
        text = self.dialog.active_page.controls["MultiLineText"]
        text.ChangeValue("")
        self.dialog.request_preview(immediate=True)
        self.assertIsNotNone(self.dialog.error)
        self.assertFalse(self.dialog.place_button.IsEnabled())
        text.ChangeValue("RECOVERED")
        self.dialog.request_preview(immediate=True)
        self.assertIsNone(self.dialog.error)
        self.assertTrue(self.dialog.place_button.IsEnabled())

    def test_settings_read_errors_stay_inside_preview_error_boundary(self):
        self.dialog._select_tool("Standard")
        with patch.object(self.dialog, "CurrentSettings", side_effect=OSError("Imported file is missing")), patch("kobeestudio.ui.editor_v2.traceback.print_exc"):
            self.dialog.request_preview(immediate=True)
        self.assertIn("Imported file is missing", self.dialog.error)
        self.assertFalse(self.dialog.place_button.IsEnabled())

    def test_compact_window_keeps_navigation_and_target_layers_in_bounds(self):
        original_size = self.dialog.GetSize()
        try:
            self.dialog._select_tool("Standard")
            self.dialog.SetSize(wx.Size(760, 600))
            self.dialog.Layout()
            wx.Yield()
            for control in tuple(self.dialog.tool_buttons.values()) + tuple(self.dialog.layer_toggles.values()):
                if control.IsShown():
                    parent = control.GetParent()
                    rect = control.GetRect()
                    self.assertGreaterEqual(rect.x, 0)
                    self.assertLessEqual(rect.GetRight(), parent.GetClientSize().width)
                    self.assertLessEqual(rect.GetBottom(), parent.GetClientSize().height)
        finally:
            self.dialog.SetSize(original_size)
            self.dialog.Layout()

    def test_graphics_empty_state_cannot_place_a_previous_label(self):
        self.dialog._select_tool("Imported Graphic")
        self.dialog.request_preview(immediate=True)
        self.assertIsNone(self.dialog.artwork)
        self.assertFalse(self.dialog.place_button.IsEnabled())
        self.assertIn("Choose or upload", self.dialog.preview_error.GetLabel())

    def test_typing_graphic_dimensions_keeps_the_edited_value_and_aspect_ratio(self):
        self.dialog._select_tool("Imported Graphic")
        page = self.dialog.active_page
        width = page.controls["GraphicWidthCtrl"]
        height = page.controls["GraphicHeightCtrl"]
        page.controls["GraphicAspectLock"].SetValue(True)
        page._graphic_aspect_ratio = 20.0 / 12.0
        width.SetValue(20)
        height.SetValue(12)
        # Exercise the child editor's native EVT_TEXT and its relayed event.
        # A child event used to be mistaken for a height edit and reset width.
        width.editor.SetValue("10")
        wx.Yield()
        self.assertAlmostEqual(10, width.GetValue())
        self.assertAlmostEqual(6, height.GetValue())
        height.editor.SetValue("9")
        wx.Yield()
        self.assertAlmostEqual(15, width.GetValue())
        self.assertAlmostEqual(9, height.GetValue())

    def test_cached_preview_reenables_placement_after_debounce(self):
        self.dialog._select_tool("Standard")
        self.dialog.request_preview(immediate=True)
        self.dialog.request_preview()
        self.assertFalse(self.dialog.place_button.IsEnabled())
        self.dialog.request_preview(immediate=True)
        self.assertTrue(self.dialog.place_button.IsEnabled())

    def test_board_operations_hide_artwork_placement_controls(self):
        for tool in ("Cleanup", "Project Data"):
            self.dialog._select_tool(tool)
            self.assertFalse(self.dialog.place_button.IsShown())
            self.assertFalse(self.dialog.preview_panel.IsShown())

    def test_returning_to_a_family_restores_the_last_tool(self):
        self.dialog._select_tool("Barcode")
        self.dialog._select_family("labels")
        self.dialog._select_family("codes")
        self.assertEqual("Barcode", self.dialog._tool)

    def test_settings_font_lists_retain_browsable_height(self):
        dialog = SettingsDialog(
            self.dialog, preferences_store=self.dialog.preferences_store,
            profile_store=self.dialog.profile_store,
            global_asset_store=self.dialog.global_asset_store,
            global_label_store=self.dialog.global_label_store,
            project_label_store=None, current_module="labels",
            preferences_changed=lambda *_: None,
            project_asset_store=None, symbol_catalog=self.dialog.symbol_catalog,
        )
        try:
            dialog.SetSize(wx.Size(780, 620))
            dialog.Layout()
            dialog._select_page(2)
            self.assertGreaterEqual(dialog.available_font_list.GetSize().height, 200)
            self.assertGreaterEqual(dialog.activated_font_list.GetSize().height, 200)
        finally:
            dialog.Destroy()

    def test_compact_font_settings_stack_columns_and_fit_actions(self):
        dialog = self.make_settings()
        try:
            dialog.SetSize(wx.Size(620, 460))
            dialog.Layout()
            dialog._select_page(2)
            wx.Yield()
            self.assertEqual(wx.VERTICAL, dialog._font_columns.GetOrientation())
            for control in (dialog.available_font_list, dialog.activated_font_list,
                            dialog.font_favourite_button, dialog.deactivate_font_button,
                            dialog.repair_font_button):
                self.assertLessEqual(control.GetRect().GetRight(), dialog.fonts_page.GetClientSize().width)
        finally:
            dialog.Destroy()
            wx.Yield()

    def test_dynamic_action_labels_reserve_the_painted_text_width(self):
        button = ThemedActionButton(self.dialog, "Remove", lambda: None)
        try:
            old_width = button.GetMinSize().width
            button.SetLabel("Remove downloaded font")
            dc = wx.ClientDC(button)
            dc.SetFont(button.GetFont().Bold())
            width, _ = dc.GetTextExtent(button.GetLabel())
            self.assertGreater(button.GetMinSize().width, old_width)
            self.assertGreaterEqual(button.GetMinSize().width, width + 28)
        finally:
            button.Destroy()

    def test_compact_asset_settings_keep_the_preview_usable(self):
        dialog = self.make_settings()
        try:
            dialog.SetSize(wx.Size(620, 460))
            dialog.Layout()
            dialog._select_page(3)
            dialog._select_asset_page(0)
            wx.Yield()
            self.assertGreaterEqual(dialog.asset_preview.GetSize().height, 230)
            self.assertGreater(dialog.upload_page.GetVirtualSize().height,
                               dialog.upload_page.GetClientSize().height)
        finally:
            dialog.Destroy()
            wx.Yield()

    def test_library_list_can_be_navigated_with_keyboard(self):
        control = ThemedListBox(self.dialog, choices=("First", "Second", "Third"))
        try:
            for key, expected in ((wx.WXK_DOWN, 0), (wx.WXK_END, 2), (wx.WXK_UP, 1), (wx.WXK_HOME, 0)):
                event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
                event.SetKeyCode(key)
                control._on_key(event)
                self.assertEqual(expected, control.GetSelection())
        finally:
            control.Destroy()

"""Check every tool section using real light and dark desktop controls."""

import tempfile
import unittest
from pathlib import Path

import wx

from kobeestudio.core.app_preferences import AppPreferences, AppPreferencesStore
from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.ui.editor_v2 import StudioEditorDialog, ToolPage
from kobeestudio.ui.theme import set_appearance_preference


@unittest.skipUnless(wx.GetApp(), "run tools/run_tests.py to initialize wx")
class UiConsistencyTests(unittest.TestCase):
    def tearDown(self):
        set_appearance_preference("system")

    def test_every_tool_section_fits_its_card_in_both_themes(self):
        for appearance in ("light", "dark"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                AppPreferencesStore(root).save(AppPreferences(appearance=appearance))
                dialog = StudioEditorDialog(None, str(root / "config.json"), TextGeometry().buzzard, lambda *_: None)
                try:
                    dialog.SetSize(wx.Size(760, 600))
                    dialog.Layout()
                    for tool, page in dialog.page_by_tool.items():
                        dialog._select_tool(tool)
                        dialog.Layout()
                        if not isinstance(page, ToolPage):
                            continue
                        for section in page.sections:
                            page._show_section(section)
                            page._apply_scheduled_layout()
                            for key, control in page.controls.items():
                                if not control.IsShown() or not control.GetParent().IsShown():
                                    continue
                                with self.subTest(appearance=appearance, tool=tool, section=section, field=key):
                                    rect = control.GetRect()
                                    size = control.GetParent().GetClientSize()
                                    self.assertGreaterEqual(rect.x, 0)
                                    self.assertGreaterEqual(rect.y, 0)
                                    self.assertLessEqual(rect.GetRight(), size.width)
                                    self.assertLessEqual(rect.GetBottom(), size.height)
                finally:
                    dialog.Destroy()
                    wx.Yield()

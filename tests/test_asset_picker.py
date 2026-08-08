"""Catalog-level checks for the searchable visual asset picker."""

from __future__ import annotations

import unittest

from kobeestudio.ui.main_dialog import (
    KOBEE_STUDIO_DOCS_URL,
    MainDialog,
    _launch_settings,
    _subtitle_font_name,
    mode_defaults,
)
from kobeestudio.ui.asset_picker import (
    AssetPickerDialog,
    filter_picker_items,
    icon_picker_items,
    label_picker_items,
)


class AssetPickerTests(unittest.TestCase):
    def test_in_app_help_uses_the_hosted_kobee_studio_docs(self):
        self.assertEqual(
            "https://www.coreybusuttil.com/kobeestudio/docs/",
            KOBEE_STUDIO_DOCS_URL,
        )

    def test_picker_contains_every_catalog_item_plus_clear_choice(self):
        icons = icon_picker_items()
        labels = label_picker_items()
        self.assertEqual("", icons[0].asset_id)
        self.assertEqual("", labels[0].asset_id)
        self.assertTrue(any(item.asset_id == "builtin.warning" for item in icons))
        self.assertTrue(any(item.asset_id == "gnd" for item in labels))

    def test_search_matches_names_categories_and_multiple_words(self):
        labels = label_picker_items()
        self.assertEqual(
            ("gnd", "pgnd", "agnd"),
            tuple(item.asset_id for item in filter_picker_items(labels, "power gnd")),
        )
        electrical = filter_picker_items(icon_picker_items(), category="Electrical")
        self.assertTrue(electrical)
        self.assertTrue(all(item.category == "Electrical" for item in electrical))
        self.assertEqual(
            ("builtin.centre_negative",),
            tuple(item.asset_id for item in filter_picker_items(icon_picker_items(), "centre negative")),
        )

    def test_selecting_a_card_does_not_rebuild_or_destroy_clicked_button(self):
        class Card:
            def __init__(self):
                self.bitmap = None
                self.refreshed = False

            def SetBitmap(self, bitmap):
                self.bitmap = bitmap

            def Refresh(self, erase_background):
                self.refreshed = not erase_background

        class Event:
            skipped = False

            def Skip(self):
                self.skipped = True

        class PickerState:
            _selected_id = "first"
            _cards = {
                "first": (Card(), "first item"),
                "second": (Card(), "second item"),
            }

            @staticmethod
            def _thumbnail(item, selected):
                return (item, selected)

        picker = PickerState()
        event = Event()
        AssetPickerDialog._on_selected(picker, event, "second")
        self.assertEqual("second", picker._selected_id)
        self.assertEqual(("first item", False), picker._cards["first"][0].bitmap)
        self.assertEqual(("second item", True), picker._cards["second"][0].bitmap)
        self.assertTrue(event.skipped)



    def test_picker_button_caption_is_bounded_but_tooltip_keeps_full_name(self):
        class Button:
            label = ""
            tooltip = ""

            def SetLabel(self, value):
                self.label = value

            def SetToolTip(self, value):
                self.tooltip = value

        button = Button()
        full_name = "A deliberately long future symbol preset name"
        MainDialog._set_picker_button(
            button, full_name, "Browse symbols…", "symbol"
        )
        self.assertLessEqual(len(button.label), 28)
        self.assertTrue(button.label.endswith("…  ▾"))
        self.assertIn(full_name, button.tooltip)

    def test_subtitle_typeface_matches_main_unless_overridden(self):
        self.assertEqual(
            "FreddySpark-Regular",
            _subtitle_font_name("Match main typeface", "FreddySpark-Regular"),
        )
        self.assertEqual(
            "UbuntuMono-B",
            _subtitle_font_name("UbuntuMono-B", "FreddySpark-Regular"),
        )

    def test_fresh_launch_ignores_previous_session_settings(self):
        incoming = {
            "StudioModeChoice": "Component Array",
            "HeightCtrl": 9.0,
            "MultiLineText": "OLD",
            "LayerComboBox": "B.Cu",
            "advancedCheckbox": True,
        }
        settings, editing = _launch_settings(incoming, MainDialog.config_defaults)
        self.assertFalse(editing)
        self.assertNotIn("StudioModeChoice", settings)
        self.assertEqual("1.2", settings["HeightCtrl"])
        self.assertEqual("LABEL", settings["MultiLineText"])
        self.assertEqual("F.SilkS", settings["LayerComboBox"])
        self.assertFalse(settings["advancedCheckbox"])

    def test_each_new_artwork_mode_has_a_renderable_placeholder(self):
        header = mode_defaults("2.54 mm Pin Header")
        self.assertEqual("Pin 1\nPin 2\nPin 3\nPin 4", header["MultiLineText"])
        self.assertEqual(4, header["HeaderPinCountCtrl"])
        self.assertEqual("Vertical", header["HeaderOrientationChoice"])
        self.assertEqual("Left", header["HeaderPinSideChoice"])
        self.assertEqual("Continuous plug opening", header["HeaderOpeningChoice"])

        self.assertEqual("COMPONENT", mode_defaults("Component Callout")["MultiLineText"])
        self.assertEqual("LED 1\nLED 2\nLED 3", mode_defaults("Component Array")["MultiLineText"])
        self.assertEqual(
            "https://github.com/mrcpuddington/kobeestudio",
            mode_defaults("QR / Barcode")["MultiLineText"],
        )

    def test_selected_existing_artwork_keeps_its_embedded_settings(self):
        incoming = {
            "_LoadedFootprintSettings": True,
            "StudioModeChoice": "Component Array",
            "HeightCtrl": 2.4,
            "MultiLineText": "LED 1\nLED 2",
        }
        settings, editing = _launch_settings(incoming, MainDialog.config_defaults)
        self.assertTrue(editing)
        self.assertEqual(incoming, settings)

if __name__ == "__main__":
    unittest.main()

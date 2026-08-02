"""Catalog-level checks for the searchable visual asset picker."""

from __future__ import annotations

import unittest

from kibeezard.ui.asset_picker import (
    filter_picker_items,
    icon_picker_items,
    label_picker_items,
)


class AssetPickerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

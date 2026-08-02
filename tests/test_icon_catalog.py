"""Checks for the built-in fabrication-safe icon and label catalogs."""

from __future__ import annotations

import math
import unittest

from kibeezard.core.icon_catalog import (
    BUILTIN_ICONS,
    ICON_BY_ID,
    LABEL_PRESETS,
    render_builtin_icon,
)
from kibeezard.core.composition import Point


class IconCatalogTests(unittest.TestCase):
    def test_every_icon_has_unique_finite_geometry_at_exact_height(self):
        self.assertEqual(len(BUILTIN_ICONS), len(ICON_BY_ID))
        for icon in BUILTIN_ICONS:
            with self.subTest(icon=icon.asset_id):
                vectors = render_builtin_icon(icon.asset_id, 1.6)
                self.assertAlmostEqual(1.6, vectors.size.height)
                self.assertGreater(vectors.size.width, 0.0)
                self.assertTrue(
                    all(
                        math.isfinite(point.x) and math.isfinite(point.y)
                        for polygon in vectors.polygons
                        for point in polygon
                    )
                )

    def test_unknown_icons_and_invalid_heights_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown built-in icon"):
            render_builtin_icon("builtin.missing", 1.0)
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            render_builtin_icon("builtin.ground", 0.0)

    def test_label_presets_are_unique_and_only_reference_known_icons(self):
        self.assertEqual(len(LABEL_PRESETS), len({preset.preset_id for preset in LABEL_PRESETS}))
        self.assertEqual(len(LABEL_PRESETS), len({preset.display_name for preset in LABEL_PRESETS}))
        for preset in LABEL_PRESETS:
            self.assertTrue(preset.text)
            self.assertTrue(preset.category)
            if preset.icon_id:
                self.assertIn(preset.icon_id, ICON_BY_ID)

    def test_input_and_output_arrows_point_in_opposite_directions(self):
        input_icon = ICON_BY_ID["builtin.input"]
        output_icon = ICON_BY_ID["builtin.output"]
        self.assertIn(Point(-0.39, 0.0), input_icon.polygons[1])
        self.assertIn(Point(0.50, 0.0), output_icon.polygons[1])

    def test_revised_polarity_catalog_and_removed_airflow(self):
        self.assertIn("builtin.centre_positive", ICON_BY_ID)
        self.assertIn("builtin.centre_negative", ICON_BY_ID)
        self.assertIn("builtin.positive", ICON_BY_ID)
        self.assertIn("builtin.negative", ICON_BY_ID)
        self.assertNotIn("builtin.airflow", ICON_BY_ID)
        positive = render_builtin_icon("builtin.positive", 1.2)
        negative = render_builtin_icon("builtin.negative", 1.2)
        self.assertAlmostEqual(positive.size.width, positive.size.height)
        self.assertAlmostEqual(negative.size.width, negative.size.height)


if __name__ == "__main__":
    unittest.main()

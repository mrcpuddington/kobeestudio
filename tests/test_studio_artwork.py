"""Checks for preview-identical Silk Studio vector artwork."""

from __future__ import annotations

import re
import unittest

from kibeezard.core.composition import (
    DocumentStyle,
    IconObject,
    Padding,
    ShapeStyle,
    TextObject,
    TypographyStyle,
)
from kibeezard.core.pin_header import PinHeaderSpec
from kibeezard.core.icon_catalog import BUILTIN_ICONS
from kibeezard.core.studio_artwork import (
    TextVectorizer,
    render_header_artwork,
    render_label_artwork,
    serialize_artwork,
)
from kibeezard.core.text_geometry import TextGeometry


class StudioArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectorizer = TextVectorizer(TextGeometry().buzzard)

    def style(self, filled=False, inverted=False):
        return DocumentStyle(
            typography=TypographyStyle(height_mm=1.0),
            shape=ShapeStyle(
                padding=Padding.symmetric(0.4, 0.3),
                border_thickness_mm=0.2 if not filled else 0.0,
                corner_radius_mm=0.5,
                feature_size_mm=0.6,
                filled=filled,
                inverted=inverted,
            ),
        )

    def test_plain_text_and_every_shape_render(self):
        plain = render_label_artwork(self.vectorizer, "GND", self.style(), "F.SilkS")
        self.assertGreater(len(plain.filled_polygons), 0)
        self.assertEqual((), plain.strokes)

        for shape in (
            "rectangle",
            "rounded_rectangle",
            "pill",
            "custom_ends",
            "custom_long_edges",
            "pointer",
            "flag",
            "tab",
            "chamfer",
            "hexagon",
        ):
            with self.subTest(shape=shape):
                artwork = render_label_artwork(self.vectorizer, "GND", self.style(), "F.SilkS", shape)
                self.assertGreater(len(artwork.filled_polygons), 0)
                self.assertEqual(1, len(artwork.strokes))

    def test_requested_cap_height_and_padding_are_physical_millimetres(self):
        style = DocumentStyle(
            typography=TypographyStyle(font_name="FreddySpark-Regular", height_mm=2.0),
            shape=ShapeStyle(
                padding=Padding(top=0.3, right=0.4, bottom=0.3, left=0.4),
                border_thickness_mm=0.2,
                corner_radius_mm=0.5,
                filled=False,
            ),
        )
        vectors = self.vectorizer.render("H", style.typography)
        self.assertAlmostEqual(2.0, vectors.size.height, places=6)
        artwork = render_label_artwork(self.vectorizer, "H", style, "F.SilkS", "rounded_rectangle")
        self.assertAlmostEqual(vectors.size.width + 0.8, artwork.document.size.width, places=6)
        self.assertAlmostEqual(2.6, artwork.document.size.height, places=6)

    def test_icon_and_text_layout_supports_left_right_and_icon_only(self):
        left = render_label_artwork(
            self.vectorizer,
            "GND",
            self.style(),
            "F.SilkS",
            "rounded_rectangle",
            icon_id="builtin.ground",
            icon_position="left",
            icon_height_mm=0.8,
            icon_gap_mm=0.25,
        )
        right = render_label_artwork(
            self.vectorizer,
            "GND",
            self.style(),
            "F.SilkS",
            "rounded_rectangle",
            icon_id="builtin.ground",
            icon_position="right",
            icon_height_mm=0.8,
            icon_gap_mm=0.25,
        )
        left_text = next(item for item in left.document.objects if isinstance(item, TextObject))
        left_icon = next(item for item in left.document.objects if isinstance(item, IconObject))
        right_text = next(item for item in right.document.objects if isinstance(item, TextObject))
        right_icon = next(item for item in right.document.objects if isinstance(item, IconObject))
        self.assertLess(left_icon.position.x, left_text.position.x)
        self.assertGreater(right_icon.position.x, right_text.position.x)
        self.assertAlmostEqual(left.document.size.width, right.document.size.width)

        icon_only = render_label_artwork(
            self.vectorizer,
            "ignored",
            self.style(),
            "F.SilkS",
            "pill",
            icon_id="builtin.test_point",
            icon_position="only",
            icon_height_mm=1.2,
        )
        self.assertFalse(any(isinstance(item, TextObject) for item in icon_only.document.objects))
        self.assertEqual(1, len([item for item in icon_only.document.objects if isinstance(item, IconObject)]))

        bare_icon = render_label_artwork(
            self.vectorizer,
            "",
            self.style(),
            "F.SilkS",
            icon_id="builtin.lightning",
            icon_position="only",
            icon_height_mm=1.5,
        )
        self.assertFalse(any(item.kind == "shape" for item in bare_icon.document.objects))
        self.assertEqual((), bare_icon.strokes)
        self.assertGreater(len(bare_icon.filled_polygons), 0)

    def test_icons_render_as_positive_and_inverted_fabrication_geometry(self):
        plain = render_label_artwork(
            self.vectorizer,
            "POWER",
            self.style(),
            "F.SilkS",
            icon_id="builtin.lightning",
        )
        inverted = render_label_artwork(
            self.vectorizer,
            "POWER",
            self.style(filled=True, inverted=True),
            "F.SilkS",
            "pill",
            icon_id="builtin.lightning",
        )
        self.assertGreater(len(plain.filled_polygons), 1)
        self.assertGreaterEqual(len(inverted.filled_polygons), 1)
        self.assertEqual((), inverted.strokes)
        self.assertTrue(any(isinstance(item, IconObject) for item in inverted.document.objects))

        for icon in BUILTIN_ICONS:
            with self.subTest(icon=icon.asset_id):
                artwork = render_label_artwork(
                    self.vectorizer,
                    "ICON",
                    self.style(filled=True, inverted=True),
                    "F.SilkS",
                    "pill",
                    icon_id=icon.asset_id,
                    icon_height_mm=1.0,
                )
                self.assertGreater(len(artwork.filled_polygons), 0)
                self.assertEqual((), artwork.strokes)

    def test_inverted_fill_combines_shape_and_text_as_knockouts(self):
        artwork = render_label_artwork(
            self.vectorizer,
            "GND",
            self.style(filled=True, inverted=True),
            "F.SilkS",
            "pill",
        )
        self.assertGreaterEqual(len(artwork.filled_polygons), 1)
        self.assertEqual((), artwork.strokes)
        self.assertGreater(sum(len(polygon) for polygon in artwork.filled_polygons), 100)

    def test_header_artwork_has_guides_but_does_not_export_them(self):
        spec = PinHeaderSpec(
            pin_count=4,
            pin_labels=("VCC", "GND", "SDA", "SCL"),
            pad_clearance_mm=6.0,
            shape="rounded_rectangle",
            style=self.style(),
        )
        artwork = render_header_artwork(self.vectorizer, spec)
        self.assertEqual(4, len(artwork.guides))
        output = serialize_artwork(artwork, "encoded", "F.SilkS")
        self.assertEqual(len(artwork.filled_polygons) + len(artwork.strokes), output.count("(fp_poly"))
        self.assertNotIn("pad-guide", output)

    def test_horizontal_header_rotates_every_label_with_the_pin_layout(self):
        spec = PinHeaderSpec(
            pin_count=3,
            pin_labels=("VCC", "GND", "SIGNAL"),
            orientation="horizontal",
            label_side="below",
            shape="rounded_rectangle",
            style=self.style(filled=True, inverted=True),
        )
        artwork = render_header_artwork(self.vectorizer, spec)
        labels = [item for item in artwork.document.objects if item.kind == "text"]
        self.assertEqual([90.0, 90.0, 90.0], [item.rotation_deg for item in labels])
        # Inverted blocks contain text and connector clearances in the same
        # knockout polygon while preview retains the plug envelope and one
        # alignment guide per pin.
        self.assertGreaterEqual(len(artwork.filled_polygons), 1)
        self.assertEqual(3, len(artwork.guides))

    def test_header_opening_can_be_none_continuous_or_individual(self):
        artworks = {}
        for opening_mode in ("none", "continuous", "individual"):
            spec = PinHeaderSpec(
                pin_count=3,
                pin_labels=("VCC", "GND", "SDA"),
                orientation="vertical",
                label_side="right",
                opening_mode=opening_mode,
                shape="custom_ends",
                style=self.style(filled=True, inverted=True),
            )
            artworks[opening_mode] = render_header_artwork(self.vectorizer, spec)
        signatures = {
            mode: tuple(tuple((round(point.x, 5), round(point.y, 5)) for point in polygon) for polygon in artwork.filled_polygons)
            for mode, artwork in artworks.items()
        }
        self.assertNotEqual(signatures["none"], signatures["continuous"])
        self.assertNotEqual(signatures["continuous"], signatures["individual"])

    def test_bottom_serialization_is_one_x_mirror(self):
        artwork = render_label_artwork(self.vectorizer, "R2D7", self.style(), "F.SilkS", "pointer")
        front = serialize_artwork(artwork, "encoded", "F.SilkS")
        bottom = serialize_artwork(artwork, "encoded", "B.SilkS")
        pattern = re.compile(r"\(xy (-?[0-9.]+) (-?[0-9.]+)\)")
        front_points = sorted((round(float(x), 6), round(float(y), 6)) for x, y in pattern.findall(front))
        bottom_points = sorted((round(float(x), 6), round(float(y), 6)) for x, y in pattern.findall(bottom))
        expected = sorted((round(-x, 6), y) for x, y in front_points)
        self.assertEqual(expected, bottom_points)
        self.assertIn('(layer "B.Cu")', bottom)
        self.assertIn('(layer "B.SilkS")', bottom)


if __name__ == "__main__":
    unittest.main()

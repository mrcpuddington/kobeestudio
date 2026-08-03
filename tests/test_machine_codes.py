"""Checks for fabrication-aware QR and Code 128 generators."""

from __future__ import annotations

import unittest

from kobeestudio.core.composition import Point, TextObject
from kobeestudio.core.machine_codes import (
    CODE128_DEFAULT_HEIGHT_MM,
    CODE128_DEFAULT_MODULE_MM,
    CODE128_MIN_HEIGHT_MM,
    CODE128_MIN_MODULE_MM,
    QR_MIN_MODULE_MM,
    render_code128,
    render_qr_code,
)
from kobeestudio.core.shape_geometry import polygon_bounds
from kobeestudio.core.studio_artwork import (
    TextVectorizer,
    _point_in_polygon,
    render_machine_code_artwork,
    serialize_artwork,
)
from kobeestudio.core.text_geometry import TextGeometry


class MachineCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectorizer = TextVectorizer(TextGeometry().buzzard)

    def test_qr_code_uses_standard_matrix_and_four_module_quiet_zone(self):
        code = render_qr_code("HELLO", QR_MIN_MODULE_MM)
        self.assertEqual("qr", code.kind)
        self.assertEqual(21, code.module_columns)
        self.assertEqual(21, code.module_rows)
        self.assertEqual(4, code.quiet_zone_modules)
        self.assertAlmostEqual((21 + 8) * QR_MIN_MODULE_MM, code.size.width)
        self.assertEqual(code.size.width, code.size.height)
        self.assertGreater(len(code.polygons), 0)

    def test_code128_uses_compact_defaults_and_ten_module_quiet_zones(self):
        code = render_code128("KOBEE-123")
        self.assertEqual("code128", code.kind)
        self.assertEqual(134, code.module_columns)
        self.assertEqual(10, code.quiet_zone_modules)
        self.assertAlmostEqual(
            (134 + 20) * CODE128_DEFAULT_MODULE_MM, code.size.width
        )
        self.assertAlmostEqual(CODE128_DEFAULT_HEIGHT_MM, code.size.height)
        self.assertGreater(len(code.polygons), 0)

    def test_payload_and_fabrication_limits_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "Enter a payload"):
            render_qr_code("")
        with self.assertRaisesRegex(ValueError, "at least 0.35 mm"):
            render_qr_code("HELLO", 0.2)
        with self.assertRaisesRegex(ValueError, "single line"):
            render_code128("ONE\nTWO")
        with self.assertRaisesRegex(ValueError, "printable ASCII"):
            render_code128("KOBEE 🐝")
        with self.assertRaisesRegex(ValueError, "at least 0.20 mm"):
            render_code128("KOBEE", CODE128_MIN_MODULE_MM - 0.01)
        with self.assertRaisesRegex(ValueError, "at least 3.0 mm"):
            render_code128("KOBEE", bar_height_mm=CODE128_MIN_HEIGHT_MM - 0.1)

    def test_machine_code_quiet_zone_is_preview_only(self):
        artwork = render_machine_code_artwork(
            "https://kobee.com.au",
            "qr",
            QR_MIN_MODULE_MM,
            CODE128_DEFAULT_HEIGHT_MM,
            "F.SilkS",
        )
        self.assertEqual(1, len(artwork.guides))
        footprint = serialize_artwork(artwork, "encoded", "F.SilkS")
        self.assertNotIn("guide", footprint)
        self.assertIn("fp_poly", footprint)

    def test_qr_can_show_editable_human_readable_text(self):
        artwork = render_machine_code_artwork(
            "https://www.coreybusuttil.com/kobeestudio/docs/",
            "qr",
            QR_MIN_MODULE_MM,
            CODE128_DEFAULT_HEIGHT_MM,
            "F.SilkS",
            vectorizer=self.vectorizer,
            show_content_text=True,
            content_text="Kobee Studio docs",
            content_height_mm=0.9,
            content_gap_mm=0.5,
        )
        content = next(
            item for item in artwork.document.objects
            if isinstance(item, TextObject) and item.object_id == "code.content-text"
        )
        self.assertEqual("Kobee Studio docs", content.text)
        self.assertGreater(content.position.y, artwork.guides[0][2].y)

    def test_code128_content_text_is_independent_from_encoded_payload(self):
        artwork = render_machine_code_artwork(
            "ASSET-00042",
            "code128",
            CODE128_DEFAULT_MODULE_MM,
            CODE128_DEFAULT_HEIGHT_MM,
            "F.SilkS",
            vectorizer=self.vectorizer,
            show_content_text=True,
            content_text="Board 42",
        )
        content = next(
            item for item in artwork.document.objects
            if isinstance(item, TextObject) and item.object_id == "code.content-text"
        )
        self.assertEqual("Board 42", content.text)
        self.assertGreater(artwork.document.size.height, CODE128_DEFAULT_HEIGHT_MM)

    def test_machine_code_content_text_validation(self):
        with self.assertRaisesRegex(ValueError, "single line"):
            render_machine_code_artwork(
                "HELLO",
                "qr",
                QR_MIN_MODULE_MM,
                CODE128_DEFAULT_HEIGHT_MM,
                "F.SilkS",
                vectorizer=self.vectorizer,
                show_content_text=True,
                content_text="ONE\nTWO",
            )

    def test_rounded_qr_frame_stays_outside_quiet_zone(self):
        code = render_qr_code("https://kobee.com.au", QR_MIN_MODULE_MM)
        compact = render_machine_code_artwork(
            code.payload,
            "qr",
            QR_MIN_MODULE_MM,
            CODE128_DEFAULT_HEIGHT_MM,
            "F.SilkS",
            presentation="rounded_frame",
            frame_padding_mm=0.0,
        )
        roomy = render_machine_code_artwork(
            code.payload,
            "qr",
            QR_MIN_MODULE_MM,
            CODE128_DEFAULT_HEIGHT_MM,
            "F.SilkS",
            presentation="rounded_frame",
            frame_padding_mm=1.0,
        )
        artwork = compact
        self.assertGreater(artwork.document.size.width, code.size.width)
        self.assertGreater(artwork.document.size.height, code.size.height)
        self.assertAlmostEqual(2.0, roomy.document.size.width - compact.document.size.width)
        self.assertAlmostEqual(2.0, roomy.document.size.height - compact.document.size.height)
        decorations = artwork.filled_polygons[len(code.polygons):]
        half_width = code.size.width / 2.0
        half_height = code.size.height / 2.0
        self.assertFalse(
            any(
                abs(point.x) < half_width and abs(point.y) < half_height
                for polygon in decorations
                for point in polygon
            )
        )

    def test_qr_footer_is_filled_with_knockout_text(self):
        code = render_qr_code("https://kobee.com.au", QR_MIN_MODULE_MM)
        artwork = render_machine_code_artwork(
            code.payload,
            "qr",
            QR_MIN_MODULE_MM,
            CODE128_DEFAULT_HEIGHT_MM,
            "F.SilkS",
            vectorizer=self.vectorizer,
            presentation="rounded_caption",
            caption_text="SCAN ME",
            caption_height_mm=1.2,
        )
        caption = next(
            item for item in artwork.document.objects if isinstance(item, TextObject)
        )
        vectors = self.vectorizer.render(
            caption.text, artwork.document.style.typography
        )
        text_polygons = tuple(
            tuple(
                Point(point.x + caption.position.x, point.y + caption.position.y)
                for point in polygon
            )
            for polygon in vectors.polygons
        )
        minimum, maximum = polygon_bounds(text_polygons)
        decorations = artwork.filled_polygons[len(code.polygons):]
        found_knockout = False
        for row in range(1, 30):
            y = minimum.y + (maximum.y - minimum.y) * row / 30.0
            for column in range(1, 80):
                x = minimum.x + (maximum.x - minimum.x) * column / 80.0
                point = Point(x, y)
                inside_text = sum(
                    1 for polygon in text_polygons if _point_in_polygon(point, polygon)
                ) % 2
                if inside_text and not any(
                    _point_in_polygon(point, polygon) for polygon in decorations
                ):
                    found_knockout = True
                    break
            if found_knockout:
                break
        self.assertTrue(found_knockout)

    def test_qr_footer_validates_caption_input(self):
        with self.assertRaisesRegex(ValueError, "Enter footer text"):
            render_machine_code_artwork(
                "HELLO",
                "qr",
                QR_MIN_MODULE_MM,
                CODE128_DEFAULT_HEIGHT_MM,
                "F.SilkS",
                vectorizer=self.vectorizer,
                presentation="rounded_caption",
                caption_text="   ",
            )


if __name__ == "__main__":
    unittest.main()

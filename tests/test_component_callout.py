"""Regression checks for multi-text labels and component-centred callouts."""

from __future__ import annotations

import unittest

from kobeestudio.core.component_callout import (
    COMPONENT_PRESETS,
    COMPONENT_PRESET_BY_ID,
    ComponentCalloutSpec,
)
from kobeestudio.core.composition import (
    CompositionDocument,
    DocumentStyle,
    Padding,
    Point,
    ShapeStyle,
    TypographyStyle,
)
from kobeestudio.core.shape_geometry import polygon_bounds
from kobeestudio.core.studio_artwork import (
    TextVectorizer,
    _point_in_polygon,
    render_component_callout_artwork,
    render_label_artwork,
    serialize_artwork,
)
from kobeestudio.core.text_geometry import TextGeometry

try:
    import pcbnew
    from kobeestudio.integration.kicad_compatibility import KiCadCompatibility
except ImportError:  # pragma: no cover - normal Python can still discover the suite
    pcbnew = None


class ComponentCalloutTests(unittest.TestCase):
    def setUp(self):
        self.vectorizer = TextVectorizer(TextGeometry().buzzard)

    @staticmethod
    def style(alignment="center"):
        return DocumentStyle(
            typography=TypographyStyle(height_mm=1.2, alignment=alignment),
            secondary_typography=TypographyStyle(height_mm=0.7, alignment=alignment),
            shape=ShapeStyle(
                padding=Padding.symmetric(0.7, 0.5),
                corner_radius_mm=0.2,
                filled=True,
                inverted=True,
            ),
        )

    def spec(self, **changes):
        values = {
            "title": "POWER",
            "subtitle": "LED",
            "component_width_mm": 2.6,
            "component_height_mm": 1.8,
            "component_clearance_mm": 0.3,
            "style": self.style(),
        }
        values.update(changes)
        return ComponentCalloutSpec(**values)

    def test_package_presets_cover_initial_chip_and_component_families(self):
        preset_ids = {item.preset_id for item in COMPONENT_PRESETS}
        self.assertTrue({"0402", "0603", "0805", "1206", "1210"}.issubset(preset_ids))
        self.assertTrue({"sot23", "soic8", "qfn32_5", "tactile_6"}.issubset(preset_ids))
        self.assertTrue(all(item.width_mm > 0 and item.height_mm > 0 for item in COMPONENT_PRESETS))

    def test_title_and_subtitle_keep_independent_typography(self):
        artwork = render_label_artwork(
            self.vectorizer,
            "POWER",
            self.style(),
            "F.SilkS",
            "rounded_rectangle",
            subtitle_text="LED",
            subtitle_typography=TypographyStyle(height_mm=0.55),
            subtitle_gap_mm=0.35,
        )
        texts = [item for item in artwork.document.objects if item.kind == "text"]
        self.assertEqual(["primary", "secondary"], [item.style_role for item in texts])
        self.assertLess(texts[0].position.y, texts[1].position.y)
        self.assertEqual(0.55, artwork.document.style.secondary_typography.height_mm)
        self.assertEqual(artwork.document, CompositionDocument.from_json(artwork.document.to_json()))

    def test_callout_origin_and_guide_are_component_centred(self):
        for position in ("left", "right", "above", "below"):
            with self.subTest(position=position):
                artwork = render_component_callout_artwork(
                    self.vectorizer,
                    self.spec(component_position=position),
                )
                guide = next(
                    item for item in artwork.document.objects if item.object_id == "component.safe-zone"
                )
                self.assertEqual(Point(), artwork.document.anchor)
                self.assertEqual(Point(), guide.position)
                self.assertEqual(1, len(artwork.guides))
                self.assertFalse(any(_point_in_polygon(Point(), polygon) for polygon in artwork.filled_polygons))

    def test_custom_safe_zone_clearance_and_minimum_container_size(self):
        spec = self.spec(
            preset_id="custom",
            component_width_mm=5.0,
            component_height_mm=3.0,
            component_clearance_mm=0.75,
            cutout_shape="pill",
            minimum_width_mm=18.0,
            minimum_height_mm=8.0,
        )
        artwork = render_component_callout_artwork(self.vectorizer, spec)
        guide_min, guide_max = polygon_bounds(artwork.guides)
        self.assertAlmostEqual(6.5, guide_max.x - guide_min.x, places=6)
        self.assertAlmostEqual(4.5, guide_max.y - guide_min.y, places=6)
        self.assertGreaterEqual(artwork.document.size.width, 18.0)
        self.assertGreaterEqual(artwork.document.size.height, 8.0)


    def test_reviewed_presets_use_practical_land_pattern_envelopes(self):
        self.assertEqual(1.9, COMPONENT_PRESET_BY_ID["1206"].height_mm)
        self.assertEqual((1.6, 0.8), (
            COMPONENT_PRESET_BY_ID["0402"].width_mm,
            COMPONENT_PRESET_BY_ID["0402"].height_mm,
        ))
        tactile = COMPONENT_PRESET_BY_ID["tactile_6"]
        self.assertEqual((8.0, 7.0), (tactile.width_mm, tactile.height_mm))
        self.assertEqual("rounded_rectangle", tactile.cutout_shape)

    def test_tactile_switch_guide_is_one_simple_enclosing_shape(self):
        preset = COMPONENT_PRESET_BY_ID["tactile_6"]
        artwork = render_component_callout_artwork(
            self.vectorizer,
            self.spec(
                title="BUTTON",
                subtitle="",
                preset_id=preset.preset_id,
                component_width_mm=preset.width_mm,
                component_height_mm=preset.height_mm,
                cutout_shape=preset.cutout_shape,
                cutout_radius_mm=preset.cutout_radius_mm,
            ),
        )
        guide_min, guide_max = polygon_bounds(artwork.guides)
        self.assertAlmostEqual(8.6, guide_max.x - guide_min.x, places=6)
        self.assertAlmostEqual(7.6, guide_max.y - guide_min.y, places=6)
        # The rounded rectangle encloses the switch body and side legs without
        # the four stepped pin wings used by the old preset.
        contour = artwork.guides[0]
        self.assertTrue(all(guide_min.x <= point.x <= guide_max.x for point in contour))
        self.assertTrue(all(guide_min.y <= point.y <= guide_max.y for point in contour))

    def test_component_array_has_one_cutout_and_label_per_component(self):
        artwork = render_component_callout_artwork(
            self.vectorizer,
            self.spec(
                title="LED 1\nLED 2\nLED 3",
                subtitle="",
                component_width_mm=2.2,
                component_height_mm=1.1,
                array_count=3,
                array_orientation="vertical",
                array_pitch_mm=5.0,
            ),
        )
        guides = [item for item in artwork.document.objects if item.kind == "guide"]
        labels = [item for item in artwork.document.objects if item.kind == "text"]
        self.assertEqual(3, len(artwork.guides))
        self.assertEqual(3, len(guides))
        self.assertEqual(3, len(labels))
        self.assertEqual([-5.0, 0.0, 5.0], [item.position.y for item in guides])
        self.assertTrue(any(item.object_id == "group.component-array" for item in artwork.document.objects))
        restored = ComponentCalloutSpec.from_dict(
            artwork.component_callout.to_dict(), style=artwork.component_callout.style
        )
        self.assertEqual(artwork.component_callout, restored)

    def test_component_array_rejects_overlapping_pitch(self):
        with self.assertRaisesRegex(ValueError, "spacing must be at least"):
            render_component_callout_artwork(
                self.vectorizer,
                self.spec(
                    title="A\nB\nC",
                    subtitle="",
                    array_count=3,
                    array_orientation="vertical",
                    array_pitch_mm=0.5,
                ),
            )

    def test_horizontal_component_array_uses_configured_centres(self):
        artwork = render_component_callout_artwork(
            self.vectorizer,
            self.spec(
                title="A\nB\nC",
                subtitle="",
                array_count=3,
                array_orientation="horizontal",
                array_pitch_mm=8.0,
            ),
        )
        guides = [item for item in artwork.document.objects if item.kind == "guide"]
        for actual, expected in zip(
            (item.position.x for item in guides), (-8.0, 0.0, 8.0)
        ):
            self.assertAlmostEqual(expected, actual, places=9)
        self.assertTrue(all(abs(item.position.y) < 1e-9 for item in guides))

    def test_component_array_count_is_bounded_for_interactive_performance(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 16"):
            self.spec(
                title="\n".join(str(index) for index in range(17)),
                subtitle="",
                array_count=17,
            )

    def test_feature_round_trip_and_guides_do_not_export(self):
        spec = self.spec(component_position="right", cutout_shape="rectangle")
        restored = ComponentCalloutSpec.from_dict(spec.to_dict(), style=spec.style)
        self.assertEqual(spec, restored)
        artwork = render_component_callout_artwork(self.vectorizer, spec)
        output = serialize_artwork(artwork, "encoded", "F.SilkS")
        self.assertNotIn("component.safe-zone", output)
        self.assertEqual(
            len(artwork.filled_polygons) + len(artwork.strokes),
            output.count("(fp_poly"),
        )


    @unittest.skipIf(pcbnew is None, "requires KiCad embedded Python")
    def test_callouts_parse_on_every_supported_layer(self):
        compatibility = KiCadCompatibility()
        for layer in ("F.SilkS", "B.SilkS", "F.Cu", "B.Cu", "F.Mask", "B.Mask"):
            with self.subTest(layer=layer):
                spec = self.spec(output_layer=layer)
                artwork = render_component_callout_artwork(self.vectorizer, spec)
                footprint = compatibility.parse_footprint(
                    serialize_artwork(artwork, "encoded", layer)
                )
                expected_owner = "B.Cu" if layer.startswith("B.") else "F.Cu"
                self.assertEqual(expected_owner, footprint.GetLayerName())
                self.assertTrue(footprint.GraphicalItems())


if __name__ == "__main__":
    unittest.main()

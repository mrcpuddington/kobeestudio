import unittest

from kobeestudio.core.text_formatting import formatted_runs
from kobeestudio.core.composition import DocumentStyle, ShapeObject, Point
from kobeestudio.core.shape_geometry import polygon_bounds
from kobeestudio.core.studio_artwork import (
    PLACEMENT_ANCHORS, TextVectorizer, render_label_artwork, with_placement_anchor,
)
from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.integration.ipc_artwork import IpcArtworkPlacement, artwork_polygons


class TextFormattingTests(unittest.TestCase):
    def test_bus_notation_uses_smaller_lowered_runs(self):
        runs = formatted_runs("D_{0} - D_{7}")
        self.assertEqual("D0 - D7", "".join(run.text for run in runs))
        for run in (runs[1], runs[-1]):
            self.assertLess(run.scale, 1)
            self.assertGreater(run.baseline, 0)

    def test_scripts_can_be_nested_inside_overlined_groups(self):
        runs = formatted_runs("~{V^{2}} !{RESET}")
        self.assertTrue(runs[1].overline)
        self.assertLess(runs[1].baseline, 0)
        self.assertTrue(runs[-1].underline)

    def test_plain_and_escaped_notation_remains_literal(self):
        text = r"D_0 {PCB} \_{0}"
        self.assertEqual("D_0 {PCB} _{0}", "".join(run.text for run in formatted_runs(text)))

    def test_incomplete_and_excessively_nested_markup_is_actionable(self):
        with self.assertRaisesRegex(ValueError, "Close each"):
            formatted_runs("D_{0")
        with self.assertRaisesRegex(ValueError, "eight"):
            formatted_runs("^{" * 10 + "x" + "}" * 10)


class FormattedArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectorizer = TextVectorizer(TextGeometry().buzzard)

    def test_script_overline_and_underline_notation_exports_real_polygons(self):
        for text in ("D_{0} - D_{7}", "V^{2}", "~{RESET}", "!{ENABLE}", "~{V^{2}}"):
            with self.subTest(text=text):
                artwork = render_label_artwork(self.vectorizer, text, DocumentStyle(), "F.SilkS", inline_format=True)
                self.assertTrue(artwork.filled_polygons)

    def test_blank_or_empty_formatted_labels_cannot_be_placed(self):
        for text in ("   ", "^{}"):
            with self.assertRaisesRegex(ValueError, "label needs"):
                render_label_artwork(self.vectorizer, text, DocumentStyle(), "F.SilkS", inline_format=True)

    def test_both_lines_reserve_their_requested_physical_gaps(self):
        artwork = render_label_artwork(
            self.vectorizer, "RESET", DocumentStyle(), "F.SilkS",
            underline=True, underline_gap_mm=0.4, underline_thickness_mm=0.2,
            overline=True, overline_gap_mm=0.3, overline_thickness_mm=0.1,
        )
        shapes = {obj.object_id: obj for obj in artwork.document.objects if isinstance(obj, ShapeObject)}
        under = shapes["text.underline"]
        over = shapes["text.overline"]
        self.assertAlmostEqual(0.2, under.size.height)
        self.assertAlmostEqual(0.1, over.size.height)
        minimum, maximum = polygon_bounds(artwork.filled_polygons[:-2])
        self.assertAlmostEqual(0.4, under.position.y - under.size.height / 2 - maximum.y)
        self.assertAlmostEqual(0.3, minimum.y - over.position.y - over.size.height / 2)

    def test_all_nine_anchors_land_at_the_footprint_origin_on_both_sides(self):
        original = render_label_artwork(self.vectorizer, "ANCHOR", DocumentStyle(), "F.SilkS", shape="rectangle")
        for index, name in enumerate(PLACEMENT_ANCHORS):
            anchored = with_placement_anchor(original, name)
            self.assertEqual(original.filled_polygons, anchored.filled_polygons)
            for layer in ("F.SilkS", "B.SilkS"):
                primitives = artwork_polygons(anchored, layer, IpcArtworkPlacement._artwork_offset(anchored, layer))
                minimum, maximum = polygon_bounds(tuple(item.points for item in primitives))
                row, column = divmod(index, 3)
                if layer.startswith("B."):
                    column = 2 - column
                self.assertAlmostEqual(0, (minimum.x, (minimum.x + maximum.x) / 2, maximum.x)[column])
                self.assertAlmostEqual(0, (minimum.y, (minimum.y + maximum.y) / 2, maximum.y)[row])

    def test_changing_text_preserves_the_chosen_corner(self):
        for text in ("A", "LONGER LABEL"):
            artwork = with_placement_anchor(render_label_artwork(self.vectorizer, text, DocumentStyle(), "F.SilkS"), "Bottom left")
            minimum, maximum = polygon_bounds(artwork.all_exported_polygons)
            self.assertEqual(Point(minimum.x, maximum.y), artwork.document.origin)

    def test_symbol_variant_survives_container_layout(self):
        artwork = render_label_artwork(
            self.vectorizer, "GND", DocumentStyle(), "F.SilkS", shape="rectangle",
            icon_id="builtin.ground", icon_variant="rounded",
        )
        icon = next(item for item in artwork.document.objects if item.kind == "icon")
        self.assertEqual("rounded", icon.variant)

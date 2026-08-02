"""Milestone 4 checks for the single-row 2.54 mm header generator."""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from kobeestudio.core.composition import DocumentStyle, Padding, ShapeStyle, Size, TypographyStyle
from kobeestudio.core.pin_header import (
    PinHeaderSpec,
    layout_pin_header,
    maximum_pin_label_height,
    mirror_layout_for_output,
)
from kobeestudio.core.shape_geometry import render_document_shapes


def header_style():
    return DocumentStyle(
        typography=TypographyStyle(height_mm=1.0),
        shape=ShapeStyle(
            padding=Padding.symmetric(0.3, 0.3),
            border_thickness_mm=0.2,
            corner_radius_mm=0.5,
            filled=False,
        ),
    )


class PinHeaderTests(unittest.TestCase):
    def make_spec(self, pin_count=4, **overrides):
        values = {
            "pin_count": pin_count,
            "pin_labels": tuple("P{}".format(index + 1) for index in range(pin_count)),
            "style": header_style(),
        }
        values.update(overrides)
        return PinHeaderSpec(**values)

    def test_pin_centres_are_exactly_2_54_mm_apart(self):
        layout = layout_pin_header(self.make_spec(8), (Size(1.0, 1.0),) * 8)
        for first, second in zip(layout.pin_centres, layout.pin_centres[1:]):
            self.assertAlmostEqual(2.54, second.x - first.x)
            self.assertEqual(0.0, second.y)
        self.assertEqual(layout.pin_centres[0], layout.anchor)

    def test_expected_bounds_for_common_pin_counts(self):
        for pin_count in (1, 2, 3, 8, 10, 20):
            with self.subTest(pin_count=pin_count):
                spec = self.make_spec(pin_count)
                layout = layout_pin_header(spec, (Size(1.0, 1.0),) * pin_count)
                # The enclosure includes the 2 mm connector envelope plus
                # 0.3 mm of adjustable outer padding at each row end.
                self.assertAlmostEqual(pin_count * 2.54 + 0.06, layout.size.width)
                self.assertAlmostEqual(3.9, layout.size.height)

    def test_default_row_end_padding_is_compact_and_adjustable(self):
        compact = layout_pin_header(self.make_spec(2), (Size(1.0, 1.0),) * 2)
        roomy = layout_pin_header(
            self.make_spec(2, leading_padding_mm=2.0, trailing_padding_mm=3.0),
            (Size(1.0, 1.0),) * 2,
        )
        self.assertAlmostEqual(0.3, compact.spec.leading_padding_mm)
        self.assertAlmostEqual(0.3, compact.spec.trailing_padding_mm)
        self.assertAlmostEqual(4.4, roomy.size.width - compact.size.width)

    def test_text_height_cannot_overlap_adjacent_2_54_mm_labels(self):
        limit = maximum_pin_label_height(2.54)
        self.assertAlmostEqual(2.34, limit)
        tall_style = replace(
            header_style(),
            typography=replace(header_style().typography, height_mm=limit + 0.01),
        )
        with self.assertRaisesRegex(ValueError, "too large.*maximum is 2.34"):
            self.make_spec(2, style=tall_style)
        with self.assertRaisesRegex(ValueError, "Rendered text height.*maximum is 2.34"):
            layout_pin_header(self.make_spec(2), (Size(1.0, limit + 0.01),) * 2)

    def test_pin_labels_must_match_pin_count(self):
        with self.assertRaisesRegex(ValueError, "label count"):
            PinHeaderSpec(pin_count=3, pin_labels=("VCC", "GND"))
        with self.assertRaisesRegex(ValueError, "label size count"):
            layout_pin_header(self.make_spec(3), (Size(1.0, 1.0),))

    def test_connector_clearance_is_adjustable_inside_the_enclosure(self):
        ordinary = layout_pin_header(self.make_spec(2, pad_clearance_mm=2.0), (Size(1.0, 1.0),) * 2)
        large_plug = layout_pin_header(self.make_spec(2, pad_clearance_mm=8.0), (Size(1.0, 1.0),) * 2)
        self.assertAlmostEqual(3.9, ordinary.size.height)
        self.assertAlmostEqual(9.9, large_plug.size.height)
        self.assertGreater(large_plug.bounds_max.y, ordinary.bounds_max.y)
        self.assertLess(large_plug.bounds_min.y, ordinary.bounds_min.y)

    def test_opening_is_optional_and_continuous_end_padding_expands_the_enclosure(self):
        no_opening = layout_pin_header(
            self.make_spec(4, opening_mode="none"),
            (Size(1.0, 1.0),) * 4,
        )
        extended = layout_pin_header(
            self.make_spec(
                4,
                opening_mode="continuous",
                opening_end_padding_mm=3.0,
            ),
            (Size(1.0, 1.0),) * 4,
        )
        self.assertGreater(extended.size.width, no_opening.size.width)
        self.assertAlmostEqual(3.0, extended.spec.opening_end_padding_mm)

    def test_individual_openings_cannot_overlap_at_a_2_54_mm_pitch(self):
        with self.assertRaisesRegex(ValueError, "use a continuous opening"):
            self.make_spec(4, opening_mode="individual", pad_clearance_mm=3.0)

    def test_copper_header_requires_an_explicit_opening(self):
        with self.assertRaisesRegex(ValueError, "avoid shorting pins"):
            self.make_spec(4, output_layer="F.Cu", opening_mode="none")

    def test_every_connector_clearance_is_encompassed_by_the_outer_shape(self):
        for orientation, side in (
            ("horizontal", "above"),
            ("horizontal", "below"),
            ("vertical", "left"),
            ("vertical", "right"),
        ):
            with self.subTest(orientation=orientation, side=side):
                spec = self.make_spec(
                    8,
                    orientation=orientation,
                    label_side=side,
                    pad_clearance_mm=7.5,
                )
                layout = layout_pin_header(spec, (Size(1.0, 1.0),) * 8)
                for guide in layout.pad_guides:
                    self.assertTrue(
                        all(
                            layout.bounds_min.x <= point.x <= layout.bounds_max.x
                            and layout.bounds_min.y <= point.y <= layout.bounds_max.y
                            for point in guide
                        )
                    )

    def test_vertical_pins_left_produces_padding_pin_gap_right_aligned_labels(self):
        sizes = (Size(1.0, 1.0), Size(2.0, 1.0), Size(3.0, 1.0))
        layout = layout_pin_header(
            self.make_spec(3, orientation="vertical", label_side="right"),
            sizes,
        )
        self.assertAlmostEqual(-1.3, layout.bounds_min.x)
        self.assertAlmostEqual(4.6, layout.bounds_max.x)
        right_edges = tuple(centre.x + size.width / 2.0 for centre, size in zip(layout.label_centres, sizes))
        self.assertTrue(all(abs(edge - 4.3) < 1e-9 for edge in right_edges))
        self.assertTrue(all(centre.x > 0.0 for centre in layout.label_centres))

    def test_vertical_pins_right_is_the_opposite_left_aligned_layout(self):
        sizes = (Size(1.0, 1.0), Size(2.0, 1.0), Size(3.0, 1.0))
        layout = layout_pin_header(
            self.make_spec(3, orientation="vertical", label_side="left"),
            sizes,
        )
        left_edges = tuple(centre.x - size.width / 2.0 for centre, size in zip(layout.label_centres, sizes))
        self.assertTrue(all(abs(edge + 4.3) < 1e-9 for edge in left_edges))
        self.assertTrue(all(centre.x < 0.0 for centre in layout.label_centres))

    def test_cross_axis_padding_is_independently_controllable(self):
        layout = layout_pin_header(
            self.make_spec(
                3,
                orientation="vertical",
                label_side="right",
                pad_clearance_mm=2.0,
                pin_outer_padding_mm=3.0,
                pin_to_label_gap_mm=5.0,
                label_outer_padding_mm=1.0,
            ),
            (Size(2.0, 1.0),) * 3,
        )
        # Pins occupy x=-1…1.  The rail retains 3 mm outside the pin
        # envelope and 5 mm before text starts, independently of its 1 mm
        # label-side outer padding.
        self.assertAlmostEqual(-4.0, layout.bounds_min.x)
        self.assertAlmostEqual(9.0, layout.bounds_max.x)
        self.assertAlmostEqual(6.0, layout.label_centres[0].x - 1.0)
        self.assertAlmostEqual(8.0, layout.label_centres[0].x + 1.0)

    def test_fixed_cross_dimension_keeps_labels_outer_aligned(self):
        layout = layout_pin_header(
            self.make_spec(
                3,
                orientation="vertical",
                label_side="right",
                rail_cross_size_mm=15.0,
            ),
            (Size(2.0, 1.0),) * 3,
        )
        self.assertAlmostEqual(15.0, layout.size.width)
        right_edges = tuple(centre.x + 1.0 for centre in layout.label_centres)
        self.assertTrue(all(abs(edge - (layout.bounds_max.x - 0.3)) < 1e-9 for edge in right_edges))

    def test_horizontal_layout_is_the_same_model_rotated_90_degrees(self):
        sizes = (Size(1.0, 1.0), Size(2.0, 1.0), Size(3.0, 1.0))
        pins_top = layout_pin_header(
            self.make_spec(3, orientation="horizontal", label_side="below"),
            sizes,
        )
        pins_bottom = layout_pin_header(
            self.make_spec(3, orientation="horizontal", label_side="above"),
            sizes,
        )
        self.assertEqual((90.0, 90.0, 90.0), pins_top.label_rotations_deg)
        self.assertEqual((-90.0, -90.0, -90.0), pins_bottom.label_rotations_deg)
        bottom_edges = tuple(centre.y + size.width / 2.0 for centre, size in zip(pins_top.label_centres, sizes))
        top_edges = tuple(centre.y - size.width / 2.0 for centre, size in zip(pins_bottom.label_centres, sizes))
        self.assertTrue(all(abs(edge - 4.3) < 1e-9 for edge in bottom_edges))
        self.assertTrue(all(abs(edge + 4.3) < 1e-9 for edge in top_edges))

    def test_pin1_end_reverses_row_but_keeps_pin1_anchor(self):
        start = layout_pin_header(self.make_spec(3), (Size(1.0, 1.0),) * 3)
        end = layout_pin_header(self.make_spec(3, pin1_end="end"), (Size(1.0, 1.0),) * 3)
        self.assertEqual(0.0, start.pin_centres[0].x)
        self.assertEqual(0.0, end.pin_centres[0].x)
        self.assertEqual(5.08, start.pin_centres[-1].x)
        self.assertEqual(-5.08, end.pin_centres[-1].x)

    def test_independent_header_edges_follow_pin_and_label_sides(self):
        def has_point(points, x, y):
            return any(abs(point.x - x) < 1e-8 and abs(point.y - y) < 1e-8 for point in points)

        for orientation, label_side, pin_edge in (
            ("horizontal", "below", "top"),
            ("horizontal", "above", "bottom"),
            ("vertical", "right", "left"),
            ("vertical", "left", "right"),
        ):
            with self.subTest(orientation=orientation, label_side=label_side):
                style = replace(
                    header_style(),
                    shape=replace(
                        header_style().shape,
                        corner_radius_mm=0.6,
                        start_cap="square",
                        end_cap="rounded",
                    ),
                )
                layout = layout_pin_header(
                    self.make_spec(
                        4,
                        orientation=orientation,
                        label_side=label_side,
                        shape="custom_long_edges",
                        style=style,
                    ),
                    (Size(1.0, 1.0),) * 4,
                )
                points = layout.rail.regions[0].outer
                minimum, maximum = layout.bounds_min, layout.bounds_max
                corners = {
                    "top": ((minimum.x, minimum.y), (maximum.x, minimum.y)),
                    "bottom": ((minimum.x, maximum.y), (maximum.x, maximum.y)),
                    "left": ((minimum.x, minimum.y), (minimum.x, maximum.y)),
                    "right": ((maximum.x, minimum.y), (maximum.x, maximum.y)),
                }
                label_edge = {
                    "top": "bottom",
                    "bottom": "top",
                    "left": "right",
                    "right": "left",
                }[pin_edge]
                self.assertTrue(all(has_point(points, *corner) for corner in corners[pin_edge]))
                self.assertTrue(all(not has_point(points, *corner) for corner in corners[label_edge]))

    def test_composition_preserves_mapped_long_edge_geometry(self):
        style = replace(
            header_style(),
            shape=replace(
                header_style().shape,
                corner_radius_mm=0.6,
                start_cap="square",
                end_cap="rounded",
            ),
        )
        layout = layout_pin_header(
            self.make_spec(
                4,
                orientation="vertical",
                label_side="right",
                shape="custom_long_edges",
                style=style,
            ),
            (Size(1.0, 1.0),) * 4,
        )
        rendered = render_document_shapes(layout.to_composition_document())
        self.assertEqual(1, len(rendered))
        expected = layout.rail.regions[0].outer
        actual = rendered[0].geometry.regions[0].outer
        self.assertEqual(len(expected), len(actual))
        for expected_point, actual_point in zip(expected, actual):
            self.assertAlmostEqual(expected_point.x, actual_point.x)
            self.assertAlmostEqual(expected_point.y, actual_point.y)

    def test_pin1_anchor_does_not_move_when_labels_or_style_change(self):
        compact = layout_pin_header(self.make_spec(4), (Size(0.5, 0.5),) * 4)
        wide = layout_pin_header(
            self.make_spec(4, shape="pill", label_padding_mm=2.0),
            (Size(8.0, 2.0),) * 4,
        )
        self.assertEqual(compact.anchor, wide.anchor)
        self.assertEqual(compact.pin_centres[0], wide.pin_centres[0])

    def test_pin1_marker_is_optional_and_stays_on_the_rail(self):
        marked = layout_pin_header(self.make_spec(4, pin1_marker=True), (Size(1.0, 1.0),) * 4)
        unmarked = layout_pin_header(self.make_spec(4, pin1_marker=False), (Size(1.0, 1.0),) * 4)
        self.assertIsNotNone(marked.pin1_marker)
        self.assertIsNone(unmarked.pin1_marker)
        self.assertTrue(
            all(
                marked.bounds_min.x <= point.x <= marked.bounds_max.x
                and marked.bounds_min.y <= point.y <= marked.bounds_max.y
                for point in marked.pin1_marker
            )
        )

    def test_bottom_output_is_exactly_one_x_mirror(self):
        front = layout_pin_header(self.make_spec(3, output_layer="F.SilkS"), (Size(1.0, 1.0),) * 3)
        bottom = layout_pin_header(self.make_spec(3, output_layer="B.SilkS"), (Size(1.0, 1.0),) * 3)
        mirrored = mirror_layout_for_output(bottom)
        for front_point, bottom_point in zip(front.pin_centres, mirrored.pin_centres):
            self.assertAlmostEqual(-front_point.x, bottom_point.x)
            self.assertAlmostEqual(front_point.y, bottom_point.y)
        self.assertEqual(tuple(-value for value in bottom.label_rotations_deg), mirrored.label_rotations_deg)

    def test_serialisation_round_trip_preserves_layout_settings(self):
        spec = self.make_spec(
            4,
            pin_labels=("VCC", "GND", "SDA", "SCL"),
            orientation="vertical",
            label_side="right",
            pin1_end="end",
            pad_clearance_mm=6.5,
            leading_padding_mm=2.0,
            trailing_padding_mm=3.0,
            label_padding_mm=0.75,
            pin_outer_padding_mm=1.25,
            pin_to_label_gap_mm=2.5,
            label_outer_padding_mm=0.5,
            rail_cross_size_mm=12.0,
            opening_mode="continuous",
            opening_end_padding_mm=1.5,
            shape="pill",
            output_layer="B.Mask",
        )
        self.assertEqual(spec, PinHeaderSpec.from_json(spec.to_json()))

    def test_layout_builds_a_versioned_composition_with_preview_only_guides(self):
        layout = layout_pin_header(self.make_spec(3), (Size(1.0, 1.0),) * 3)
        document = layout.to_composition_document()
        self.assertEqual("F.SilkS", document.output_layer)
        self.assertEqual(4, len([item for item in document.objects if item.kind == "guide"]))
        self.assertEqual(document, type(document).from_json(document.to_json()))

    @staticmethod
    def segment_distance(point, start, end):
        dx = end.x - start.x
        dy = end.y - start.y
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            return math.hypot(point.x - start.x, point.y - start.y)
        projection = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_squared
        projection = min(1.0, max(0.0, projection))
        nearest_x = start.x + projection * dx
        nearest_y = start.y + projection * dy
        return math.hypot(point.x - nearest_x, point.y - nearest_y)


if __name__ == "__main__":
    unittest.main()

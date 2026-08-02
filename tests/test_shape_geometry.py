"""Milestone 2 checks for the parametric shape and style engine."""

from __future__ import annotations

import math
import unittest

from kibeezard.core.composition import (
    CompositionDocument,
    DocumentStyle,
    Padding,
    Point,
    ShapeObject,
    ShapeStyle,
    Size,
)
from kibeezard.core.shape_geometry import (
    clamp_corner_radius,
    content_box,
    polygon_bounds,
    render_document_shapes,
    render_shape,
    shape_contour,
    size_from_polygons,
    transform_geometry,
)
from kibeezard.core.transforms import SUPPORTED_OUTPUT_LAYERS


class ShapeGeometryTests(unittest.TestCase):
    def assertPointAlmostEqual(self, first, second, places=7):
        self.assertAlmostEqual(first.x, second.x, places=places)
        self.assertAlmostEqual(first.y, second.y, places=places)

    def test_asymmetric_padding_sizes_and_positions_content(self):
        style = ShapeStyle(padding=Padding(top=1.0, right=2.0, bottom=3.0, left=4.0))
        box = content_box(Size(10.0, 5.0), style)
        self.assertEqual(Size(16.0, 9.0), box.size)
        self.assertEqual(Point(1.0, -1.0), box.centre)

    def test_rectangle_outer_dimensions_are_exact(self):
        style = ShapeStyle(padding=Padding())
        geometry = render_shape(ShapeObject("shape", "rectangle", size=Size(10.0, 4.0)), style)
        self.assertEqual(Size(10.0, 4.0), geometry.outer_size)
        minimum, maximum = polygon_bounds((geometry.regions[0].outer,))
        self.assertEqual(Point(-5.0, -2.0), minimum)
        self.assertEqual(Point(5.0, 2.0), maximum)

    def test_rounded_radius_clamps_and_pill_uses_half_height(self):
        self.assertEqual(2.0, clamp_corner_radius(10.0, 4.0, 99.0))
        rounded = shape_contour(
            "rounded_rectangle",
            Size(10.0, 4.0),
            ShapeStyle(corner_radius_mm=99.0),
        )
        pill = shape_contour("pill", Size(10.0, 4.0), ShapeStyle())
        self.assertEqual(rounded, pill)
        self.assertGreater(len(pill), 20)

    def test_outline_border_preserves_outer_dimensions(self):
        style = ShapeStyle(
            padding=Padding(),
            filled=False,
            border_thickness_mm=0.5,
            corner_radius_mm=1.0,
        )
        geometry = render_shape(ShapeObject("shape", "rounded_rectangle", size=Size(10.0, 6.0)), style)
        self.assertEqual(Size(10.0, 6.0), size_from_polygons((geometry.regions[0].outer,)))
        self.assertEqual(1, len(geometry.regions[0].holes))
        inner_size = size_from_polygons(geometry.regions[0].holes)
        self.assertAlmostEqual(9.0, inner_size.width, places=6)
        self.assertAlmostEqual(5.0, inner_size.height, places=6)

    def test_large_border_deterministically_becomes_solid(self):
        style = ShapeStyle(padding=Padding(), filled=False, border_thickness_mm=10.0)
        geometry = render_shape(ShapeObject("shape", size=Size(2.0, 1.0)), style)
        self.assertEqual((), geometry.regions[0].holes)

    def test_inverted_shape_marks_content_as_knockout(self):
        style = ShapeStyle(padding=Padding(), filled=True, inverted=True)
        geometry = render_shape(ShapeObject("shape", "pill", size=Size(8.0, 3.0)), style)
        self.assertEqual("knockout", geometry.content_polarity)

    def test_all_planned_shapes_generate_finite_geometry(self):
        for shape in ("rectangle", "rounded_rectangle", "pill", "custom_ends", "custom_long_edges", "pointer", "flag", "tab", "chamfer", "hexagon"):
            with self.subTest(shape=shape):
                contour = shape_contour(
                    shape,
                    Size(12.0, 5.0),
                    ShapeStyle(corner_radius_mm=1.0, feature_size_mm=1.0),
                )
                self.assertGreaterEqual(len(contour), 4)
                self.assertTrue(all(math.isfinite(point.x) and math.isfinite(point.y) for point in contour))
                self.assertEqual(Size(12.0, 5.0), size_from_polygons((contour,)))

    def test_all_planned_shapes_support_outline_borders(self):
        for shape in ("rectangle", "rounded_rectangle", "pill", "custom_ends", "custom_long_edges", "pointer", "flag", "tab", "chamfer", "hexagon"):
            with self.subTest(shape=shape):
                geometry = render_shape(
                    ShapeObject("shape", shape, size=Size(12.0, 5.0)),
                    ShapeStyle(
                        filled=False,
                        border_thickness_mm=0.2,
                        corner_radius_mm=1.0,
                        feature_size_mm=1.0,
                    ),
                )
                self.assertEqual(1, len(geometry.regions[0].holes))
                self.assertGreaterEqual(len(geometry.regions[0].holes[0]), 3)

    def test_independent_end_caps_support_all_four_square_rounded_combinations(self):
        for start_cap, end_cap in (
            ("square", "square"),
            ("square", "rounded"),
            ("rounded", "square"),
            ("rounded", "rounded"),
        ):
            with self.subTest(start=start_cap, end=end_cap):
                contour = shape_contour(
                    "custom_ends",
                    Size(10.0, 4.0),
                    ShapeStyle(start_cap=start_cap, end_cap=end_cap),
                )
                self.assertEqual(Size(10.0, 4.0), size_from_polygons((contour,)))
                left_edge = [point for point in contour if abs(point.x + 5.0) < 1e-9]
                right_edge = [point for point in contour if abs(point.x - 5.0) < 1e-9]
                self.assertEqual(2 if start_cap == "square" else 1, len(left_edge))
                self.assertEqual(2 if end_cap == "square" else 1, len(right_edge))

    def test_independent_end_caps_support_extended_styles_on_either_side(self):
        for cap in ("square", "rounded", "chamfered", "point", "notch"):
            for side in ("start", "end"):
                with self.subTest(cap=cap, side=side):
                    contour = shape_contour(
                        "custom_ends",
                        Size(10.0, 4.0),
                        ShapeStyle(
                            start_cap=cap if side == "start" else "square",
                            end_cap=cap if side == "end" else "square",
                        ),
                    )
                    self.assertEqual(Size(10.0, 4.0), size_from_polygons((contour,)))
                    self.assertTrue(
                        all(math.isfinite(point.x) and math.isfinite(point.y) for point in contour)
                    )

    def test_independent_long_edges_round_corners_without_creating_end_caps(self):
        contour = shape_contour(
            "custom_long_edges",
            Size(20.0, 6.0),
            ShapeStyle(
                corner_radius_mm=0.6,
                start_cap="square",
                end_cap="rounded",
            ),
        )
        self.assertEqual(Size(20.0, 6.0), size_from_polygons((contour,)))
        self.assertIn(Point(-10.0, -3.0), contour)
        self.assertIn(Point(10.0, -3.0), contour)
        self.assertNotIn(Point(-10.0, 3.0), contour)
        self.assertNotIn(Point(10.0, 3.0), contour)
        # The radius control, rather than half the enclosure height, controls
        # how far each rounded corner is inset.
        self.assertIn(Point(9.4, 3.0), contour)
        self.assertIn(Point(-9.4, 3.0), contour)

    def test_content_measurement_controls_auto_sized_shapes(self):
        style = ShapeStyle(padding=Padding.symmetric(horizontal=1.0, vertical=0.5))
        one_line = render_shape(ShapeObject("shape", "pill"), style, Size(8.0, 2.0))
        multiline = render_shape(ShapeObject("shape", "pill"), style, Size(8.0, 5.0))
        self.assertEqual(Size(10.0, 3.0), one_line.outer_size)
        self.assertEqual(Size(10.0, 6.0), multiline.outer_size)

    def test_bottom_layers_are_exactly_one_x_mirror(self):
        shape = ShapeObject("shape", "pointer", size=Size(10.0, 4.0))
        base = render_shape(shape, ShapeStyle(feature_size_mm=2.0))
        front = transform_geometry(base, "F.SilkS", rotation_deg=17.0, translation=Point(3.0, 4.0))
        bottom = transform_geometry(base, "B.SilkS", rotation_deg=17.0, translation=Point(3.0, 4.0))
        front_points = front.regions[0].outer
        bottom_points = bottom.regions[0].outer
        for front_point, bottom_point in zip(front_points, bottom_points):
            self.assertAlmostEqual(-front_point.x, bottom_point.x)
            self.assertAlmostEqual(front_point.y, bottom_point.y)

        for layer in SUPPORTED_OUTPUT_LAYERS:
            transformed = transform_geometry(base, layer)
            expected_x = -base.regions[0].outer[0].x if layer.startswith("B.") else base.regions[0].outer[0].x
            self.assertAlmostEqual(expected_x, transformed.regions[0].outer[0].x)

    def test_document_renderer_is_stable_and_uses_document_placement(self):
        shape = ShapeObject("shape", "rounded_rectangle", position=Point(2.0, 1.0), rotation_deg=15.0)
        document = CompositionDocument(
            objects=(shape,),
            output_layer="F.Cu",
            origin=Point(10.0, 20.0),
            rotation_deg=5.0,
            style=DocumentStyle(shape=ShapeStyle(padding=Padding.symmetric(1.0, 0.5), corner_radius_mm=1.0)),
        )
        first = render_document_shapes(document, {"shape": Size(6.0, 2.0)})
        second = render_document_shapes(CompositionDocument.from_json(document.to_json()), {"shape": Size(6.0, 2.0)})
        self.assertEqual(first, second)
        self.assertEqual("shape", first[0].object_id)
        self.assertEqual(Size(8.0, 3.0), first[0].geometry.outer_size)


if __name__ == "__main__":
    unittest.main()

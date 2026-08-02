"""Pure layout model for single-row 2.54 mm pin-header label blocks."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ..version import __version__
from .composition import (
    CompositionDocument,
    DocumentStyle,
    GroupObject,
    GuideObject,
    IconObject,
    Padding,
    Point,
    SHAPE_KINDS,
    ShapeObject,
    ShapeStyle,
    Size,
    TextObject,
    TypographyStyle,
)
from .shape_geometry import Polygon, ShapeGeometry, polygon_bounds, render_shape, transform_geometry
from .transforms import (
    BOTTOM_COPPER,
    FRONT_COPPER,
    FRONT_SILKSCREEN,
    SUPPORTED_OUTPUT_LAYERS,
    is_bottom,
)


PIN_HEADER_SCHEMA_VERSION = 1
ORIENTATIONS = ("horizontal", "vertical")
PIN1_ENDS = ("start", "end")
LABEL_SIDES = ("above", "below", "left", "right")
OPENING_MODES = ("none", "continuous", "individual")


def _positive(name: str, value: float) -> None:
    if not math.isfinite(float(value)) or value <= 0:
        raise ValueError("{} must be greater than zero".format(name))


def _non_negative(name: str, value: float) -> None:
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError("{} must be non-negative".format(name))


@dataclass(frozen=True)
class PinHeaderSpec:
    """Editable parameters for one single-row connector label block."""

    pin_count: int
    pin_labels: Tuple[str, ...]
    pitch_mm: float = 2.54
    orientation: str = "horizontal"
    pin1_end: str = "start"
    label_side: str = "above"
    pad_clearance_mm: float = 2.0
    leading_padding_mm: float = 1.27
    trailing_padding_mm: float = 1.27
    label_padding_mm: float = 0.3
    opening_mode: str = "none"
    opening_end_padding_mm: float = 0.0
    pin1_marker: bool = True
    shape: str = "rounded_rectangle"
    output_layer: str = FRONT_SILKSCREEN
    style: DocumentStyle = field(default_factory=DocumentStyle)
    schema_version: int = PIN_HEADER_SCHEMA_VERSION
    generator_version: str = __version__

    def __post_init__(self) -> None:
        object.__setattr__(self, "pin_labels", tuple(self.pin_labels))
        if self.schema_version != PIN_HEADER_SCHEMA_VERSION:
            raise ValueError("Unsupported pin-header schema: {}".format(self.schema_version))
        if not isinstance(self.pin_count, int) or isinstance(self.pin_count, bool) or self.pin_count < 1:
            raise ValueError("pin_count must be a positive integer")
        if len(self.pin_labels) != self.pin_count:
            raise ValueError("pin label count must match pin_count")
        _positive("pitch_mm", self.pitch_mm)
        _positive("pad_clearance_mm", self.pad_clearance_mm)
        for name in (
            "leading_padding_mm",
            "trailing_padding_mm",
            "label_padding_mm",
            "opening_end_padding_mm",
        ):
            _non_negative(name, getattr(self, name))
        if self.orientation not in ORIENTATIONS:
            raise ValueError("Unsupported header orientation: {}".format(self.orientation))
        if self.pin1_end not in PIN1_ENDS:
            raise ValueError("Unsupported pin-1 end: {}".format(self.pin1_end))
        if self.label_side not in LABEL_SIDES:
            raise ValueError("Unsupported label side: {}".format(self.label_side))
        if self.orientation == "horizontal" and self.label_side not in ("above", "below"):
            raise ValueError("Horizontal headers require labels above or below")
        if self.orientation == "vertical" and self.label_side not in ("left", "right"):
            raise ValueError("Vertical headers require labels left or right")
        if self.opening_mode not in OPENING_MODES:
            raise ValueError("Unsupported connector opening: {}".format(self.opening_mode))
        if self.opening_mode == "individual" and self.pad_clearance_mm > self.pitch_mm:
            raise ValueError(
                "Individual pin openings cannot be wider than the pitch; use a continuous opening"
            )
        if self.shape not in SHAPE_KINDS:
            raise ValueError("Unsupported header shape: {}".format(self.shape))
        if self.output_layer not in SUPPORTED_OUTPUT_LAYERS:
            raise ValueError("Unsupported Kobee Studio output layer: {}".format(self.output_layer))
        if self.output_layer in (FRONT_COPPER, BOTTOM_COPPER) and self.opening_mode == "none":
            raise ValueError("Copper header blocks require a connector opening to avoid shorting pins")
        if not self.generator_version:
            raise ValueError("generator_version cannot be empty")

    def to_dict(self) -> Dict[str, Any]:
        typography = self.style.typography
        shape_style = self.style.shape
        return {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "pin_count": self.pin_count,
            "pitch_mm": self.pitch_mm,
            "pin_labels": list(self.pin_labels),
            "orientation": self.orientation,
            "pin1_end": self.pin1_end,
            "label_side": self.label_side,
            "pad_clearance_mm": self.pad_clearance_mm,
            "leading_padding_mm": self.leading_padding_mm,
            "trailing_padding_mm": self.trailing_padding_mm,
            "label_padding_mm": self.label_padding_mm,
            "opening_mode": self.opening_mode,
            "opening_end_padding_mm": self.opening_end_padding_mm,
            "pin1_marker": self.pin1_marker,
            "shape": self.shape,
            "output_layer": self.output_layer,
            "style": {
                "typography": {
                    "font_name": typography.font_name,
                    "height_mm": typography.height_mm,
                    "width_mm": typography.width_mm,
                    "line_spacing": typography.line_spacing,
                    "alignment": typography.alignment,
                },
                "shape": {
                    "padding": {
                        "top": shape_style.padding.top,
                        "right": shape_style.padding.right,
                        "bottom": shape_style.padding.bottom,
                        "left": shape_style.padding.left,
                    },
                    "border_thickness_mm": shape_style.border_thickness_mm,
                    "corner_radius_mm": shape_style.corner_radius_mm,
                    "feature_size_mm": shape_style.feature_size_mm,
                    "filled": shape_style.filled,
                    "inverted": shape_style.inverted,
                    "direction": shape_style.direction,
                    "start_cap": shape_style.start_cap,
                    "end_cap": shape_style.end_cap,
                },
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PinHeaderSpec":
        style_data = data.get("style", {})
        typography_data = style_data.get("typography", {})
        shape_data = style_data.get("shape", {})
        padding_data = shape_data.get("padding", {})
        style = DocumentStyle(
            typography=TypographyStyle(
                font_name=str(typography_data.get("font_name", "UbuntuMono-B")),
                height_mm=float(typography_data.get("height_mm", 1.0)),
                width_mm=float(typography_data.get("width_mm", 0.0)),
                line_spacing=float(typography_data.get("line_spacing", 1.5)),
                alignment=str(typography_data.get("alignment", "center")).lower(),
            ),
            shape=ShapeStyle(
                padding=Padding(
                    top=float(padding_data.get("top", 0.3)),
                    right=float(padding_data.get("right", 0.3)),
                    bottom=float(padding_data.get("bottom", 0.3)),
                    left=float(padding_data.get("left", 0.3)),
                ),
                border_thickness_mm=float(shape_data.get("border_thickness_mm", 0.2)),
                corner_radius_mm=float(shape_data.get("corner_radius_mm", 0.5)),
                feature_size_mm=float(shape_data.get("feature_size_mm", 0.75)),
                filled=bool(shape_data.get("filled", False)),
                inverted=bool(shape_data.get("inverted", False)),
                direction=str(shape_data.get("direction", "right")),
                start_cap=str(shape_data.get("start_cap", "square")),
                end_cap=str(shape_data.get("end_cap", "rounded")),
            ),
        )
        return cls(
            pin_count=int(data.get("pin_count", 0)),
            pin_labels=tuple(str(value) for value in data.get("pin_labels", ())),
            pitch_mm=float(data.get("pitch_mm", 2.54)),
            orientation=str(data.get("orientation", "horizontal")),
            pin1_end=str(data.get("pin1_end", "start")),
            label_side=str(data.get("label_side", "above")),
            pad_clearance_mm=float(data.get("pad_clearance_mm", 2.0)),
            leading_padding_mm=float(data.get("leading_padding_mm", 1.27)),
            trailing_padding_mm=float(data.get("trailing_padding_mm", 1.27)),
            label_padding_mm=float(data.get("label_padding_mm", 0.3)),
            # Existing 0.3.0-dev headers always used a continuous opening.
            opening_mode=str(data.get("opening_mode", "continuous")),
            opening_end_padding_mm=float(data.get("opening_end_padding_mm", 0.0)),
            pin1_marker=bool(data.get("pin1_marker", True)),
            shape=str(data.get("shape", "rounded_rectangle")),
            output_layer=str(data.get("output_layer", FRONT_SILKSCREEN)),
            style=style,
            schema_version=int(data.get("schema_version", 0)),
            generator_version=str(data.get("generator_version", "unknown")),
        )

    @classmethod
    def from_json(cls, value: str) -> "PinHeaderSpec":
        data = json.loads(value)
        if not isinstance(data, Mapping):
            raise ValueError("Pin-header JSON must contain an object")
        return cls.from_dict(data)


@dataclass(frozen=True)
class HeaderLayout:
    spec: PinHeaderSpec
    pin_centres: Tuple[Point, ...]
    label_centres: Tuple[Point, ...]
    label_sizes: Tuple[Size, ...]
    label_rotations_deg: Tuple[float, ...]
    rail: ShapeGeometry
    rail_style: ShapeStyle
    rail_rotation_deg: float
    connector_keepout: Polygon
    pad_guides: Tuple[Polygon, ...]
    pin1_marker: Optional[Polygon]
    bounds_min: Point
    bounds_max: Point
    anchor: Point = Point()

    @property
    def size(self) -> Size:
        return Size(self.bounds_max.x - self.bounds_min.x, self.bounds_max.y - self.bounds_min.y)

    def to_composition_document(self) -> CompositionDocument:
        text_objects = tuple(
            TextObject(
                "header.label.{}".format(index + 1),
                label,
                position=centre,
                rotation_deg=rotation,
            )
            for index, (label, centre, rotation) in enumerate(
                zip(self.spec.pin_labels, self.label_centres, self.label_rotations_deg)
            )
        )
        guide_objects = tuple(
            GuideObject(
                "header.pad-guide.{}".format(index + 1),
                guide_type="circle",
                position=centre,
                size=Size(self.spec.pad_clearance_mm, self.spec.pad_clearance_mm),
            )
            for index, centre in enumerate(self.pin_centres)
        )
        keepout_min, keepout_max = polygon_bounds((self.connector_keepout,))
        keepout_guide = GuideObject(
            "header.connector-keepout",
            guide_type="connector_keepout",
            position=Point(
                (keepout_min.x + keepout_max.x) / 2.0,
                (keepout_min.y + keepout_max.y) / 2.0,
            ),
            size=Size(keepout_max.x - keepout_min.x, keepout_max.y - keepout_min.y),
        )
        marker_objects = ()
        if self.pin1_marker:
            marker_min, marker_max = polygon_bounds((self.pin1_marker,))
            marker_objects = (
                IconObject(
                    "header.pin1-marker",
                    asset_id="builtin.pin1-triangle",
                    position=Point((marker_min.x + marker_max.x) / 2.0, (marker_min.y + marker_max.y) / 2.0),
                    size=Size(marker_max.x - marker_min.x, marker_max.y - marker_min.y),
                ),
            )
        rail = ShapeObject(
            "header.rail",
            shape=self.spec.shape,
            position=self.rail.content_box.centre,
            size=self.rail.outer_size,
            rotation_deg=self.rail_rotation_deg,
            content_ids=tuple(item.object_id for item in text_objects),
        )
        # The rendered rail centre is recovered from its bounds because the
        # content-box centre describes padding, not object placement.
        rail_min, rail_max = polygon_bounds((self.rail.regions[0].outer,))
        rail = ShapeObject(
            rail.object_id,
            shape=rail.shape,
            position=Point((rail_min.x + rail_max.x) / 2.0, (rail_min.y + rail_max.y) / 2.0),
            size=rail.size,
            rotation_deg=rail.rotation_deg,
            content_ids=rail.content_ids,
        )
        children = (rail.object_id,) + tuple(
            item.object_id for item in text_objects + marker_objects + (keepout_guide,) + guide_objects
        )
        group = GroupObject("header.group", children)
        return CompositionDocument(
            objects=text_objects + (rail,) + marker_objects + (keepout_guide,) + guide_objects + (group,),
            output_layer=self.spec.output_layer,
            anchor=self.anchor,
            origin=Point(),
            size=self.size,
            style=replace(self.spec.style, shape=self.rail_style),
            generator_version=self.spec.generator_version,
        )


def _circle(centre: Point, diameter: float, segments: int = 32) -> Polygon:
    radius = diameter / 2.0
    return tuple(
        Point(
            centre.x + radius * math.cos(2.0 * math.pi * index / segments),
            centre.y + radius * math.sin(2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    )


def layout_pin_header(spec: PinHeaderSpec, label_sizes: Sequence[Size]) -> HeaderLayout:
    """Lay out one enclosure around a pin row and its aligned labels.

    Across the short axis the layout is always::

        outer padding | connector clearance | label gap | label | outer padding

    ``label_side`` selects which side of the pins contains the labels.  Labels
    align at the edge furthest from the pins, so a vertical row with pins on
    the left has right-aligned text.  Horizontal rows use the same layout
    rotated 90 degrees.
    """
    sizes = tuple(label_sizes)
    if len(sizes) != spec.pin_count:
        raise ValueError("label size count must match pin_count")

    direction = 1.0 if spec.pin1_end == "start" else -1.0
    if spec.orientation == "horizontal":
        pin_centres = tuple(Point(direction * index * spec.pitch_mm, 0.0) for index in range(spec.pin_count))
        axis_values = tuple(point.x for point in pin_centres)
        rotations = tuple(-90.0 if spec.label_side == "above" else 90.0 for _ in sizes)
        # Rotated text is one capital-height wide along the pin row and its
        # natural text width extends away from the connector.
        label_axis_sizes = tuple(size.height for size in sizes)
        label_cross_sizes = tuple(size.width for size in sizes)
    else:
        pin_centres = tuple(Point(0.0, direction * index * spec.pitch_mm) for index in range(spec.pin_count))
        axis_values = tuple(point.y for point in pin_centres)
        label_axis_sizes = tuple(size.height for size in sizes)
        label_cross_sizes = tuple(size.width for size in sizes)
        rotations = tuple(0.0 for _ in sizes)

    clearance_radius = spec.pad_clearance_mm / 2.0
    first_axis = axis_values[0]
    last_axis = axis_values[-1]
    if direction > 0:
        axis_min = first_axis - clearance_radius - spec.leading_padding_mm
        axis_max = last_axis + clearance_radius + spec.trailing_padding_mm
    else:
        axis_min = last_axis - clearance_radius - spec.trailing_padding_mm
        axis_max = first_axis + clearance_radius + spec.leading_padding_mm
    if spec.opening_mode == "continuous":
        axis_min = min(
            axis_min,
            min(axis_values) - clearance_radius - spec.opening_end_padding_mm - spec.label_padding_mm,
        )
        axis_max = max(
            axis_max,
            max(axis_values) + clearance_radius + spec.opening_end_padding_mm + spec.label_padding_mm,
        )
    for centre, label_axis_size in zip(axis_values, label_axis_sizes):
        axis_min = min(axis_min, centre - label_axis_size / 2.0 - spec.label_padding_mm)
        axis_max = max(axis_max, centre + label_axis_size / 2.0 + spec.label_padding_mm)

    maximum_label_cross = max(label_cross_sizes, default=0.0)
    negative_side = spec.label_side in ("above", "left")
    near_edge = -clearance_radius - spec.label_padding_mm if negative_side else clearance_radius + spec.label_padding_mm
    far_text_edge = near_edge - maximum_label_cross if negative_side else near_edge + maximum_label_cross
    cross_min = far_text_edge - spec.label_padding_mm if negative_side else -clearance_radius - spec.label_padding_mm
    cross_max = clearance_radius + spec.label_padding_mm if negative_side else far_text_edge + spec.label_padding_mm
    cross_size = max(0.001, cross_max - cross_min)
    axis_centre = (axis_min + axis_max) / 2.0
    axis_size = max(0.001, axis_max - axis_min)
    cross_centre = (cross_min + cross_max) / 2.0

    # Align every label at the outer edge away from the pins.  This produces
    # right-aligned text when the pin row is on the left and the exact mirror
    # when the row is on the right.
    label_cross_centres = tuple(
        far_text_edge + label_size / 2.0 if negative_side else far_text_edge - label_size / 2.0
        for label_size in label_cross_sizes
    )
    if spec.orientation == "horizontal":
        rail_centre = Point(axis_centre, cross_centre)
        rail_rotation = 0.0
        label_centres = tuple(
            Point(point.x, cross) for point, cross in zip(pin_centres, label_cross_centres)
        )
    else:
        rail_centre = Point(cross_centre, axis_centre)
        rail_rotation = 90.0
        label_centres = tuple(
            Point(cross, point.y) for point, cross in zip(pin_centres, label_cross_centres)
        )

    # Shapes are authored along the pin axis, then vertical headers rotate the
    # same geometry 90 degrees.  For the asymmetric header shape, style names
    # are semantic: start_cap is the pin-side long edge and end_cap is the
    # label-side long edge.  Map those onto the local top/bottom corners.
    rail_size = Size(axis_size, cross_size)
    rail_object = ShapeObject("header.rail", shape=spec.shape, size=rail_size)
    # All required spacing is already included in ``rail_size``.  Do not let
    # the generic label padding expand the explicitly dimensioned enclosure a
    # second time.
    rail_style = replace(spec.style.shape, padding=Padding())
    if spec.shape == "custom_long_edges":
        pin_edge = rail_style.start_cap
        label_edge = rail_style.end_cap
        pin_is_local_top = (
            not negative_side if spec.orientation == "horizontal" else negative_side
        )
        rail_style = replace(
            rail_style,
            start_cap=pin_edge if pin_is_local_top else label_edge,
            end_cap=label_edge if pin_is_local_top else pin_edge,
        )
    rail = render_shape(rail_object, rail_style)
    # Layout geometry stays in board coordinates. Mirroring happens once at
    # preview/export boundaries, just like ordinary Kobee Studio labels.
    rail = transform_geometry(
        rail,
        FRONT_SILKSCREEN,
        rotation_deg=rail_rotation,
        translation=rail_centre,
    )
    rail_min, rail_max = polygon_bounds((rail.regions[0].outer,))
    guides = tuple(_circle(centre, spec.pad_clearance_mm) for centre in pin_centres)
    keepout_axis_min = min(axis_values) - clearance_radius - spec.opening_end_padding_mm
    keepout_axis_max = max(axis_values) + clearance_radius + spec.opening_end_padding_mm
    keepout_axis_size = keepout_axis_max - keepout_axis_min
    keepout_axis_centre = (keepout_axis_min + keepout_axis_max) / 2.0
    if spec.orientation == "horizontal":
        keepout_size = Size(keepout_axis_size, spec.pad_clearance_mm)
        keepout_centre = Point(keepout_axis_centre, 0.0)
    else:
        keepout_size = Size(spec.pad_clearance_mm, keepout_axis_size)
        keepout_centre = Point(0.0, keepout_axis_centre)
    keepout_object = ShapeObject("header.connector-keepout", shape="pill", size=keepout_size)
    keepout_style = replace(
        spec.style.shape,
        padding=Padding(),
        filled=True,
        inverted=False,
        border_thickness_mm=0.0,
    )
    keepout_geometry = render_shape(keepout_object, keepout_style)
    keepout_geometry = transform_geometry(
        keepout_geometry,
        FRONT_SILKSCREEN,
        translation=keepout_centre,
    )
    connector_keepout = keepout_geometry.regions[0].outer
    marker = None
    if spec.pin1_marker:
        marker_size = min(0.4, spec.label_padding_mm, cross_size * 0.2)
        if marker_size <= 0.05:
            marker_size = min(0.2, cross_size * 0.1)
        edge_inset = marker_size * 0.15
        half = marker_size / 2.0
        pin1 = pin_centres[0]
        if spec.label_side == "above":
            marker = (
                Point(pin1.x, rail_min.y + edge_inset),
                Point(pin1.x - half, rail_min.y + marker_size),
                Point(pin1.x + half, rail_min.y + marker_size),
            )
        elif spec.label_side == "below":
            marker = (
                Point(pin1.x, rail_max.y - edge_inset),
                Point(pin1.x - half, rail_max.y - marker_size),
                Point(pin1.x + half, rail_max.y - marker_size),
            )
        elif spec.label_side == "left":
            marker = (
                Point(rail_min.x + edge_inset, pin1.y),
                Point(rail_min.x + marker_size, pin1.y - half),
                Point(rail_min.x + marker_size, pin1.y + half),
            )
        else:
            marker = (
                Point(rail_max.x - edge_inset, pin1.y),
                Point(rail_max.x - marker_size, pin1.y - half),
                Point(rail_max.x - marker_size, pin1.y + half),
            )

    return HeaderLayout(
        spec=spec,
        pin_centres=pin_centres,
        label_centres=label_centres,
        label_sizes=sizes,
        label_rotations_deg=rotations,
        rail=rail,
        rail_style=rail_style,
        rail_rotation_deg=rail_rotation,
        connector_keepout=connector_keepout,
        pad_guides=guides,
        pin1_marker=marker,
        bounds_min=rail_min,
        bounds_max=rail_max,
    )


def mirror_layout_for_output(layout: HeaderLayout) -> HeaderLayout:
    """Return the front-view bottom-layer mirror, or the unchanged layout."""
    if not is_bottom(layout.spec.output_layer):
        return layout

    def mirror_point(point: Point) -> Point:
        return Point(-point.x, point.y)

    def mirror_polygon(polygon: Polygon) -> Polygon:
        return tuple(mirror_point(point) for point in reversed(polygon))

    rail = ShapeGeometry(
        regions=tuple(
            type(region)(
                outer=mirror_polygon(region.outer),
                holes=tuple(mirror_polygon(hole) for hole in region.holes),
            )
            for region in layout.rail.regions
        ),
        outer_size=layout.rail.outer_size,
        content_box=type(layout.rail.content_box)(
            size=layout.rail.content_box.size,
            centre=mirror_point(layout.rail.content_box.centre),
        ),
        content_polarity=layout.rail.content_polarity,
    )
    return HeaderLayout(
        spec=layout.spec,
        pin_centres=tuple(mirror_point(point) for point in layout.pin_centres),
        label_centres=tuple(mirror_point(point) for point in layout.label_centres),
        label_sizes=layout.label_sizes,
        label_rotations_deg=tuple(-rotation for rotation in layout.label_rotations_deg),
        rail=rail,
        rail_style=layout.rail_style,
        rail_rotation_deg=-layout.rail_rotation_deg,
        connector_keepout=mirror_polygon(layout.connector_keepout),
        pad_guides=tuple(mirror_polygon(polygon) for polygon in layout.pad_guides),
        pin1_marker=mirror_polygon(layout.pin1_marker) if layout.pin1_marker else None,
        bounds_min=Point(-layout.bounds_max.x, layout.bounds_min.y),
        bounds_max=Point(-layout.bounds_min.x, layout.bounds_max.y),
        anchor=mirror_point(layout.anchor),
    )

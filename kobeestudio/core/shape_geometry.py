"""Pure parametric shape geometry for Silk Studio compositions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .composition import CompositionDocument, Point, ShapeObject, ShapeStyle, Size
from .transforms import is_bottom


Polygon = Tuple[Point, ...]


@dataclass(frozen=True)
class ContentBox:
    size: Size
    centre: Point


@dataclass(frozen=True)
class PolygonRegion:
    outer: Polygon
    holes: Tuple[Polygon, ...] = ()


@dataclass(frozen=True)
class ShapeGeometry:
    regions: Tuple[PolygonRegion, ...]
    outer_size: Size
    content_box: ContentBox
    content_polarity: str = "positive"


@dataclass(frozen=True)
class RenderedShape:
    object_id: str
    geometry: ShapeGeometry


def content_box(content_size: Size, style: ShapeStyle) -> ContentBox:
    """Return padded outer size and the content centre within that box."""
    padding = style.padding
    size = Size(
        content_size.width + padding.left + padding.right,
        content_size.height + padding.top + padding.bottom,
    )
    return ContentBox(
        size=size,
        centre=Point(
            (padding.left - padding.right) / 2.0,
            (padding.top - padding.bottom) / 2.0,
        ),
    )


def polygon_bounds(polygons: Iterable[Sequence[Point]]) -> Tuple[Point, Point]:
    points = [point for polygon in polygons for point in polygon]
    if not points:
        return Point(), Point()
    return (
        Point(min(point.x for point in points), min(point.y for point in points)),
        Point(max(point.x for point in points), max(point.y for point in points)),
    )


def size_from_polygons(polygons: Iterable[Sequence[Point]]) -> Size:
    minimum, maximum = polygon_bounds(polygons)
    return Size(maximum.x - minimum.x, maximum.y - minimum.y)


def clamp_corner_radius(width: float, height: float, requested: float) -> float:
    if width <= 0 or height <= 0:
        raise ValueError("Shape dimensions must be greater than zero")
    return min(max(0.0, requested), width / 2.0, height / 2.0)


def _rectangle(width: float, height: float) -> Polygon:
    half_width = width / 2.0
    half_height = height / 2.0
    return (
        Point(-half_width, -half_height),
        Point(half_width, -half_height),
        Point(half_width, half_height),
        Point(-half_width, half_height),
    )


def _rounded_rectangle(width: float, height: float, radius: float, segments_per_corner: int = 8) -> Polygon:
    radius = clamp_corner_radius(width, height, radius)
    if radius == 0:
        return _rectangle(width, height)

    half_width = width / 2.0
    half_height = height / 2.0
    centres = (
        (half_width - radius, -half_height + radius, -90.0),
        (half_width - radius, half_height - radius, 0.0),
        (-half_width + radius, half_height - radius, 90.0),
        (-half_width + radius, -half_height + radius, 180.0),
    )
    points = []
    segments = max(1, int(segments_per_corner))
    for centre_x, centre_y, start_degrees in centres:
        for index in range(segments + 1):
            angle = math.radians(start_degrees + (90.0 * index / segments))
            point = Point(centre_x + radius * math.cos(angle), centre_y + radius * math.sin(angle))
            if not points or point != points[-1]:
                points.append(point)
    if points and points[0] == points[-1]:
        points.pop()
    return tuple(points)


def _custom_ends(
    width: float,
    height: float,
    start_cap: str,
    end_cap: str,
    segments_per_cap: int = 12,
) -> Polygon:
    """Build a horizontal tag with two independently styled ends."""
    half_width = width / 2.0
    half_height = height / 2.0
    radius = min(half_height, half_width)
    feature = min(height * 0.34, width / 2.0)

    def join_x(style: str) -> float:
        return radius if style == "rounded" else feature if style in ("chamfered", "point") else 0.0

    def right_cap(style: str) -> Tuple[Point, ...]:
        if style == "rounded":
            centre_x = half_width - radius
            return tuple(
                Point(
                    centre_x + radius * math.cos(math.radians(-90.0 + 180.0 * index / segments_per_cap)),
                    radius * math.sin(math.radians(-90.0 + 180.0 * index / segments_per_cap)),
                )
                for index in range(segments_per_cap + 1)
            )
        if style == "chamfered":
            return (
                Point(half_width - feature, -half_height),
                Point(half_width, -half_height + feature),
                Point(half_width, half_height - feature),
                Point(half_width - feature, half_height),
            )
        if style == "point":
            return (
                Point(half_width - feature, -half_height),
                Point(half_width, 0.0),
                Point(half_width - feature, half_height),
            )
        if style == "notch":
            return (
                Point(half_width, -half_height),
                Point(half_width - feature, 0.0),
                Point(half_width, half_height),
            )
        return (Point(half_width, -half_height), Point(half_width, half_height))

    start_inset = join_x(start_cap)
    end_inset = join_x(end_cap)
    points = [Point(-half_width + start_inset, -half_height)]
    for point in right_cap(end_cap):
        if point != points[-1]:
            points.append(point)
    start_bottom = Point(-half_width + start_inset, half_height)
    if points[-1] != start_bottom:
        points.append(start_bottom)
    for point in tuple(Point(-point.x, point.y) for point in reversed(right_cap(start_cap))):
        if point != points[-1]:
            points.append(point)

    if points and points[0] == points[-1]:
        points.pop()
    return tuple(points)


def _custom_long_edges(
    width: float,
    height: float,
    top_edge: str,
    bottom_edge: str,
    radius: float,
    segments_per_corner: int = 8,
) -> Polygon:
    """Build a rectangle whose two long edges have independent corner styles.

    A rounded top edge rounds both top corners; a rounded bottom edge rounds
    both bottom corners.  Unlike ``custom_ends``, this uses the requested
    corner radius instead of turning either short end into a semicircle.
    """
    radius = clamp_corner_radius(width, height, radius)
    top_radius = radius if top_edge == "rounded" else 0.0
    bottom_radius = radius if bottom_edge == "rounded" else 0.0
    half_width = width / 2.0
    half_height = height / 2.0
    segments = max(1, int(segments_per_corner))
    points = []

    def append(point: Point) -> None:
        if not points or point != points[-1]:
            points.append(point)

    def arc(centre_x: float, centre_y: float, arc_radius: float, start_degrees: float) -> None:
        if arc_radius == 0:
            append(Point(centre_x, centre_y))
            return
        for index in range(segments + 1):
            angle = math.radians(start_degrees + 90.0 * index / segments)
            append(
                Point(
                    centre_x + arc_radius * math.cos(angle),
                    centre_y + arc_radius * math.sin(angle),
                )
            )

    append(Point(-half_width + top_radius, -half_height))
    append(Point(half_width - top_radius, -half_height))
    if top_radius:
        arc(half_width - top_radius, -half_height + top_radius, top_radius, -90.0)
    else:
        append(Point(half_width, -half_height))
    append(Point(half_width, half_height - bottom_radius))
    if bottom_radius:
        arc(half_width - bottom_radius, half_height - bottom_radius, bottom_radius, 0.0)
    else:
        append(Point(half_width, half_height))
    append(Point(-half_width + bottom_radius, half_height))
    if bottom_radius:
        arc(-half_width + bottom_radius, half_height - bottom_radius, bottom_radius, 90.0)
    else:
        append(Point(-half_width, half_height))
    append(Point(-half_width, -half_height + top_radius))
    if top_radius:
        arc(-half_width + top_radius, -half_height + top_radius, top_radius, 180.0)
    else:
        append(Point(-half_width, -half_height))

    if points and points[0] == points[-1]:
        points.pop()
    return tuple(points)


def _chamfer(width: float, height: float, feature: float) -> Polygon:
    half_width = width / 2.0
    half_height = height / 2.0
    cut = min(max(0.0, feature), half_width, half_height)
    if cut == 0:
        return _rectangle(width, height)
    return (
        Point(-half_width + cut, -half_height),
        Point(half_width - cut, -half_height),
        Point(half_width, -half_height + cut),
        Point(half_width, half_height - cut),
        Point(half_width - cut, half_height),
        Point(-half_width + cut, half_height),
        Point(-half_width, half_height - cut),
        Point(-half_width, -half_height + cut),
    )


def _pointer(width: float, height: float, feature: float) -> Polygon:
    half_width = width / 2.0
    half_height = height / 2.0
    tip = min(max(feature, 0.0), width)
    return (
        Point(-half_width, -half_height),
        Point(half_width - tip, -half_height),
        Point(half_width, 0.0),
        Point(half_width - tip, half_height),
        Point(-half_width, half_height),
    )


def _flag(width: float, height: float, feature: float) -> Polygon:
    half_width = width / 2.0
    half_height = height / 2.0
    feature = min(max(feature, 0.0), width / 2.0, height)
    return (
        Point(-half_width, -half_height),
        Point(half_width - feature, -half_height),
        Point(half_width, 0.0),
        Point(half_width - feature, half_height),
        Point(-half_width, half_height),
        Point(-half_width + feature, 0.0),
    )


def _tab(width: float, height: float, feature: float) -> Polygon:
    half_width = width / 2.0
    half_height = height / 2.0
    tab_half_width = max(width / 8.0, min(width / 2.0 - 0.001, max(feature, width / 4.0)))
    shoulder_y = -half_height + min(max(feature, 0.0), height / 2.0)
    return (
        Point(-half_width, shoulder_y),
        Point(-tab_half_width, shoulder_y),
        Point(-tab_half_width, -half_height),
        Point(tab_half_width, -half_height),
        Point(tab_half_width, shoulder_y),
        Point(half_width, shoulder_y),
        Point(half_width, half_height),
        Point(-half_width, half_height),
    )


def _hexagon(width: float, height: float, feature: float) -> Polygon:
    half_width = width / 2.0
    half_height = height / 2.0
    shoulder = min(max(feature, 0.0), width / 2.0)
    if shoulder == 0:
        shoulder = min(width / 4.0, half_height)
    return (
        Point(-half_width + shoulder, -half_height),
        Point(half_width - shoulder, -half_height),
        Point(half_width, 0.0),
        Point(half_width - shoulder, half_height),
        Point(-half_width + shoulder, half_height),
        Point(-half_width, 0.0),
    )


def _reverse_x(polygon: Polygon) -> Polygon:
    return tuple(Point(-point.x, point.y) for point in reversed(polygon))


def shape_contour(shape: str, size: Size, style: ShapeStyle) -> Polygon:
    """Build the outer contour for one supported parametric shape."""
    width, height = size.width, size.height
    if width <= 0 or height <= 0:
        raise ValueError("Shape dimensions must be greater than zero")

    if shape == "rectangle":
        polygon = _rectangle(width, height)
    elif shape == "circle":
        if not math.isclose(width, height, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("Circle shapes require equal width and height")
        polygon = _rounded_rectangle(width, height, width / 2.0)
    elif shape == "rounded_rectangle":
        polygon = _rounded_rectangle(width, height, style.corner_radius_mm)
    elif shape == "pill":
        polygon = _rounded_rectangle(width, height, min(width, height) / 2.0)
    elif shape == "custom_ends":
        polygon = _custom_ends(width, height, style.start_cap, style.end_cap)
    elif shape == "custom_long_edges":
        polygon = _custom_long_edges(
            width,
            height,
            style.start_cap,
            style.end_cap,
            style.corner_radius_mm,
        )
    elif shape == "pointer":
        polygon = _pointer(width, height, style.feature_size_mm)
    elif shape == "flag":
        polygon = _flag(width, height, style.feature_size_mm)
    elif shape == "tab":
        polygon = _tab(width, height, style.feature_size_mm)
    elif shape == "chamfer":
        polygon = _chamfer(width, height, style.feature_size_mm)
    elif shape == "hexagon":
        polygon = _hexagon(width, height, style.feature_size_mm)
    else:
        raise ValueError("Unsupported shape: {}".format(shape))

    return _reverse_x(polygon) if style.direction == "left" and shape in ("pointer", "flag") else polygon


def _signed_area(polygon: Polygon) -> float:
    return sum(
        point.x * polygon[(index + 1) % len(polygon)].y
        - polygon[(index + 1) % len(polygon)].x * point.y
        for index, point in enumerate(polygon)
    ) / 2.0


def _line_intersection(a1: Point, a2: Point, b1: Point, b2: Point) -> Optional[Point]:
    a_dx, a_dy = a2.x - a1.x, a2.y - a1.y
    b_dx, b_dy = b2.x - b1.x, b2.y - b1.y
    determinant = a_dx * b_dy - a_dy * b_dx
    if abs(determinant) < 1e-12:
        return None
    offset_x, offset_y = b1.x - a1.x, b1.y - a1.y
    factor = (offset_x * b_dy - offset_y * b_dx) / determinant
    return Point(a1.x + factor * a_dx, a1.y + factor * a_dy)


def inset_polygon(polygon: Polygon, distance: float) -> Polygon:
    """Inset a simple contour using mitred intersections of shifted edges."""
    if distance <= 0:
        return polygon
    if len(polygon) < 3:
        return ()

    orientation = 1.0 if _signed_area(polygon) > 0 else -1.0
    shifted_edges = []
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        dx, dy = end.x - start.x, end.y - start.y
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            continue
        normal_x = orientation * (-dy / length) * distance
        normal_y = orientation * (dx / length) * distance
        shifted_edges.append(
            (Point(start.x + normal_x, start.y + normal_y), Point(end.x + normal_x, end.y + normal_y))
        )
    if len(shifted_edges) < 3:
        return ()

    result = []
    for index, current in enumerate(shifted_edges):
        previous = shifted_edges[index - 1]
        intersection = _line_intersection(previous[0], previous[1], current[0], current[1])
        if intersection is None:
            intersection = current[0]
        result.append(intersection)

    inset = tuple(result)
    if abs(_signed_area(inset)) < 1e-9:
        return ()
    minimum, maximum = polygon_bounds((inset,))
    if maximum.x <= minimum.x or maximum.y <= minimum.y:
        return ()
    return inset


def render_shape(shape_object: ShapeObject, style: ShapeStyle, content_size: Size = Size()) -> ShapeGeometry:
    """Render one shape around measured content without any KiCad dependency."""
    padded = content_box(content_size, style)
    outer_size = Size(
        max(shape_object.size.width, padded.size.width),
        max(shape_object.size.height, padded.size.height),
    )
    if shape_object.shape == "circle":
        diameter = max(outer_size.width, outer_size.height)
        outer_size = Size(diameter, diameter)
    # Outline strokes are centred on their path. Reserve a full border width
    # on every side so the inner stroke edge respects the chosen text padding
    # rather than creeping into the artwork as the border grows.
    if not style.filled and (content_size.width > 0.0 or content_size.height > 0.0):
        border = style.border_thickness_mm
        outer_size = Size(
            outer_size.width + 2.0 * border,
            outer_size.height + 2.0 * border,
        )
    if outer_size.width <= 0 or outer_size.height <= 0:
        raise ValueError("A shape needs an explicit size or non-empty measured content")

    outer = shape_contour(shape_object.shape, outer_size, style)
    holes: Tuple[Polygon, ...] = ()
    if not style.filled:
        maximum_border = min(outer_size.width, outer_size.height) / 2.0
        border = min(style.border_thickness_mm, maximum_border)
        inner = inset_polygon(outer, border)
        if inner:
            holes = (inner,)

    return ShapeGeometry(
        regions=(PolygonRegion(outer=outer, holes=holes),),
        outer_size=outer_size,
        content_box=padded,
        content_polarity="knockout" if style.inverted else "positive",
    )


def _transform_point(point: Point, rotation_deg: float, translation: Point, bottom: bool) -> Point:
    angle = math.radians(rotation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    x = point.x * cosine - point.y * sine + translation.x
    y = point.x * sine + point.y * cosine + translation.y
    return Point(-x if bottom else x, y)


def transform_geometry(
    geometry: ShapeGeometry,
    output_layer: str,
    rotation_deg: float = 0.0,
    translation: Point = Point(),
) -> ShapeGeometry:
    """Apply local placement and the single front-view bottom mirror."""
    bottom = is_bottom(output_layer)

    def transform(polygon: Polygon) -> Polygon:
        return tuple(_transform_point(point, rotation_deg, translation, bottom) for point in polygon)

    return ShapeGeometry(
        regions=tuple(
            PolygonRegion(outer=transform(region.outer), holes=tuple(transform(hole) for hole in region.holes))
            for region in geometry.regions
        ),
        outer_size=geometry.outer_size,
        content_box=ContentBox(
            size=geometry.content_box.size,
            centre=_transform_point(geometry.content_box.centre, rotation_deg, translation, bottom),
        ),
        content_polarity=geometry.content_polarity,
    )


def render_document_shapes(
    document: CompositionDocument,
    content_sizes: Optional[Mapping[str, Size]] = None,
) -> Tuple[RenderedShape, ...]:
    """Render all shape objects in a document using supplied content sizes."""
    measured: Mapping[str, Size] = content_sizes or {}
    rendered = []
    for item in document.objects:
        if not isinstance(item, ShapeObject):
            continue
        geometry = render_shape(item, document.style.shape, measured.get(item.object_id, Size()))
        placement = Point(document.origin.x + item.position.x, document.origin.y + item.position.y)
        geometry = transform_geometry(
            geometry,
            output_layer=document.output_layer,
            rotation_deg=document.rotation_deg + item.rotation_deg,
            translation=placement,
        )
        rendered.append(RenderedShape(item.object_id, geometry))
    return tuple(rendered)

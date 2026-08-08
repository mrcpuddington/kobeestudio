"""Shared vector artwork renderer for Silk Studio labels and header blocks."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

from .composition import (
    CompositionDocument,
    DocumentStyle,
    GroupObject,
    GuideObject,
    IconObject,
    Point,
    ShapeObject,
    ShapeStyle,
    Size,
    TextObject,
    TypographyStyle,
)
from .component_callout import ComponentCalloutSpec
from .icon_catalog import render_builtin_icon
from .machine_codes import render_machine_code
from .pin_header import HeaderLayout, PinHeaderSpec, layout_pin_header
from .shape_geometry import (
    Polygon,
    inset_polygon,
    polygon_bounds,
    render_shape,
    shape_contour,
)
from .transforms import SUPPORTED_OUTPUT_LAYERS, is_bottom


@dataclass(frozen=True)
class StrokePath:
    points: Polygon
    width_mm: float


@dataclass(frozen=True)
class TextVectors:
    polygons: Tuple[Polygon, ...]
    size: Size


@dataclass(frozen=True)
class StudioArtwork:
    filled_polygons: Tuple[Polygon, ...]
    strokes: Tuple[StrokePath, ...]
    guides: Tuple[Polygon, ...]
    document: CompositionDocument
    header: Optional[PinHeaderSpec] = None
    component_callout: Optional[ComponentCalloutSpec] = None

    @property
    def all_exported_polygons(self) -> Tuple[Polygon, ...]:
        return self.filled_polygons + tuple(stroke.points for stroke in self.strokes)


class TextVectorizer:
    """Convert the mature bundled font renderer into millimetre polygons."""

    def __init__(self, buzzard) -> None:
        self.buzzard = buzzard
        self._cache = {}
        self._normalised_cache = {}

    def render(
        self,
        text: str,
        typography: TypographyStyle,
        inline_format: bool = False,
        lineover_style: str = "Rounded",
        lineover_thickness: int = 1,
    ) -> TextVectors:
        if not text:
            return TextVectors((), Size())

        cache_key = (
            text,
            typography,
            bool(inline_format),
            lineover_style,
            max(1, int(lineover_thickness)),
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Font height changes are common spinner edits.  The outline itself is
        # scale-independent, so preserve a unit-height version and avoid
        # invoking the SVG/font pipeline again for every tick of that spinner.
        normalised_key = (
            text,
            typography.font_name,
            typography.width_mm,
            typography.line_spacing,
            typography.alignment,
            bool(inline_format),
            lineover_style,
            max(1, int(lineover_thickness)),
        )
        normalised = self._normalised_cache.get(normalised_key)
        if normalised is not None:
            result = self._scale_vectors(normalised, typography.height_mm)
            self._remember(cache_key, result)
            return result

        buzzard = self.buzzard
        buzzard.fontName = typography.font_name
        buzzard.lineSpacing = typography.line_spacing * 10.0
        buzzard.alignment = typography.alignment.title()
        buzzard.leftCap = ""
        buzzard.rightCap = ""
        buzzard.width = 0.0
        buzzard.inlineFormat = bool(inline_format)
        buzzard.lineOverStyle = lineover_style
        buzzard.lineOverThickness = max(1, int(lineover_thickness))
        for name in ("top", "right", "bottom", "left"):
            setattr(buzzard.padding, name, 0.001)

        natural_height = buzzard.text_height()
        if natural_height <= 0:
            raise ValueError("Selected font has no measurable capital height")
        buzzard.scaleFactor = (typography.height_mm / natural_height) * (96.0 / 25.4)
        raw_polygons = buzzard.generate(text)
        # ``Buzzard.generate`` returns points that Svg2Points has already
        # converted from 96-DPI SVG units to millimetres.  ``scaleFactor`` is
        # therefore the only remaining multiplier.  Applying 25.4 / 96 here
        # again made every Studio glyph 0.2646x its requested physical height.
        mm_per_unit = buzzard.scaleFactor
        polygons = tuple(
            tuple(Point(float(point.x) * mm_per_unit, float(point.y) * mm_per_unit) for point in polygon)
            for polygon in raw_polygons
            if len(polygon) >= 3
        )
        if not polygons:
            result = TextVectors((), Size())
            self._remember(cache_key, result)
            return result

        minimum, maximum = polygon_bounds(polygons)
        centre = Point((minimum.x + maximum.x) / 2.0, (minimum.y + maximum.y) / 2.0)
        centred = tuple(_translate_polygon(polygon, Point(-centre.x, -centre.y)) for polygon in polygons)
        result = TextVectors(centred, Size(maximum.x - minimum.x, maximum.y - minimum.y))
        self._remember(cache_key, result)
        if typography.height_mm > 0:
            self._remember_normalised(
                normalised_key,
                self._scale_vectors(result, 1.0 / typography.height_mm),
            )
        return result

    def _remember(self, key, value: TextVectors) -> None:
        """Keep recent immutable outlines without retaining unbounded text."""
        if len(self._cache) >= 64:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = value

    def _remember_normalised(self, key, value: TextVectors) -> None:
        if len(self._normalised_cache) >= 64:
            self._normalised_cache.pop(next(iter(self._normalised_cache)))
        self._normalised_cache[key] = value

    @staticmethod
    def _scale_vectors(vectors: TextVectors, factor: float) -> TextVectors:
        return TextVectors(
            tuple(
                tuple(Point(point.x * factor, point.y * factor) for point in polygon)
                for polygon in vectors.polygons
            ),
            Size(vectors.size.width * factor, vectors.size.height * factor),
        )


def _translate_polygon(polygon: Polygon, offset: Point) -> Polygon:
    return tuple(Point(point.x + offset.x, point.y + offset.y) for point in polygon)


def _clip_polygon_below_y(polygon: Polygon, minimum_y: float) -> Polygon:
    """Clip a polygon to the half-plane at or below ``minimum_y``."""
    if len(polygon) < 3:
        return ()

    def intersection(start: Point, end: Point) -> Point:
        if abs(end.y - start.y) <= 1e-12:
            return Point(end.x, minimum_y)
        ratio = (minimum_y - start.y) / (end.y - start.y)
        return Point(start.x + ratio * (end.x - start.x), minimum_y)

    result = []
    previous = polygon[-1]
    previous_inside = previous.y >= minimum_y
    for current in polygon:
        current_inside = current.y >= minimum_y
        if current_inside != previous_inside:
            result.append(intersection(previous, current))
        if current_inside:
            result.append(current)
        previous = current
        previous_inside = current_inside
    return tuple(result)


def _place_polygon(polygon: Polygon, offset: Point, rotation_deg: float = 0.0) -> Polygon:
    if rotation_deg == 0.0:
        return _translate_polygon(polygon, offset)
    angle = math.radians(rotation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    return tuple(
        Point(
            point.x * cosine - point.y * sine + offset.x,
            point.x * sine + point.y * cosine + offset.y,
        )
        for point in polygon
    )


def _signed_area(polygon: Polygon) -> float:
    return sum(
        point.x * polygon[(index + 1) % len(polygon)].y
        - polygon[(index + 1) % len(polygon)].x * point.y
        for index, point in enumerate(polygon)
    ) / 2.0


def _edge_x_at_y(start: Point, end: Point, y: float) -> float:
    return start.x + (y - start.y) * (end.x - start.x) / (end.y - start.y)


def _knockout_tiles(outer: Polygon, holes: Iterable[Polygon]) -> Tuple[Polygon, ...]:
    """Decompose an even-odd polygon into compact, simple y-monotone regions.

    Each scanline span is simple and reliable in KiCad, but emitting every
    span as a separate trapezoid can turn a detailed icon into thousands of
    footprint polygons.  Adjacent spans bounded by the same source edges are
    merged here.  The result keeps the stable, non-self-intersecting geometry
    while reducing complex polarity labels from megabytes to a practical size.
    """
    rings = tuple(ring for ring in (outer,) + tuple(holes) if len(ring) >= 3)
    levels = sorted({point.y for ring in rings for point in ring})
    epsilon = 1e-10
    active = {}
    regions = []

    # Keep the same source-order pairing used by the reference scanline
    # implementation, but visit only edges crossing the current band.  Some
    # glyph contours have near-identical adjacent Y values, so edge events are
    # processed even for bands we subsequently skip as degenerate.
    edge_starts = {}
    edge_ends = {}
    for ring_index, ring in enumerate(rings):
        for edge_index, start in enumerate(ring):
            end = ring[(edge_index + 1) % len(ring)]
            if end.y == start.y:
                continue
            low, high = sorted((start.y, end.y))
            edge = (ring_index, edge_index, start, end)
            edge_starts.setdefault(low, []).append(edge)
            edge_ends.setdefault(high, []).append(edge)
    sweep_edges = {}

    def append_edge_point(points, point):
        if points and abs(points[-1].x - point.x) <= epsilon and abs(points[-1].y - point.y) <= epsilon:
            return
        if len(points) >= 2:
            first, second = points[-2], points[-1]
            cross = ((second.x - first.x) * (point.y - second.y)
                     - (second.y - first.y) * (point.x - second.x))
            if abs(cross) <= epsilon:
                points[-1] = point
                return
        points.append(point)

    def finish(strip):
        boundary = tuple(strip["left"] + list(reversed(strip["right"])))
        if len(boundary) >= 3 and abs(_signed_area(boundary)) > epsilon:
            regions.append(boundary)

    for y0, y1 in zip(levels, levels[1:]):
        for edge in edge_ends.get(y0, ()):
            sweep_edges.pop((edge[0], edge[1]), None)
        for edge in edge_starts.get(y0, ()):
            sweep_edges[(edge[0], edge[1])] = edge
        if y1 - y0 <= epsilon:
            continue
        middle_y = (y0 + y1) / 2.0
        crossings = []
        for ring_index, edge_index, start, end in sweep_edges.values():
            crossings.append(
                (
                    _edge_x_at_y(start, end, middle_y),
                    _edge_x_at_y(start, end, y0),
                    _edge_x_at_y(start, end, y1),
                    (ring_index, edge_index),
                )
            )
        crossings.sort(key=lambda item: item[0])
        next_active = {}
        inside_outer = False
        active_holes = set()
        span_left = None

        # The outer ring uses even/odd membership, while every content ring is
        # part of one combined knockout.  Treating all rings as a single
        # even/odd path made overlapping icon components cancel each other,
        # leaving diamonds and wedges inside inverted symbols.
        for crossing in crossings:
            was_filled = inside_outer and not active_holes
            ring_index = crossing[3][0]
            if ring_index == 0:
                inside_outer = not inside_outer
            elif ring_index in active_holes:
                active_holes.remove(ring_index)
            else:
                active_holes.add(ring_index)
            is_filled = inside_outer and not active_holes

            if not was_filled and is_filled:
                span_left = crossing
                continue
            if not (was_filled and not is_filled and span_left is not None):
                continue

            left, right = span_left, crossing
            span_left = None
            if right[0] - left[0] <= epsilon:
                continue
            key = (left[3], right[3])
            strip = active.pop(key, None)
            if strip is None or abs(strip["end_y"] - y0) > epsilon:
                if strip is not None:
                    finish(strip)
                strip = {
                    "left": [Point(left[1], y0)],
                    "right": [Point(right[1], y0)],
                    "end_y": y0,
                }
            append_edge_point(strip["left"], Point(left[2], y1))
            append_edge_point(strip["right"], Point(right[2], y1))
            strip["end_y"] = y1
            next_active[key] = strip
        for strip in active.values():
            finish(strip)
        active = next_active

    for strip in active.values():
        finish(strip)
    return tuple(regions)


def _point_in_polygon(point: Point, polygon: Polygon) -> bool:
    inside = False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if (start.y > point.y) == (end.y > point.y):
            continue
        crossing_x = start.x + (point.y - start.y) * (end.x - start.x) / (end.y - start.y)
        if crossing_x > point.x:
            inside = not inside
    return inside


def _bridge_holes(outer: Polygon, holes: Sequence[Polygon]) -> Polygon:
    """Join direct child holes to a boundary with non-crossing right rays."""
    boundary = list(outer if _signed_area(outer) > 0 else tuple(reversed(outer)))
    ordered_holes = sorted(
        holes,
        key=lambda ring: max(point.x for point in ring),
        reverse=True,
    )
    epsilon = 1e-9
    for raw_hole in ordered_holes:
        hole = raw_hole if _signed_area(raw_hole) < 0 else tuple(reversed(raw_hole))
        hole_index = max(range(len(hole)), key=lambda index: (hole[index].x, -hole[index].y))
        anchor = hole[hole_index]
        candidates = []
        for index, start in enumerate(boundary):
            end = boundary[(index + 1) % len(boundary)]
            if start.y == end.y:
                continue
            low, high = sorted((start.y, end.y))
            if not (low <= anchor.y < high):
                continue
            crossing_x = _edge_x_at_y(start, end, anchor.y)
            if crossing_x + epsilon >= anchor.x:
                candidates.append((crossing_x, index))
        if not candidates:
            # A valid enclosed hole always has a boundary crossing to its
            # right.  Keep the scanline decomposition as a safe last resort.
            raise ValueError("Could not bridge an enclosed knockout contour")
        crossing_x, edge_index = min(candidates, key=lambda item: item[0])
        bridge = Point(crossing_x, anchor.y)
        cycle = [hole[(hole_index + offset) % len(hole)] for offset in range(len(hole))]
        prefix = boundary[: edge_index + 1]
        suffix = boundary[edge_index + 1 :]
        if not prefix or prefix[-1] != bridge:
            prefix.append(bridge)
        boundary = prefix + cycle + [anchor, bridge] + suffix
    return tuple(boundary)


def _knockout_regions(outer: Polygon, holes: Iterable[Polygon]) -> Tuple[Polygon, ...]:
    """Return simple KiCad polygons for an inverted shape.

    KiCad's accelerated canvas does not consistently paint the weakly-simple
    bridge paths that are otherwise valid in a footprint polygon.  This was
    particularly visible with icons plus the compact FreddySpark glyphs:
    letters appeared to join or disappear while editing.  The scanline tiles
    are ordinary non-self-intersecting polygons, so they are a little more
    numerous but render identically and reliably in both canvas backends.
    """
    return _knockout_tiles(outer, holes)


def _legacy_knockout_regions(outer: Polygon, holes: Iterable[Polygon]) -> Tuple[Polygon, ...]:
    """Build compact weakly-simple KiCad polygons using even-odd nesting.

    Retained as a reference implementation for the nested-contour algorithm;
    live artwork uses the stable simple-tile representation above.
    """
    contours = tuple(
        ring
        for ring in holes
        if len(ring) >= 3 and _point_in_polygon(ring[0], outer)
    )
    parents = []
    for index, ring in enumerate(contours):
        containers = [
            candidate
            for candidate, other in enumerate(contours)
            if candidate != index
            and abs(_signed_area(other)) > abs(_signed_area(ring))
            and _point_in_polygon(ring[0], other)
        ]
        parents.append(
            min(containers, key=lambda candidate: abs(_signed_area(contours[candidate])))
            if containers
            else None
        )
    children = {None: []}
    for index, parent in enumerate(parents):
        children.setdefault(parent, []).append(index)
        children.setdefault(index, [])

    regions = []

    def add_filled_region(boundary: Polygon, child_holes: Sequence[int]) -> None:
        regions.append(_bridge_holes(boundary, tuple(contours[index] for index in child_holes)))
        for hole_index in child_holes:
            for island_index in children[hole_index]:
                add_filled_region(contours[island_index], children[island_index])

    try:
        add_filled_region(outer, children[None])
        return tuple(regions)
    except ValueError:
        return _knockout_tiles(outer, contours)


def _content_offset(outer_size: Size, content_size: Size, style: DocumentStyle) -> Point:
    padding = style.shape.padding
    left = -outer_size.width / 2.0 + padding.left
    right = outer_size.width / 2.0 - padding.right
    top = -outer_size.height / 2.0 + padding.top
    bottom = outer_size.height / 2.0 - padding.bottom
    alignment = style.typography.alignment
    if alignment == "left":
        x = left + content_size.width / 2.0
    elif alignment == "right":
        x = right - content_size.width / 2.0
    else:
        x = (left + right) / 2.0
    return Point(x, (top + bottom) / 2.0)


def _shape_layers(
    outer: Polygon,
    text_polygons: Sequence[Polygon],
    style: DocumentStyle,
    knockout_polygons: Sequence[Polygon] = (),
) -> Tuple[Tuple[Polygon, ...], Tuple[StrokePath, ...]]:
    shape_style = style.shape
    if shape_style.filled:
        if shape_style.inverted:
            return (
                _knockout_regions(outer, tuple(text_polygons) + tuple(knockout_polygons)),
                (),
            )
        return ((outer,) + tuple(text_polygons), ())

    contour = inset_polygon(outer, shape_style.border_thickness_mm / 2.0)
    strokes = (StrokePath(contour or outer, shape_style.border_thickness_mm),)
    return (tuple(text_polygons), strokes)


def render_label_artwork(
    vectorizer: TextVectorizer,
    text: str,
    style: DocumentStyle,
    output_layer: str,
    shape: Optional[str] = None,
    minimum_width_mm: float = 0.0,
    inline_format: bool = False,
    lineover_style: str = "Rounded",
    lineover_thickness: int = 1,
    icon_id: str = "",
    icon_position: str = "left",
    icon_height_mm: float = 0.0,
    icon_gap_mm: float = 0.3,
    subtitle_text: str = "",
    subtitle_typography: Optional[TypographyStyle] = None,
    subtitle_gap_mm: float = 0.25,
    underline: bool = False,
    underline_thickness_mm: float = 0.15,
    underline_gap_mm: float = 0.12,
) -> StudioArtwork:
    if icon_position not in ("left", "right", "only"):
        raise ValueError("Unsupported icon position: {}".format(icon_position))
    if icon_height_mm < 0:
        raise ValueError("Icon height must be non-negative")
    if icon_gap_mm < 0:
        raise ValueError("Icon gap must be non-negative")
    if subtitle_gap_mm < 0:
        raise ValueError("Subtitle gap must be non-negative")
    if underline_thickness_mm <= 0:
        raise ValueError("Underline thickness must be greater than zero")
    if underline_gap_mm < 0:
        raise ValueError("Underline gap must be non-negative")

    has_icon = bool(icon_id)
    has_text = bool(text or subtitle_text) and icon_position != "only"
    if not has_text and not has_icon:
        raise ValueError("A label needs text or an icon")

    vectors = vectorizer.render(
        text if has_text else "",
        style.typography,
        inline_format,
        lineover_style,
        lineover_thickness,
    )
    secondary_typography = subtitle_typography or TypographyStyle(
        font_name=style.typography.font_name,
        height_mm=max(0.01, style.typography.height_mm * 0.65),
        width_mm=0.0,
        line_spacing=style.typography.line_spacing,
        alignment=style.typography.alignment,
    )
    subtitle_vectors = vectorizer.render(
        subtitle_text if has_text else "",
        secondary_typography,
        False,
        lineover_style,
        lineover_thickness,
    )
    has_primary = bool(vectors.polygons)
    has_subtitle = bool(subtitle_vectors.polygons)
    has_underline = bool(underline and has_primary)
    underline_extra = underline_gap_mm + underline_thickness_mm if has_underline else 0.0
    primary_block_height = vectors.size.height + underline_extra
    text_gap = subtitle_gap_mm if has_primary and has_subtitle else 0.0
    text_stack_size = Size(
        max(vectors.size.width, subtitle_vectors.size.width),
        primary_block_height + subtitle_vectors.size.height + text_gap,
    )

    def line_x(line_width: float) -> float:
        if style.typography.alignment == "left":
            return -text_stack_size.width / 2.0 + line_width / 2.0
        if style.typography.alignment == "right":
            return text_stack_size.width / 2.0 - line_width / 2.0
        return 0.0

    primary_block_centre_y = 0.0
    if has_primary and has_subtitle:
        primary_block_centre_y = -text_stack_size.height / 2.0 + primary_block_height / 2.0
    primary_in_stack = Point(
        line_x(vectors.size.width),
        primary_block_centre_y - underline_extra / 2.0,
    )
    subtitle_in_stack = Point(line_x(subtitle_vectors.size.width), 0.0)
    if has_primary and has_subtitle:
        subtitle_in_stack = Point(
            subtitle_in_stack.x,
            text_stack_size.height / 2.0 - subtitle_vectors.size.height / 2.0,
        )
    underline_in_stack = Point(
        line_x(vectors.size.width),
        primary_block_centre_y + (vectors.size.height + underline_gap_mm) / 2.0,
    )
    icon = (
        render_builtin_icon(icon_id, icon_height_mm or style.typography.height_mm)
        if has_icon
        else None
    )
    gap = icon_gap_mm if has_text and icon is not None else 0.0
    content_size = Size(
        text_stack_size.width + (icon.size.width if icon else 0.0) + gap,
        max(text_stack_size.height, icon.size.height if icon else 0.0),
    )

    text_stack_centre = Point()
    icon_centre = Point()
    if has_text and icon is not None:
        if icon_position == "left":
            icon_centre = Point(-content_size.width / 2.0 + icon.size.width / 2.0, 0.0)
            text_stack_centre = Point(
                content_size.width / 2.0 - text_stack_size.width / 2.0, 0.0
            )
        else:
            text_stack_centre = Point(
                -content_size.width / 2.0 + text_stack_size.width / 2.0, 0.0
            )
            icon_centre = Point(content_size.width / 2.0 - icon.size.width / 2.0, 0.0)

    text_centre = Point(
        text_stack_centre.x + primary_in_stack.x,
        text_stack_centre.y + primary_in_stack.y,
    )
    subtitle_centre = Point(
        text_stack_centre.x + subtitle_in_stack.x,
        text_stack_centre.y + subtitle_in_stack.y,
    )
    underline_centre = Point(
        text_stack_centre.x + underline_in_stack.x,
        text_stack_centre.y + underline_in_stack.y,
    )
    placed_text = tuple(_translate_polygon(polygon, text_centre) for polygon in vectors.polygons)
    placed_subtitle = tuple(
        _translate_polygon(polygon, subtitle_centre) for polygon in subtitle_vectors.polygons
    )
    placed_icon = tuple(
        _translate_polygon(polygon, icon_centre) for polygon in (icon.polygons if icon else ())
    )
    placed_underline = (
        (
            Point(underline_centre.x - vectors.size.width / 2.0, underline_centre.y - underline_thickness_mm / 2.0),
            Point(underline_centre.x + vectors.size.width / 2.0, underline_centre.y - underline_thickness_mm / 2.0),
            Point(underline_centre.x + vectors.size.width / 2.0, underline_centre.y + underline_thickness_mm / 2.0),
            Point(underline_centre.x - vectors.size.width / 2.0, underline_centre.y + underline_thickness_mm / 2.0),
        ),
    ) if has_underline else ()
    content_polygons = placed_text + placed_subtitle + placed_icon + placed_underline
    if content_polygons:
        content_minimum, content_maximum = polygon_bounds(content_polygons)
        normalise = Point(
            -(content_minimum.x + content_maximum.x) / 2.0,
            -(content_minimum.y + content_maximum.y) / 2.0,
        )
        text_centre = Point(text_centre.x + normalise.x, text_centre.y + normalise.y)
        subtitle_centre = Point(
            subtitle_centre.x + normalise.x, subtitle_centre.y + normalise.y
        )
        icon_centre = Point(icon_centre.x + normalise.x, icon_centre.y + normalise.y)
        underline_centre = Point(underline_centre.x + normalise.x, underline_centre.y + normalise.y)
        content_polygons = tuple(
            _translate_polygon(polygon, normalise) for polygon in content_polygons
        )
        content_size = Size(
            content_maximum.x - content_minimum.x,
            content_maximum.y - content_minimum.y,
        )

    # Alignment is applied to this measured icon-plus-text assembly.  Building
    # the objects after normalisation prevents an icon's nominal canvas or
    # asymmetric source bounds from leaving the text centred on its own.
    objects = []
    if has_primary:
        objects.append(TextObject("text.primary", text, position=text_centre))
    if has_subtitle:
        objects.append(
            TextObject(
                "text.secondary",
                subtitle_text,
                position=subtitle_centre,
                style_role="secondary",
            )
        )
    if has_underline:
        objects.append(
            ShapeObject(
                "text.underline",
                shape="rectangle",
                position=underline_centre,
                size=Size(vectors.size.width, underline_thickness_mm),
            )
        )
    if icon is not None:
        objects.append(
            IconObject(
                "icon.primary",
                icon_id,
                position=icon_centre,
                size=icon.size,
            )
        )

    if shape is None:
        if len(objects) > 1:
            objects.append(GroupObject("group.label", tuple(item.object_id for item in objects)))
        artwork_style = DocumentStyle(
            typography=style.typography,
            shape=style.shape,
            secondary_typography=secondary_typography if has_subtitle else None,
        )
        document = CompositionDocument(
            objects=tuple(objects),
            output_layer=output_layer,
            size=content_size,
            alignment=style.typography.alignment,
            style=artwork_style,
        )
        return StudioArtwork(content_polygons, (), (), document)

    shape_object = ShapeObject(
        "shape.background",
        shape=shape,
        size=Size(max(0.0, minimum_width_mm), 0.0),
        content_ids=tuple(item.object_id for item in objects),
    )
    geometry = render_shape(shape_object, style.shape, content_size)
    offset = _content_offset(geometry.outer_size, content_size, style)
    content_polygons = tuple(_translate_polygon(polygon, offset) for polygon in content_polygons)
    filled, strokes = _shape_layers(geometry.regions[0].outer, content_polygons, style)
    placed_objects_list = []
    for item in objects:
        position = Point(item.position.x + offset.x, item.position.y + offset.y)
        if isinstance(item, TextObject):
            placed_objects_list.append(
                TextObject(
                    item.object_id,
                    item.text,
                    position=position,
                    rotation_deg=item.rotation_deg,
                    style_role=item.style_role,
                )
            )
        elif isinstance(item, IconObject):
            placed_objects_list.append(
                IconObject(
                    item.object_id,
                    item.asset_id,
                    position=position,
                    size=item.size,
                    rotation_deg=item.rotation_deg,
                )
            )
        else:
            placed_objects_list.append(
                ShapeObject(
                    item.object_id,
                    shape=item.shape,
                    position=position,
                    size=item.size,
                    rotation_deg=item.rotation_deg,
                    content_ids=item.content_ids,
                )
            )
    placed_objects = tuple(placed_objects_list)
    shape_object = ShapeObject(
        shape_object.object_id,
        shape=shape,
        size=geometry.outer_size,
        content_ids=tuple(item.object_id for item in placed_objects),
    )
    group = GroupObject(
        "group.label",
        (shape_object.object_id,) + tuple(item.object_id for item in placed_objects),
    )
    artwork_style = DocumentStyle(
        typography=style.typography,
        shape=style.shape,
        secondary_typography=secondary_typography if has_subtitle else None,
    )
    document = CompositionDocument(
        objects=placed_objects + (shape_object, group),
        output_layer=output_layer,
        size=geometry.outer_size,
        alignment=style.typography.alignment,
        style=artwork_style,
    )
    return StudioArtwork(filled, strokes, (), document)


def _component_cutout_contour(spec: ComponentCalloutSpec) -> Polygon:
    """Return the physical keep-clear contour for one component."""
    cutout_size = Size(spec.cutout_width_mm, spec.cutout_height_mm)
    if spec.cutout_shape != "tactile_switch":
        style = ShapeStyle(
            corner_radius_mm=spec.cutout_radius_mm,
            filled=True,
            inverted=False,
        )
        return shape_contour(spec.cutout_shape, cutout_size, style)

    # A 6 × 6 mm tactile switch has a square body and two terminals on each
    # side. This stepped outline includes those four terminal wings while
    # keeping the unused side areas available for artwork.
    half_width = cutout_size.width / 2.0
    half_height = cutout_size.height / 2.0
    body_half_width = min(
        half_width,
        (min(spec.component_width_mm, 6.0) + 2.0 * spec.component_clearance_mm) / 2.0,
    )
    corner = min(
        spec.cutout_radius_mm,
        half_height * 0.25,
        body_half_width * 0.25,
    )
    pin_half_height = min(0.8, half_height * 0.18)
    pin_centre = min(half_height - pin_half_height - corner, half_height * 0.56)
    return (
        Point(-body_half_width + corner, -half_height),
        Point(body_half_width - corner, -half_height),
        Point(body_half_width, -half_height + corner),
        Point(body_half_width, -pin_centre - pin_half_height),
        Point(half_width, -pin_centre - pin_half_height),
        Point(half_width, -pin_centre + pin_half_height),
        Point(body_half_width, -pin_centre + pin_half_height),
        Point(body_half_width, pin_centre - pin_half_height),
        Point(half_width, pin_centre - pin_half_height),
        Point(half_width, pin_centre + pin_half_height),
        Point(body_half_width, pin_centre + pin_half_height),
        Point(body_half_width, half_height - corner),
        Point(body_half_width - corner, half_height),
        Point(-body_half_width + corner, half_height),
        Point(-body_half_width, half_height - corner),
        Point(-body_half_width, pin_centre + pin_half_height),
        Point(-half_width, pin_centre + pin_half_height),
        Point(-half_width, pin_centre - pin_half_height),
        Point(-body_half_width, pin_centre - pin_half_height),
        Point(-body_half_width, -pin_centre + pin_half_height),
        Point(-half_width, -pin_centre + pin_half_height),
        Point(-half_width, -pin_centre - pin_half_height),
        Point(-body_half_width, -pin_centre - pin_half_height),
        Point(-body_half_width, -half_height + corner),
    )


def render_component_callout_artwork(
    vectorizer: TextVectorizer,
    spec: ComponentCalloutSpec,
    icon_id: str = "",
    icon_position: str = "left",
    icon_height_mm: float = 0.0,
    icon_gap_mm: float = 0.3,
) -> StudioArtwork:
    """Render one component callout or a regularly spaced component array."""
    labels = tuple(spec.title.splitlines()) if spec.array_count > 1 else (spec.title,)
    text_artworks = tuple(
        render_label_artwork(
            vectorizer,
            label,
            spec.style,
            spec.output_layer,
            shape=None,
            icon_id=icon_id,
            icon_position=icon_position,
            icon_height_mm=icon_height_mm,
            icon_gap_mm=icon_gap_mm,
            subtitle_text=spec.subtitle if spec.array_count == 1 else "",
            subtitle_typography=spec.style.secondary_typography,
            subtitle_gap_mm=spec.subtitle_gap_mm,
        )
        for label in labels
    )
    max_text_size = Size(
        max(item.document.size.width for item in text_artworks),
        max(item.document.size.height for item in text_artworks),
    )
    cutout_size = Size(spec.cutout_width_mm, spec.cutout_height_mm)
    component_beside_text = spec.component_position in ("left", "right")
    cell_size = Size(
        cutout_size.width + spec.component_to_text_gap_mm + max_text_size.width
        if component_beside_text
        else max(cutout_size.width, max_text_size.width),
        max(cutout_size.height, max_text_size.height)
        if component_beside_text
        else cutout_size.height + spec.component_to_text_gap_mm + max_text_size.height,
    )
    if spec.array_count > 1:
        minimum_pitch = (
            cell_size.height if spec.array_orientation == "vertical" else cell_size.width
        )
        if spec.array_pitch_mm + 1e-9 < minimum_pitch:
            raise ValueError(
                "Component spacing must be at least {:.2f} mm for the current cutout and text".format(
                    minimum_pitch
                )
            )
    content_size = Size(
        cell_size.width
        if spec.array_orientation == "vertical"
        else cell_size.width + (spec.array_count - 1) * spec.array_pitch_mm,
        cell_size.height + (spec.array_count - 1) * spec.array_pitch_mm
        if spec.array_orientation == "vertical"
        else cell_size.height,
    )

    def aligned_text_x(text_width: float, slot_centre: float, slot_width: float) -> float:
        alignment = spec.style.typography.alignment
        if alignment == "left":
            return slot_centre - slot_width / 2.0 + text_width / 2.0
        if alignment == "right":
            return slot_centre + slot_width / 2.0 - text_width / 2.0
        return slot_centre

    component_centres = []
    text_centres = []
    for index, artwork in enumerate(text_artworks):
        axis_offset = (index - (spec.array_count - 1) / 2.0) * spec.array_pitch_mm
        cell_centre = (
            Point(0.0, axis_offset)
            if spec.array_orientation == "vertical"
            else Point(axis_offset, 0.0)
        )
        text_size = artwork.document.size
        if spec.component_position == "left":
            component = Point(-cell_size.width / 2.0 + cutout_size.width / 2.0, 0.0)
            slot_centre = cell_size.width / 2.0 - max_text_size.width / 2.0
            text = Point(aligned_text_x(text_size.width, slot_centre, max_text_size.width), 0.0)
        elif spec.component_position == "right":
            component = Point(cell_size.width / 2.0 - cutout_size.width / 2.0, 0.0)
            slot_centre = -cell_size.width / 2.0 + max_text_size.width / 2.0
            text = Point(aligned_text_x(text_size.width, slot_centre, max_text_size.width), 0.0)
        elif spec.component_position == "above":
            component = Point(0.0, -cell_size.height / 2.0 + cutout_size.height / 2.0)
            text = Point(
                aligned_text_x(text_size.width, 0.0, cell_size.width),
                cell_size.height / 2.0 - text_size.height / 2.0,
            )
        else:
            component = Point(0.0, cell_size.height / 2.0 - cutout_size.height / 2.0)
            text = Point(
                aligned_text_x(text_size.width, 0.0, cell_size.width),
                -cell_size.height / 2.0 + text_size.height / 2.0,
            )
        component_centres.append(
            Point(component.x + cell_centre.x, component.y + cell_centre.y)
        )
        text_centres.append(Point(text.x + cell_centre.x, text.y + cell_centre.y))

    outer_object = ShapeObject(
        "shape.background",
        shape=spec.shape,
        size=Size(spec.minimum_width_mm, spec.minimum_height_mm),
    )
    outer_geometry = render_shape(outer_object, spec.style.shape, content_size)
    content_offset = _content_offset(outer_geometry.outer_size, content_size, spec.style)
    component_centres = [
        Point(item.x + content_offset.x, item.y + content_offset.y)
        for item in component_centres
    ]
    text_centres = [
        Point(item.x + content_offset.x, item.y + content_offset.y)
        for item in text_centres
    ]

    average_component = Point(
        sum(item.x for item in component_centres) / len(component_centres),
        sum(item.y for item in component_centres) / len(component_centres),
    )
    anchor_shift = Point(-average_component.x, -average_component.y)
    outer_centre = anchor_shift
    component_centres = [
        Point(item.x + anchor_shift.x, item.y + anchor_shift.y)
        for item in component_centres
    ]
    text_centres = [
        Point(item.x + anchor_shift.x, item.y + anchor_shift.y)
        for item in text_centres
    ]
    outer = _translate_polygon(outer_geometry.regions[0].outer, outer_centre)

    text_polygons = []
    cutouts = []
    placed_objects = []
    guide_objects = []
    base_cutout = _component_cutout_contour(spec)
    for index, (artwork, text_centre, component_centre) in enumerate(
        zip(text_artworks, text_centres, component_centres)
    ):
        text_polygons.extend(
            _translate_polygon(polygon, text_centre)
            for polygon in artwork.filled_polygons
        )
        cutout = _translate_polygon(base_cutout, component_centre)
        cutouts.append(cutout)
        suffix = "" if spec.array_count == 1 else ".{}".format(index + 1)
        for item in artwork.document.objects:
            if isinstance(item, TextObject):
                object_id = (
                    item.object_id if spec.array_count == 1 else "text.row{}".format(suffix)
                )
                placed_objects.append(
                    TextObject(
                        object_id,
                        item.text,
                        position=Point(
                            item.position.x + text_centre.x,
                            item.position.y + text_centre.y,
                        ),
                        rotation_deg=item.rotation_deg,
                        style_role=item.style_role,
                    )
                )
            elif isinstance(item, IconObject):
                object_id = (
                    item.object_id if spec.array_count == 1 else "icon.row{}".format(suffix)
                )
                placed_objects.append(
                    IconObject(
                        object_id,
                        item.asset_id,
                        position=Point(
                            item.position.x + text_centre.x,
                            item.position.y + text_centre.y,
                        ),
                        size=item.size,
                        rotation_deg=item.rotation_deg,
                    )
                )
        guide_objects.append(
            GuideObject(
                "component.safe-zone{}".format(suffix),
                guide_type=spec.cutout_shape,
                position=component_centre,
                size=cutout_size,
            )
        )

    text_polygons_tuple = tuple(text_polygons)
    cutouts_tuple = tuple(cutouts)
    if spec.style.shape.filled and not spec.style.shape.inverted:
        filled = _knockout_regions(outer, cutouts_tuple) + text_polygons_tuple
        strokes = ()
    else:
        filled, strokes = _shape_layers(
            outer,
            text_polygons_tuple,
            spec.style,
            cutouts_tuple,
        )

    content_ids = tuple(item.object_id for item in placed_objects)
    shape_object = ShapeObject(
        "shape.background",
        shape=spec.shape,
        position=outer_centre,
        size=outer_geometry.outer_size,
        content_ids=content_ids,
    )
    all_objects = tuple(placed_objects) + (shape_object,) + tuple(guide_objects)
    group = GroupObject(
        "group.component-array" if spec.array_count > 1 else "group.component-callout",
        tuple(item.object_id for item in all_objects),
    )
    document = CompositionDocument(
        objects=all_objects + (group,),
        output_layer=spec.output_layer,
        anchor=Point(),
        origin=outer_centre,
        size=outer_geometry.outer_size,
        alignment=spec.style.typography.alignment,
        style=text_artworks[0].document.style,
    )
    return StudioArtwork(
        filled_polygons=filled,
        strokes=strokes,
        guides=cutouts_tuple,
        document=document,
        component_callout=spec,
    )


def render_machine_code_artwork(
    payload: str,
    kind: str,
    module_size_mm: float,
    bar_height_mm: float,
    output_layer: str,
    vectorizer: Optional[TextVectorizer] = None,
    presentation: str = "plain",
    caption_text: str = "SCAN ME",
    caption_height_mm: float = 1.2,
    frame_padding_mm: float = 0.2,
    show_content_text: bool = False,
    content_text: str = "",
    content_height_mm: float = 0.9,
    content_gap_mm: float = 0.5,
) -> StudioArtwork:
    """Render a QR or linear barcode directly as fabrication polygons."""
    if output_layer not in SUPPORTED_OUTPUT_LAYERS:
        raise ValueError("Unsupported Kobee Studio output layer: {}".format(output_layer))
    if presentation not in ("plain", "rounded_frame", "rounded_caption"):
        raise ValueError("Unsupported machine-code presentation: {}".format(presentation))
    if kind != "qr" and presentation != "plain":
        raise ValueError("Rounded containers are currently available for QR Codes only")
    if frame_padding_mm < 0.0:
        raise ValueError("QR frame padding must be non-negative")
    if content_gap_mm < 0.0:
        raise ValueError("Machine-code text gap must be non-negative")
    if content_height_mm < 0.6:
        raise ValueError("Machine-code text must be at least 0.6 mm high")

    code = render_machine_code(kind, payload, module_size_mm, bar_height_mm)
    half_width = code.size.width / 2.0
    half_height = code.size.height / 2.0
    quiet_zone_guide = (
        Point(-half_width, -half_height),
        Point(half_width, -half_height),
        Point(half_width, half_height),
        Point(-half_width, half_height),
    )
    code_object = IconObject(
        "code.primary",
        "generated.{}".format(kind),
        size=code.size,
    )
    if presentation == "plain":
        document = CompositionDocument(
            objects=(code_object,),
            output_layer=output_layer,
            size=code.size,
            alignment="center",
        )
        artwork = StudioArtwork(code.polygons, (), (quiet_zone_guide,), document)
        return _add_machine_code_content_text(
            artwork,
            payload,
            vectorizer,
            show_content_text,
            content_text,
            content_height_mm,
            content_gap_mm,
        )

    frame_width = max(0.35, module_size_mm)
    frame_gap = frame_padding_mm
    corner_radius = max(0.8, frame_width * 2.0)
    caption_vectors = TextVectors((), Size())
    caption_position = Point()
    caption_object = None
    caption_typography = TypographyStyle(
        font_name="UbuntuMono-B",
        height_mm=caption_height_mm,
        alignment="center",
    )
    if presentation == "rounded_caption":
        caption = caption_text.strip()
        if not caption:
            raise ValueError("Enter footer text or choose Rounded frame without footer")
        if "\n" in caption or "\r" in caption:
            raise ValueError("QR footer text must be a single line")
        if len(caption) > 32:
            raise ValueError("QR footer text must be 32 characters or fewer")
        if vectorizer is None:
            raise ValueError("A text renderer is required for a QR footer")
        caption_vectors = vectorizer.render(caption, caption_typography)
        if not caption_vectors.polygons:
            raise ValueError("QR footer text has no printable artwork")

    horizontal_caption_padding = max(0.8, module_size_mm * 2.0)
    outer_width = code.size.width + 2.0 * (frame_gap + frame_width)
    if caption_vectors.polygons:
        outer_width = max(
            outer_width,
            caption_vectors.size.width + 2.0 * horizontal_caption_padding,
        )

    outer_top = -half_height - frame_gap - frame_width
    footer_top = half_height + frame_gap
    footer_height = 0.0
    if caption_vectors.polygons:
        footer_height = caption_vectors.size.height + 2.0 * (0.35 + frame_width / 2.0)
        outer_bottom = footer_top + footer_height
        caption_position = Point(0.0, footer_top + footer_height / 2.0)
        caption_object = TextObject(
            "code.caption",
            caption_text.strip(),
            position=caption_position,
            style_role="secondary",
        )
    else:
        outer_bottom = half_height + frame_gap + frame_width

    outer_size = Size(outer_width, outer_bottom - outer_top)
    outer_centre = Point(0.0, (outer_top + outer_bottom) / 2.0)
    frame_style = ShapeStyle(corner_radius_mm=corner_radius)
    outer = _translate_polygon(
        shape_contour("rounded_rectangle", outer_size, frame_style),
        outer_centre,
    )
    inner_size = Size(
        outer_size.width - 2.0 * frame_width,
        outer_size.height - 2.0 * frame_width,
    )
    # Tight frames need squarer inner corners so the rounded border never
    # clips the square QR quiet-zone corners. Extra padding progressively
    # restores the matching rounded inner contour.
    inner_radius = min(
        max(0.0, corner_radius - frame_width),
        frame_gap * 3.0,
    )
    inner = _translate_polygon(
        shape_contour(
            "rounded_rectangle",
            inner_size,
            ShapeStyle(corner_radius_mm=inner_radius),
        ),
        outer_centre,
    )
    frame_polygons = _knockout_tiles(outer, (inner,))

    footer_polygons = ()
    if caption_vectors.polygons:
        footer = _clip_polygon_below_y(outer, footer_top)
        placed_caption = tuple(
            _translate_polygon(polygon, caption_position)
            for polygon in caption_vectors.polygons
        )
        footer_polygons = _knockout_tiles(footer, placed_caption)

    content_ids = [code_object.object_id]
    objects = [code_object]
    if caption_object is not None:
        content_ids.append(caption_object.object_id)
        objects.append(caption_object)
    shape_object = ShapeObject(
        "code.container",
        shape="rounded_rectangle",
        position=outer_centre,
        size=outer_size,
        content_ids=tuple(content_ids),
    )
    objects.append(shape_object)
    objects.append(GroupObject("group.code", tuple(item.object_id for item in objects)))
    document = CompositionDocument(
        objects=tuple(objects),
        output_layer=output_layer,
        size=outer_size,
        alignment="center",
        style=DocumentStyle(typography=caption_typography, shape=frame_style),
    )
    artwork = StudioArtwork(
        filled_polygons=code.polygons + frame_polygons + footer_polygons,
        strokes=(),
        guides=(quiet_zone_guide,),
        document=document,
    )
    return _add_machine_code_content_text(
        artwork,
        payload,
        vectorizer,
        show_content_text,
        content_text,
        content_height_mm,
        content_gap_mm,
    )


def _add_machine_code_content_text(
    artwork: StudioArtwork,
    payload: str,
    vectorizer: Optional[TextVectorizer],
    enabled: bool,
    content_text: str,
    height_mm: float,
    gap_mm: float,
) -> StudioArtwork:
    """Add optional, editable human-readable text below a QR code or barcode."""
    if not enabled:
        return artwork
    display_text = content_text.strip() or payload.strip()
    if not display_text:
        raise ValueError("Enter machine-code display text or turn it off")
    if "\n" in display_text or "\r" in display_text:
        raise ValueError("Machine-code display text must be a single line")
    if len(display_text) > 96:
        raise ValueError("Machine-code display text must be 96 characters or fewer")
    if vectorizer is None:
        raise ValueError("A text renderer is required for machine-code display text")

    typography = TypographyStyle(
        font_name="UbuntuMono-B",
        height_mm=height_mm,
        alignment="center",
    )
    vectors = vectorizer.render(display_text, typography)
    if not vectors.polygons:
        raise ValueError("Machine-code display text has no printable artwork")

    source_polygons = artwork.filled_polygons + artwork.guides
    minimum, maximum = polygon_bounds(source_polygons)
    position = Point(
        (minimum.x + maximum.x) / 2.0,
        maximum.y + gap_mm + vectors.size.height / 2.0,
    )
    text_polygons = tuple(
        _translate_polygon(polygon, position) for polygon in vectors.polygons
    )
    text_minimum, text_maximum = polygon_bounds(text_polygons)
    outer_minimum = Point(
        min(minimum.x, text_minimum.x),
        min(minimum.y, text_minimum.y),
    )
    outer_maximum = Point(
        max(maximum.x, text_maximum.x),
        max(maximum.y, text_maximum.y),
    )
    origin = Point(
        (outer_minimum.x + outer_maximum.x) / 2.0,
        (outer_minimum.y + outer_maximum.y) / 2.0,
    )

    objects = tuple(
        item for item in artwork.document.objects
        if not isinstance(item, GroupObject) or item.object_id != "group.code"
    )
    text_object = TextObject(
        "code.content-text",
        display_text,
        position=position,
        style_role="secondary",
    )
    objects = objects + (text_object,)
    objects = objects + (
        GroupObject("group.code", tuple(item.object_id for item in objects)),
    )
    style = DocumentStyle(
        typography=typography,
        shape=artwork.document.style.shape,
        secondary_typography=typography,
    )
    document = CompositionDocument(
        objects=objects,
        output_layer=artwork.document.output_layer,
        anchor=artwork.document.anchor,
        origin=origin,
        size=Size(
            outer_maximum.x - outer_minimum.x,
            outer_maximum.y - outer_minimum.y,
        ),
        alignment="center",
        style=style,
    )
    return StudioArtwork(
        filled_polygons=artwork.filled_polygons + text_polygons,
        strokes=artwork.strokes,
        guides=artwork.guides,
        document=document,
    )


def render_header_artwork(vectorizer: TextVectorizer, spec: PinHeaderSpec) -> StudioArtwork:
    vectors = tuple(vectorizer.render(label, spec.style.typography) for label in spec.pin_labels)
    layout: HeaderLayout = layout_pin_header(spec, tuple(item.size for item in vectors))
    text_polygons = tuple(
        _place_polygon(polygon, centre, rotation)
        for item, centre, rotation in zip(vectors, layout.label_centres, layout.label_rotations_deg)
        for polygon in item.polygons
    )
    outer = layout.rail.regions[0].outer
    marker_polygons = (layout.pin1_marker,) if layout.pin1_marker else ()
    content_polygons = text_polygons + marker_polygons
    # The connector clearances are real knockouts for inverted blocks, not
    # merely preview circles.  This keeps silkscreen/mask/copper artwork off
    # the pins while the outer contour still encompasses the complete header.
    if spec.opening_mode == "continuous":
        opening_polygons = (layout.connector_keepout,)
        guides = (layout.connector_keepout,) + layout.pad_guides
    elif spec.opening_mode == "individual":
        opening_polygons = layout.pad_guides
        guides = layout.pad_guides
    else:
        opening_polygons = ()
        guides = layout.pad_guides
    filled, strokes = _shape_layers(outer, content_polygons, spec.style, opening_polygons)
    return StudioArtwork(
        filled_polygons=filled,
        strokes=strokes,
        guides=guides,
        document=layout.to_composition_document(),
        header=spec,
    )


def _mirror_polygon(polygon: Polygon) -> Polygon:
    return tuple(Point(-point.x, point.y) for point in reversed(polygon))


def _format_number(value: float) -> str:
    value = 0.0 if abs(value) < 0.0000005 else value
    return "{:.6f}".format(value).rstrip("0").rstrip(".") or "0"


def _polygon_sexpr(polygon: Polygon, layer: str, width_mm: float = 0.0, filled: bool = True) -> str:
    points = "\n".join(
        "      (xy {} {})".format(_format_number(point.x), _format_number(point.y)) for point in polygon
    )
    return """  (fp_poly
    (pts
{points}
    )
    (stroke (width {width}) (type solid))
    (fill {fill})
    (layer \"{layer}\")
  )""".format(
        points=points,
        width=_format_number(width_mm),
        fill="solid" if filled else "none",
        layer=layer,
    )


def serialize_artwork(artwork: StudioArtwork, encoded_parameters: str, output_layer: str) -> str:
    """Write preview-identical artwork as a KiCad 10 footprint."""
    if output_layer not in SUPPORTED_OUTPUT_LAYERS:
        raise ValueError("Unsupported Kobee Studio output layer: {}".format(output_layer))
    bottom = is_bottom(output_layer)
    filled = tuple(_mirror_polygon(polygon) if bottom else polygon for polygon in artwork.filled_polygons)
    strokes = tuple(
        StrokePath(_mirror_polygon(stroke.points) if bottom else stroke.points, stroke.width_mm)
        for stroke in artwork.strokes
    )
    exported = filled + tuple(stroke.points for stroke in strokes)
    if not exported:
        raise ValueError("Kobee Studio artwork is empty")
    minimum, maximum = polygon_bounds(exported)
    reference_y = minimum.y - 1.0
    value_y = maximum.y + 1.0
    owner_layer = "B.Cu" if bottom else "F.Cu"
    name = "kobee-studio-{:08X}".format(int(round(time.time())))
    graphics = [
        _polygon_sexpr(polygon, output_layer, filled=True) for polygon in filled if len(polygon) >= 3
    ]
    graphics.extend(
        _polygon_sexpr(stroke.points, output_layer, width_mm=stroke.width_mm, filled=False)
        for stroke in strokes
        if len(stroke.points) >= 3
    )
    return """(footprint \"{name}\"
  (version 20240108)
  (generator kobee_studio)
  (layer \"{owner_layer}\")
  (attr board_only exclude_from_pos_files exclude_from_bom)
  (descr \"Generated with Kobee Studio (evolved from KiBuzzard)\")
  (tags \"kb_params={parameters}\")
  (fp_text reference \"{name}\" (at 0 {reference_y}) (layer \"{output_layer}\") hide
    (effects (font (size 0 0) (thickness 0)))
  )
  (fp_text value \"G***\" (at 0 {value_y}) (layer \"{output_layer}\") hide
    (effects (font (size 0 0) (thickness 0)))
  )
{graphics}
)""".format(
        name=name,
        owner_layer=owner_layer,
        parameters=encoded_parameters,
        reference_y=_format_number(reference_y),
        value_y=_format_number(value_y),
        output_layer=output_layer,
        graphics="\n".join(graphics),
    )

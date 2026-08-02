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
    IconObject,
    Point,
    ShapeObject,
    ShapeStyle,
    Size,
    TextObject,
    TypographyStyle,
)
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

    @property
    def all_exported_polygons(self) -> Tuple[Polygon, ...]:
        return self.filled_polygons + tuple(stroke.points for stroke in self.strokes)


class TextVectorizer:
    """Convert the mature bundled font renderer into millimetre polygons."""

    def __init__(self, buzzard) -> None:
        self.buzzard = buzzard

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
            return TextVectors((), Size())

        minimum, maximum = polygon_bounds(polygons)
        centre = Point((minimum.x + maximum.x) / 2.0, (minimum.y + maximum.y) / 2.0)
        centred = tuple(_translate_polygon(polygon, Point(-centre.x, -centre.y)) for polygon in polygons)
        return TextVectors(centred, Size(maximum.x - minimum.x, maximum.y - minimum.y))


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
        if y1 - y0 <= epsilon:
            continue
        middle_y = (y0 + y1) / 2.0
        crossings = []
        for ring_index, ring in enumerate(rings):
            for edge_index, start in enumerate(ring):
                end = ring[(edge_index + 1) % len(ring)]
                low, high = sorted((start.y, end.y))
                if end.y == start.y or not (low < middle_y < high):
                    continue
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
) -> StudioArtwork:
    if icon_position not in ("left", "right", "only"):
        raise ValueError("Unsupported icon position: {}".format(icon_position))
    if icon_height_mm < 0:
        raise ValueError("Icon height must be non-negative")
    if icon_gap_mm < 0:
        raise ValueError("Icon gap must be non-negative")

    has_icon = bool(icon_id)
    has_text = bool(text) and icon_position != "only"
    if not has_text and not has_icon:
        raise ValueError("A label needs text or an icon")

    vectors = vectorizer.render(
        text if has_text else "",
        style.typography,
        inline_format,
        lineover_style,
        lineover_thickness,
    )
    icon = (
        render_builtin_icon(icon_id, icon_height_mm or style.typography.height_mm)
        if has_icon
        else None
    )
    gap = icon_gap_mm if has_text and icon is not None else 0.0
    content_size = Size(
        vectors.size.width + (icon.size.width if icon else 0.0) + gap,
        max(vectors.size.height, icon.size.height if icon else 0.0),
    )

    text_centre = Point()
    icon_centre = Point()
    if has_text and icon is not None:
        if icon_position == "left":
            icon_centre = Point(-content_size.width / 2.0 + icon.size.width / 2.0, 0.0)
            text_centre = Point(content_size.width / 2.0 - vectors.size.width / 2.0, 0.0)
        else:
            text_centre = Point(-content_size.width / 2.0 + vectors.size.width / 2.0, 0.0)
            icon_centre = Point(content_size.width / 2.0 - icon.size.width / 2.0, 0.0)

    placed_text = tuple(_translate_polygon(polygon, text_centre) for polygon in vectors.polygons)
    placed_icon = tuple(
        _translate_polygon(polygon, icon_centre) for polygon in (icon.polygons if icon else ())
    )
    content_polygons = placed_text + placed_icon
    if content_polygons:
        content_minimum, content_maximum = polygon_bounds(content_polygons)
        normalise = Point(
            -(content_minimum.x + content_maximum.x) / 2.0,
            -(content_minimum.y + content_maximum.y) / 2.0,
        )
        text_centre = Point(text_centre.x + normalise.x, text_centre.y + normalise.y)
        icon_centre = Point(icon_centre.x + normalise.x, icon_centre.y + normalise.y)
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
    if has_text:
        objects.append(TextObject("text.primary", text, position=text_centre))
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
        document = CompositionDocument(
            objects=tuple(objects),
            output_layer=output_layer,
            size=content_size,
            alignment=style.typography.alignment,
            style=style,
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
        else:
            placed_objects_list.append(
                IconObject(
                    item.object_id,
                    item.asset_id,
                    position=position,
                    size=item.size,
                    rotation_deg=item.rotation_deg,
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
    document = CompositionDocument(
        objects=placed_objects + (shape_object, group),
        output_layer=output_layer,
        size=geometry.outer_size,
        alignment=style.typography.alignment,
        style=style,
    )
    return StudioArtwork(filled, strokes, (), document)


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
        return StudioArtwork(code.polygons, (), (quiet_zone_guide,), document)

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
    return StudioArtwork(
        filled_polygons=code.polygons + frame_polygons + footer_polygons,
        strokes=(),
        guides=(quiet_zone_guide,),
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

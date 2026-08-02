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
    Size,
    TextObject,
    TypographyStyle,
)
from .icon_catalog import render_builtin_icon
from .pin_header import HeaderLayout, PinHeaderSpec, layout_pin_header
from .shape_geometry import Polygon, inset_polygon, polygon_bounds, render_shape
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
    """Decompose an even-odd polygon with holes into simple trapezoids.

    KiCad footprint polygons have no native hole rings.  The former zero-width
    bridge approach becomes self-intersecting with several glyphs and a long
    connector opening.  Horizontal trapezoid decomposition preserves the
    exact polygon edges, supports nested glyph counters, and emits only simple
    filled polygons that KiCad renders reliably.
    """
    rings = tuple(ring for ring in (outer,) + tuple(holes) if len(ring) >= 3)
    levels = sorted({point.y for ring in rings for point in ring})
    tiles = []
    epsilon = 1e-10
    for y0, y1 in zip(levels, levels[1:]):
        if y1 - y0 <= epsilon:
            continue
        middle_y = (y0 + y1) / 2.0
        crossings = []
        for ring in rings:
            for index, start in enumerate(ring):
                end = ring[(index + 1) % len(ring)]
                low, high = sorted((start.y, end.y))
                if end.y == start.y or not (low < middle_y < high):
                    continue
                crossings.append(
                    (
                        _edge_x_at_y(start, end, middle_y),
                        _edge_x_at_y(start, end, y0),
                        _edge_x_at_y(start, end, y1),
                    )
                )
        crossings.sort(key=lambda item: item[0])
        # Every closed-ring scanline has an even crossing count.  Pairing them
        # applies the even-odd fill rule, including counters in O, P, R, etc.
        for left, right in zip(crossings[0::2], crossings[1::2]):
            if right[0] - left[0] <= epsilon:
                continue
            tile = (
                Point(left[1], y0),
                Point(right[1], y0),
                Point(right[2], y1),
                Point(left[2], y1),
            )
            if abs(_signed_area(tile)) > epsilon:
                tiles.append(tile)
    return tuple(tiles)


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
    """Build compact weakly-simple KiCad polygons using even-odd nesting."""
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
    placed_text = tuple(_translate_polygon(polygon, text_centre) for polygon in vectors.polygons)
    placed_icon = tuple(
        _translate_polygon(polygon, icon_centre) for polygon in (icon.polygons if icon else ())
    )
    content_polygons = placed_text + placed_icon

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

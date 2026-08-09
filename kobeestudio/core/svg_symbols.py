"""Discoverable SVG symbols and update-safe custom vector asset storage."""

from __future__ import annotations

import json
import hashlib
from functools import lru_cache
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .composition import Point, Size
from .data_paths import project_data_root, user_data_root
from .quick_labels import QuickLabelStore
from .shape_geometry import Polygon, polygon_bounds


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
BUNDLED_SYMBOLS_ROOT = Path(__file__).resolve().parents[1] / "resources" / "symbols"
BUNDLED_LABELS_ROOT = Path(__file__).resolve().parents[1] / "resources" / "labels"
ASSET_SCHEMA_VERSION = 1
MAX_SVG_BYTES = 2 * 1024 * 1024
MAX_SVG_ELEMENTS = 10000
MAX_SVG_POINTS = 100000
_SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_BUNDLED_FILE = re.compile(r"^(?P<slug>[a-z0-9]+(?:_[a-z0-9]+)*)--(?P<variant>[a-z0-9]+(?:_[a-z0-9]+)*)\.svg$")
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_SAFE_TAGS = frozenset(
    (
        "svg", "g", "path", "polygon", "polyline", "rect", "circle", "ellipse", "line",
        "title", "desc", "defs", "clipPath", "mask", "linearGradient", "radialGradient", "stop",
    )
)
_RENDERABLE_TAGS = frozenset(("svg", "g", "path", "polygon", "polyline", "rect", "circle", "ellipse", "title", "desc", "defs"))
_FORBIDDEN_ATTRIBUTE_PREFIXES = ("on",)
_URL_ATTRIBUTES = frozenset(("href", "xlink:href", "src"))


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _slug(value: str, field: str) -> str:
    value = str(value).strip().lower()
    if not _SLUG.fullmatch(value):
        raise ValueError("{} must use lowercase letters, numbers, and underscores".format(field))
    return value


def _display_name(value: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 100 or any(ord(character) < 32 for character in value):
        raise ValueError("Asset display name must contain 1 to 100 printable characters")
    return value


def _read_svg(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("SVG asset must be a regular file")
    size = path.stat().st_size
    if size <= 0 or size > MAX_SVG_BYTES:
        raise ValueError("SVG asset must be between 1 byte and 2 MiB")
    return path.read_bytes()


def validate_svg_bytes(data: bytes, require_renderable: bool = False) -> ET.Element:
    """Reject active/external content and optionally unsupported symbol geometry."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_SVG_BYTES:
        raise ValueError("SVG asset must be between 1 byte and 2 MiB")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("SVG documents cannot contain DTD or entity declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("Invalid SVG XML: {}".format(error))
    if _local_name(root.tag) != "svg":
        raise ValueError("The uploaded document is not an SVG")
    elements = list(root.iter())
    if len(elements) > MAX_SVG_ELEMENTS:
        raise ValueError("SVG contains too many elements")
    allowed = _RENDERABLE_TAGS if require_renderable else _SAFE_TAGS
    for element in elements:
        tag = _local_name(element.tag)
        if tag not in allowed:
            raise ValueError("Unsupported or unsafe SVG element: {}".format(tag))
        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            lower_name = name.lower()
            value = str(raw_value).strip().lower()
            if lower_name.startswith(_FORBIDDEN_ATTRIBUTE_PREFIXES):
                raise ValueError("SVG event attributes are not allowed")
            if lower_name in _URL_ATTRIBUTES or "url(" in value or value.startswith(("http:", "https:", "data:", "file:")):
                raise ValueError("SVG assets cannot reference external or embedded resources")
    if require_renderable:
        svg_polygons_from_root(root)
    return root


def _numbers(value: Optional[str], expected: Optional[int] = None) -> List[float]:
    values = [float(item) for item in _NUMBER.findall(value or "")]
    if expected is not None and len(values) != expected:
        raise ValueError("Expected {} numeric SVG values".format(expected))
    if not all(math.isfinite(item) for item in values):
        raise ValueError("SVG coordinates must be finite")
    return values


Matrix = Tuple[float, float, float, float, float, float]
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _multiply(first: Matrix, second: Matrix) -> Matrix:
    a, b, c, d, e, f = first
    g, h, i, j, k, l = second
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def _transform(value: Optional[str]) -> Matrix:
    result = _IDENTITY
    if not value:
        return result
    position = 0
    pattern = re.compile(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)")
    for match in pattern.finditer(value):
        if value[position:match.start()].strip(" ,\t\r\n"):
            raise ValueError("Unsupported SVG transform")
        name, raw = match.group(1), match.group(2)
        values = _numbers(raw)
        if name == "matrix" and len(values) == 6:
            operation = tuple(values)  # type: ignore[assignment]
        elif name == "translate" and len(values) in (1, 2):
            operation = (1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) == 2 else 0.0)
        elif name == "scale" and len(values) in (1, 2):
            operation = (values[0], 0.0, 0.0, values[-1], 0.0, 0.0)
        elif name == "rotate" and len(values) in (1, 3):
            angle = math.radians(values[0])
            rotation = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0.0, 0.0)
            if len(values) == 3:
                cx, cy = values[1], values[2]
                operation = _multiply(_multiply((1, 0, 0, 1, cx, cy), rotation), (1, 0, 0, 1, -cx, -cy))
            else:
                operation = rotation
        else:
            raise ValueError("Invalid SVG {} transform".format(name))
        result = _multiply(result, operation)
        position = match.end()
    if value[position:].strip(" ,\t\r\n"):
        raise ValueError("Unsupported SVG transform")
    return result


def _apply(point: Tuple[float, float], matrix: Matrix) -> Point:
    x, y = point
    a, b, c, d, e, f = matrix
    return Point(a * x + c * y + e, b * x + d * y + f)


class _FlatteningPen:
    def __init__(self, segments: int = 12) -> None:
        self.segments = segments
        self.polygons: List[List[Tuple[float, float]]] = []
        self.current: Optional[List[Tuple[float, float]]] = None
        self.point_count = 0

    def moveTo(self, point) -> None:
        if self.current:
            raise ValueError("SVG symbol paths must close every filled subpath")
        self.current = [tuple(point)]
        self.point_count += 1
        self._check_size()

    def lineTo(self, point) -> None:
        if self.current is None:
            raise ValueError("Invalid SVG path")
        self.current.append(tuple(point))
        self.point_count += 1
        self._check_size()

    def curveTo(self, control1, control2, end) -> None:
        if self.current is None:
            raise ValueError("Invalid SVG path")
        start = self.current[-1]
        for index in range(1, self.segments + 1):
            t = index / float(self.segments)
            inverse = 1.0 - t
            self.current.append(
                (
                    inverse ** 3 * start[0] + 3 * inverse ** 2 * t * control1[0] + 3 * inverse * t ** 2 * control2[0] + t ** 3 * end[0],
                    inverse ** 3 * start[1] + 3 * inverse ** 2 * t * control1[1] + 3 * inverse * t ** 2 * control2[1] + t ** 3 * end[1],
                )
            )
            self.point_count += 1
            self._check_size()

    def qCurveTo(self, *points) -> None:
        if self.current is None or not points:
            raise ValueError("Invalid SVG path")
        start = self.current[-1]
        control, end = points[-2], points[-1]
        for index in range(1, self.segments + 1):
            t = index / float(self.segments)
            inverse = 1.0 - t
            self.current.append(
                (
                    inverse ** 2 * start[0] + 2 * inverse * t * control[0] + t ** 2 * end[0],
                    inverse ** 2 * start[1] + 2 * inverse * t * control[1] + t ** 2 * end[1],
                )
            )
            self.point_count += 1
            self._check_size()

    def _check_size(self) -> None:
        if self.point_count > MAX_SVG_POINTS:
            raise ValueError("SVG symbol contains too many polygon points")

    def closePath(self) -> None:
        if self.current is None:
            raise ValueError("Invalid SVG path")
        if len(self.current) > 1 and self.current[-1] == self.current[0]:
            self.current.pop()
        if len(self.current) < 3:
            raise ValueError("SVG symbol paths need at least three points")
        self.polygons.append(self.current)
        self.current = None

    def endPath(self) -> None:
        if self.current:
            raise ValueError("SVG symbol paths must be closed and filled")


def _parse_path(data: str) -> List[List[Tuple[float, float]]]:
    package_root = Path(__file__).resolve().parents[1]
    vendor = str(package_root / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    from fontTools.svgLib.path import parse_path

    pen = _FlatteningPen()
    parse_path(data, pen)
    if pen.current:
        raise ValueError("SVG symbol paths must be closed and filled")
    return pen.polygons


def _raw_point_in_polygon(point: Tuple[float, float], polygon: Sequence[Tuple[float, float]]) -> bool:
    inside = False
    x, y = point
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if (start[1] > y) == (end[1] > y):
            continue
        crossing_x = start[0] + (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
        if crossing_x > x:
            inside = not inside
    return inside


def _raw_area(polygon: Sequence[Tuple[float, float]]) -> float:
    return sum(
        point[0] * polygon[(index + 1) % len(polygon)][1]
        - polygon[(index + 1) % len(polygon)][0] * point[1]
        for index, point in enumerate(polygon)
    ) / 2.0


def _filled_svg_contours(
    raw_contours: Sequence[Sequence[Tuple[float, float]]], matrix: Matrix, fill_rule: Optional[str]
) -> Tuple[Polygon, ...]:
    """Convert even-odd SVG cut-outs into ordinary, filled PCB polygons."""
    raw_contours = tuple(contour for contour in raw_contours if len(contour) >= 3)
    parents = []
    for index, contour in enumerate(raw_contours):
        containers = [
            candidate for candidate, other in enumerate(raw_contours)
            if candidate != index
            and abs(_raw_area(other)) > abs(_raw_area(contour))
            and _raw_point_in_polygon(contour[0], other)
        ]
        parents.append(min(containers, key=lambda candidate: abs(_raw_area(raw_contours[candidate]))) if containers else None)
    if any(parent is not None for parent in parents) and (fill_rule or "nonzero").strip().lower() != "evenodd":
        raise ValueError("SVG cut-outs must use the evenodd fill rule")
    depth = []
    for index in range(len(raw_contours)):
        value, parent = 0, parents[index]
        while parent is not None:
            value += 1
            parent = parents[parent]
        depth.append(value)
    transformed = tuple(tuple(_apply(point, matrix) for point in contour) for contour in raw_contours)
    polygons = []

    def overlap_join(polygon: Polygon) -> Polygon:
        """Slightly overlap touching SVG pieces to prevent canvas seam cracks.

        Inkscape exports a surprising number of symbols as adjacent polygons
        (not one unioned path).  KiCad anti-aliases their common boundary and
        can reveal the board grid as speckles.  Normalising every emitted
        filled piece here makes bundled and uploaded symbols behave alike.
        """
        centre_x = sum(point.x for point in polygon) / len(polygon)
        centre_y = sum(point.y for point in polygon) / len(polygon)
        # This is 0.1% about each piece's centre: far below normal PCB
        # fabrication resolution, but enough to cover one-pixel joins in
        # KiCad's anti-aliased canvas.
        return tuple(
            Point(
                centre_x + (point.x - centre_x) * 1.001,
                centre_y + (point.y - centre_y) * 1.001,
            )
            for point in polygon
        )
    # Reuse the tested scanline decomposition used for label knockouts. It
    # converts an outer contour plus its direct holes into non-self-
    # intersecting filled regions that KiCad renders reliably.
    from .studio_artwork import _knockout_tiles

    for index, contour in enumerate(transformed):
        if depth[index] % 2:
            continue
        holes = tuple(
            transformed[child] for child, parent in enumerate(parents)
            if parent == index and depth[child] == depth[index] + 1
        )
        if holes:
            polygons.extend(overlap_join(tile) for tile in _knockout_tiles(contour, holes))
        else:
            polygons.append(overlap_join(contour))
    return tuple(polygons)


def _style_value(element: ET.Element, name: str, inherited: Optional[str] = None) -> Optional[str]:
    value = element.get(name, inherited)
    style = element.get("style", "")
    for declaration in style.split(";"):
        key, separator, item = declaration.partition(":")
        if separator and key.strip() == name:
            value = item.strip()
    return value


def _element_polygons(element: ET.Element) -> List[List[Tuple[float, float]]]:
    tag = _local_name(element.tag)
    if tag == "path":
        return _parse_path(element.get("d", ""))
    if tag in ("polygon", "polyline"):
        values = _numbers(element.get("points"))
        if len(values) < 6 or len(values) % 2:
            raise ValueError("SVG polygon points are invalid")
        return [[(values[index], values[index + 1]) for index in range(0, len(values), 2)]]
    if tag == "rect":
        x, y = float(element.get("x", "0")), float(element.get("y", "0"))
        width, height = float(element.get("width", "0")), float(element.get("height", "0"))
        if width <= 0 or height <= 0:
            raise ValueError("SVG symbol rectangles must have positive size")
        raw_rx, raw_ry = element.get("rx"), element.get("ry")
        if raw_rx is None and raw_ry is None:
            return [[(x, y), (x + width, y), (x + width, y + height), (x, y + height)]]
        rx = float(raw_rx if raw_rx is not None else raw_ry)
        ry = float(raw_ry if raw_ry is not None else raw_rx)
        if rx < 0 or ry < 0:
            raise ValueError("SVG rectangle corner radii cannot be negative")
        rx, ry = min(rx, width / 2.0), min(ry, height / 2.0)
        if rx == 0 or ry == 0:
            return [[(x, y), (x + width, y), (x + width, y + height), (x, y + height)]]
        points = []
        for centre_x, centre_y, start in (
            (x + width - rx, y + ry, -90),
            (x + width - rx, y + height - ry, 0),
            (x + rx, y + height - ry, 90),
            (x + rx, y + ry, 180),
        ):
            for step in range(9):
                angle = math.radians(start + step * 90.0 / 8.0)
                points.append((centre_x + rx * math.cos(angle), centre_y + ry * math.sin(angle)))
        return [points]
    if tag in ("circle", "ellipse"):
        cx, cy = float(element.get("cx", "0")), float(element.get("cy", "0"))
        rx = float(element.get("r", element.get("rx", "0")))
        ry = float(element.get("r", element.get("ry", "0")))
        if rx <= 0 or ry <= 0:
            raise ValueError("SVG circles and ellipses must have positive radii")
        return [[(cx + rx * math.cos(2 * math.pi * index / 32), cy + ry * math.sin(2 * math.pi * index / 32)) for index in range(32)]]
    return []


def svg_polygons_from_root(root: ET.Element) -> Tuple[Polygon, ...]:
    polygons: List[Polygon] = []
    point_count = 0

    def visit(element: ET.Element, parent_matrix: Matrix, inherited_fill: Optional[str]) -> None:
        nonlocal point_count
        tag = _local_name(element.tag)
        # Inkscape commonly emits an empty <defs> block even when no reusable
        # geometry is present. Definitions are never visible artwork and must
        # not be rendered merely because they contain a supported primitive.
        if tag == "defs":
            return
        matrix = _multiply(parent_matrix, _transform(element.get("transform")))
        fill = _style_value(element, "fill", inherited_fill)
        if tag in ("path", "polygon", "polyline", "rect", "circle", "ellipse"):
            if fill is not None and fill.strip().lower() == "none":
                if (_style_value(element, "stroke") or "none").strip().lower() != "none":
                    raise ValueError("Stroked SVG symbols must be converted to filled paths")
                return
            raw_polygons = _element_polygons(element)
            fill_rule = _style_value(element, "fill-rule", None)
            for polygon in _filled_svg_contours(raw_polygons, matrix, fill_rule):
                point_count += len(polygon)
                if point_count > MAX_SVG_POINTS:
                    raise ValueError("SVG symbol contains too many polygon points")
                if not all(math.isfinite(point.x) and math.isfinite(point.y) for point in polygon):
                    raise ValueError("SVG coordinates must be finite")
                if len(polygon) >= 3:
                    polygons.append(polygon)
        for child in element:
            visit(child, matrix, fill)

    visit(root, _IDENTITY, "black")
    if not polygons:
        raise ValueError("SVG symbol contains no supported filled geometry")
    return tuple(polygons)


@lru_cache(maxsize=128)
def _svg_geometry(path_text: str, modified_ns: int, byte_size: int):
    """Cache immutable geometry while still invalidating replaced SVG files."""
    path = Path(path_text)
    root = validate_svg_bytes(_read_svg(path), require_renderable=True)
    polygons = svg_polygons_from_root(root)
    view_box = _numbers(root.get("viewBox"))
    if view_box:
        if len(view_box) != 4 or view_box[2] <= 0 or view_box[3] <= 0:
            raise ValueError("SVG symbol viewBox must contain x, y, positive width, and positive height")
        minimum = Point(view_box[0], view_box[1])
        maximum = Point(view_box[0] + view_box[2], view_box[1] + view_box[3])
    else:
        minimum, maximum = polygon_bounds(polygons)
    return polygons, minimum, maximum


def render_svg(path: Path, height_mm: float) -> Tuple[Tuple[Polygon, ...], Size]:
    if not math.isfinite(float(height_mm)) or float(height_mm) <= 0:
        raise ValueError("Symbol height must be greater than zero")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("SVG asset must be a regular file")
    stat = path.stat()
    polygons, minimum, maximum = _svg_geometry(
        str(path.resolve()), stat.st_mtime_ns, stat.st_size
    )
    natural_height = maximum.y - minimum.y
    if natural_height <= 0:
        raise ValueError("SVG symbol has no measurable height")
    scale = float(height_mm) / natural_height
    centre_x = (minimum.x + maximum.x) / 2.0
    centre_y = (minimum.y + maximum.y) / 2.0
    scaled = tuple(
        tuple(Point((point.x - centre_x) * scale, (point.y - centre_y) * scale) for point in polygon)
        for polygon in polygons
    )
    return scaled, Size((maximum.x - minimum.x) * scale, float(height_mm))


def format_symbol_reference(asset_id: str, variant: str = "default") -> str:
    variant = _slug(variant, "symbol variant")
    return str(asset_id) if variant == "default" else "{}@{}".format(asset_id, variant)


def parse_symbol_reference(reference: str) -> Tuple[str, str]:
    asset_id, separator, variant = str(reference).rpartition("@")
    if not separator:
        return str(reference), "default"
    if not asset_id:
        raise ValueError("Symbol reference is missing an asset id")
    return asset_id, _slug(variant, "symbol variant")


@dataclass(frozen=True)
class SymbolAsset:
    asset_id: str
    slug: str
    variant: str
    name: str
    category: str
    path: Path
    source: str
    scope: str = "bundle"

    @property
    def key(self) -> Tuple[str, str]:
        return self.asset_id, self.variant


@dataclass(frozen=True)
class LinkedLabel:
    preset_id: str
    text: str
    category: str
    symbol_id: str = ""
    symbol_variant: str = "default"
    source: str = "bundle"
    scope: str = "bundle"


class SymbolCatalog:
    def __init__(self, symbols: Iterable[SymbolAsset], labels: Iterable[LinkedLabel] = (), allow_missing_label_symbols: bool = False) -> None:
        by_key: Dict[Tuple[str, str], SymbolAsset] = {}
        for symbol in symbols:
            if symbol.key in by_key:
                raise ValueError("Duplicate symbol variant: {} {}".format(*symbol.key))
            by_key[symbol.key] = symbol
        self._by_key = by_key
        self.symbols = tuple(sorted(by_key.values(), key=lambda item: (item.category.casefold(), item.name.casefold(), item.variant)))
        self.labels = tuple(labels)
        for label in self.labels:
            if label.symbol_id and (label.symbol_id, label.symbol_variant) not in by_key and not allow_missing_label_symbols:
                raise ValueError("Label {} references unknown symbol {} {}".format(label.preset_id, label.symbol_id, label.symbol_variant))

    def resolve(self, asset_id: str, variant: str = "default") -> SymbolAsset:
        try:
            return self._by_key[(asset_id, _slug(variant, "variant"))]
        except KeyError:
            raise ValueError("Unknown SVG symbol variant: {} {}".format(asset_id, variant))

    def variants(self, asset_id: str) -> Tuple[SymbolAsset, ...]:
        return tuple(item for item in self.symbols if item.asset_id == asset_id)

    def render(self, asset_id: str, height_mm: float, variant: str = "default"):
        return render_svg(self.resolve(asset_id, variant).path, height_mm)

    def resolve_reference(self, reference: str) -> SymbolAsset:
        return self.resolve(*parse_symbol_reference(reference))

    def render_reference(self, reference: str, height_mm: float):
        asset_id, variant = parse_symbol_reference(reference)
        return self.render(asset_id, height_mm, variant)

    @classmethod
    def discover(
        cls,
        bundle_root: Path = BUNDLED_SYMBOLS_ROOT,
        labels_root: Path = BUNDLED_LABELS_ROOT,
        custom_stores: Sequence["SvgAssetStore"] = (),
        custom_label_stores: Sequence[QuickLabelStore] = (),
    ) -> "SymbolCatalog":
        symbols = list(discover_bundled_symbols(bundle_root))
        for store in custom_stores:
            symbols.extend(store.list(namespace="symbols"))
        labels = list(discover_linked_labels(labels_root))
        for store in custom_label_stores:
            labels.extend(
                LinkedLabel(
                    item.preset_id, item.text, item.category, item.symbol_id,
                    item.symbol_variant, "custom", item.scope,
                )
                for item in store.list()
            )
        # A removed custom symbol must not stop the picker from opening.  The
        # corresponding custom label remains manageable in Settings and is
        # simply hidden until its symbol is restored or the link is cleared.
        available = {symbol.key for symbol in symbols}
        labels = [
            label for label in labels
            if not label.symbol_id or (label.symbol_id, label.symbol_variant) in available or label.source == "bundle"
        ]
        return cls(symbols, labels)


def symbol_catalog_for_context(
    project: Optional[Union[str, Path]] = None,
    data_root: Optional[Path] = None,
    hidden_symbol_ids: Sequence[str] = (),
    hidden_label_ids: Sequence[str] = (),
) -> SymbolCatalog:
    """Build the complete shipped and user-managed catalog for one context."""
    stores: List[SvgAssetStore] = []
    label_stores: List[QuickLabelStore] = []
    stores.append(SvgAssetStore.global_store(data_root))
    label_stores.append(QuickLabelStore.global_store(data_root))
    if project is not None:
        stores.append(SvgAssetStore.project_store(project))
        label_stores.append(QuickLabelStore.project_store(project))
    raw_catalog = SymbolCatalog.discover(custom_stores=tuple(stores), custom_label_stores=tuple(label_stores))
    hidden_symbols = frozenset(str(item) for item in hidden_symbol_ids)
    hidden_labels = frozenset(str(item) for item in hidden_label_ids)
    visible_symbols = tuple(symbol for symbol in raw_catalog.symbols if symbol.asset_id not in hidden_symbols)
    visible_labels = tuple(
        label for label in raw_catalog.labels
        if label.preset_id not in hidden_labels
    )
    return SymbolCatalog(visible_symbols, visible_labels, allow_missing_label_symbols=True)


def discover_bundled_symbols(root: Path = BUNDLED_SYMBOLS_ROOT) -> Tuple[SymbolAsset, ...]:
    root = Path(root)
    if not root.exists():
        return ()
    symbols = []
    for path in sorted(root.glob("*/*.svg")):
        if path.is_symlink() or not path.is_file():
            continue
        match = _BUNDLED_FILE.fullmatch(path.name)
        if match is None or not _SLUG.fullmatch(path.parent.name):
            raise ValueError("Invalid bundled symbol path: {}".format(path.relative_to(root)))
        slug, variant = match.group("slug"), match.group("variant")
        root_element = validate_svg_bytes(_read_svg(path), require_renderable=True)
        title = root_element.find("{{{}}}title".format(SVG_NAMESPACE))
        name = _display_name(title.text if title is not None and title.text else slug.replace("_", " ").title())
        symbols.append(SymbolAsset("builtin.{}".format(slug), slug, variant, name, path.parent.name.replace("_", " ").title(), path, "bundle"))
    return tuple(symbols)


def discover_linked_labels(root: Path = BUNDLED_LABELS_ROOT) -> Tuple[LinkedLabel, ...]:
    labels = []
    seen = set()
    root = Path(root)
    if not root.exists():
        return ()
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("labels"), list):
            raise ValueError("Invalid linked-label catalog: {}".format(path))
        for item in payload["labels"]:
            preset_id = _slug(item["id"], "label id")
            if preset_id in seen:
                raise ValueError("Duplicate linked-label id: {}".format(preset_id))
            seen.add(preset_id)
            labels.append(
                LinkedLabel(
                    preset_id,
                    _display_name(item["text"]),
                    _display_name(item["category"]),
                    str(item.get("symbol_id", "")),
                    _slug(item.get("symbol_variant", "default"), "symbol variant"),
                    "bundle",
                    "bundle",
                )
            )
    return tuple(labels)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".metadata-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class SvgAssetStore:
    """Generic SVG upload/delete storage for global or project scope."""

    def __init__(self, root: Path, scope: str) -> None:
        if scope not in ("global", "project"):
            raise ValueError("Asset scope must be global or project")
        self.root = Path(root) / "assets" / "v1"
        self.scope = scope

    @classmethod
    def global_store(cls, root: Optional[Path] = None) -> "SvgAssetStore":
        return cls(Path(root) if root is not None else user_data_root(), "global")

    @classmethod
    def project_store(cls, project: Union[str, Path]) -> "SvgAssetStore":
        return cls(project_data_root(project), "project")

    def upload(
        self,
        source: Path,
        namespace: str,
        name: str,
        category: str = "Custom",
        slug: Optional[str] = None,
        variant: str = "default",
        asset_id: Optional[str] = None,
    ) -> SymbolAsset:
        namespace = _slug(namespace, "asset namespace")
        slug = _slug(slug or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"), "asset slug")
        variant = _slug(variant, "asset variant")
        name = _display_name(name)
        category = _display_name(category)
        source = Path(source)
        data = _read_svg(source)
        validate_svg_bytes(data, require_renderable=namespace == "symbols")
        content_sha256 = hashlib.sha256(data).hexdigest()
        if asset_id is None:
            asset_id = "custom.{}".format(uuid.uuid4())
        else:
            prefix, separator, raw_uuid = str(asset_id).partition(".")
            if prefix != "custom" or separator != ".":
                raise ValueError("Custom asset ids use custom.<uuid>")
            asset_id = "custom.{}".format(uuid.UUID(raw_uuid))
        if any(item.asset_id == asset_id and item.variant == variant for item in self.list(namespace)):
            raise ValueError("That custom asset already has a {} variant".format(variant))
        item_id = str(uuid.uuid4())
        destination = self.root / namespace / item_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".upload-", dir=str(destination.parent)))
        try:
            asset_path = staging / "asset.svg"
            with asset_path.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            _atomic_json(
                staging / "metadata.json",
                {
                    "schema_version": ASSET_SCHEMA_VERSION,
                    "asset_id": asset_id,
                    "namespace": namespace,
                    "slug": slug,
                    "variant": variant,
                    "name": name,
                    "category": category,
                    "scope": self.scope,
                    "content_sha256": content_sha256,
                },
            )
            os.replace(str(staging), str(destination))
        except Exception:
            shutil.rmtree(str(staging), ignore_errors=True)
            raise
        return SymbolAsset(asset_id, slug, variant, name, category, destination / "asset.svg", "custom", self.scope)

    def list(self, namespace: str) -> Tuple[SymbolAsset, ...]:
        namespace = _slug(namespace, "asset namespace")
        directory = self.root / namespace
        if not directory.exists():
            return ()
        items = []
        for item_root in sorted(directory.iterdir()):
            if item_root.is_symlink() or not item_root.is_dir():
                continue
            metadata_path, asset_path = item_root / "metadata.json", item_root / "asset.svg"
            if metadata_path.is_symlink() or asset_path.is_symlink() or not metadata_path.is_file() or not asset_path.is_file():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != ASSET_SCHEMA_VERSION or payload.get("namespace") != namespace or payload.get("scope") != self.scope:
                    continue
                validate_svg_bytes(_read_svg(asset_path), require_renderable=namespace == "symbols")
                expected_hash = payload.get("content_sha256")
                if expected_hash and hashlib.sha256(asset_path.read_bytes()).hexdigest() != expected_hash:
                    continue
                items.append(
                    SymbolAsset(
                        str(payload["asset_id"]),
                        _slug(payload["slug"], "asset slug"),
                        _slug(payload["variant"], "asset variant"),
                        _display_name(payload["name"]),
                        _display_name(payload["category"]),
                        asset_path,
                        "custom",
                        self.scope,
                    )
                )
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(items)

    def delete(self, namespace: str, asset_id: str, variant: Optional[str] = None) -> int:
        namespace = _slug(namespace, "asset namespace")
        variant = _slug(variant, "asset variant") if variant is not None else None
        matches = [item for item in self.list(namespace) if item.asset_id == asset_id and (variant is None or item.variant == variant)]
        removed = 0
        for item in matches:
            item_root = item.path.parent
            if item_root.is_symlink() or item_root.parent != self.root / namespace:
                continue
            tombstone = item_root.with_name(".delete-{}".format(uuid.uuid4()))
            os.replace(str(item_root), str(tombstone))
            shutil.rmtree(str(tombstone))
            removed += 1
        return removed

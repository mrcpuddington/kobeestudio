"""Versioned, KiCad-independent composition documents for Silk Studio."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Tuple, Union

from ..version import __version__
from .transforms import FRONT_SILKSCREEN, SUPPORTED_OUTPUT_LAYERS, is_bottom


DOCUMENT_SCHEMA_VERSION = 1
SHAPE_KINDS = (
    "rectangle",
    "circle",
    "rounded_rectangle",
    "pill",
    "custom_ends",
    "custom_long_edges",
    "pointer",
    "flag",
    "tab",
    "chamfer",
    "hexagon",
)
ALIGNMENTS = ("left", "center", "right")
DIRECTIONS = ("left", "right")
END_CAP_STYLES = ("square", "rounded", "chamfered", "point", "notch")


def _finite(name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise ValueError("{} must be finite".format(name))


def _non_negative(name: str, value: float) -> None:
    _finite(name, value)
    if value < 0:
        raise ValueError("{} must be non-negative".format(name))


@dataclass(frozen=True)
class Point:
    x: float = 0.0
    y: float = 0.0

    def __post_init__(self) -> None:
        _finite("point.x", self.x)
        _finite("point.y", self.y)


@dataclass(frozen=True)
class Size:
    width: float = 0.0
    height: float = 0.0

    def __post_init__(self) -> None:
        _non_negative("size.width", self.width)
        _non_negative("size.height", self.height)


@dataclass(frozen=True)
class Padding:
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0

    def __post_init__(self) -> None:
        for name in ("top", "right", "bottom", "left"):
            _non_negative("padding.{}".format(name), getattr(self, name))

    @classmethod
    def symmetric(cls, horizontal: float = 0.0, vertical: float = 0.0) -> "Padding":
        return cls(top=vertical, right=horizontal, bottom=vertical, left=horizontal)


@dataclass(frozen=True)
class TypographyStyle:
    font_name: str = "UbuntuMono-B"
    height_mm: float = 1.2
    width_mm: float = 0.0
    line_spacing: float = 1.5
    alignment: str = "center"

    def __post_init__(self) -> None:
        if not self.font_name:
            raise ValueError("font_name cannot be empty")
        _non_negative("typography.height_mm", self.height_mm)
        if self.height_mm == 0:
            raise ValueError("typography.height_mm must be greater than zero")
        _non_negative("typography.width_mm", self.width_mm)
        _non_negative("typography.line_spacing", self.line_spacing)
        if self.alignment not in ALIGNMENTS:
            raise ValueError("Unsupported alignment: {}".format(self.alignment))


@dataclass(frozen=True)
class ShapeStyle:
    padding: Padding = field(default_factory=lambda: Padding.symmetric(1.2, 0.5))
    border_thickness_mm: float = 0.0
    corner_radius_mm: float = 0.0
    feature_size_mm: float = 0.75
    filled: bool = True
    inverted: bool = False
    direction: str = "right"
    start_cap: str = "square"
    end_cap: str = "rounded"

    def __post_init__(self) -> None:
        _non_negative("shape.border_thickness_mm", self.border_thickness_mm)
        _non_negative("shape.corner_radius_mm", self.corner_radius_mm)
        _non_negative("shape.feature_size_mm", self.feature_size_mm)
        if self.inverted and not self.filled:
            raise ValueError("Inverted content requires a filled shape")
        if not self.filled and self.border_thickness_mm <= 0:
            raise ValueError("Outlined shapes require a positive border thickness")
        if self.direction not in DIRECTIONS:
            raise ValueError("Unsupported shape direction: {}".format(self.direction))
        if self.start_cap not in END_CAP_STYLES:
            raise ValueError("Unsupported start cap: {}".format(self.start_cap))
        if self.end_cap not in END_CAP_STYLES:
            raise ValueError("Unsupported end cap: {}".format(self.end_cap))


@dataclass(frozen=True)
class DocumentStyle:
    typography: TypographyStyle = field(default_factory=TypographyStyle)
    shape: ShapeStyle = field(default_factory=ShapeStyle)
    secondary_typography: Union[TypographyStyle, None] = None


@dataclass(frozen=True)
class TextObject:
    object_id: str
    text: str
    position: Point = field(default_factory=Point)
    rotation_deg: float = 0.0
    style_role: str = "primary"
    kind: str = field(default="text", init=False)

    def __post_init__(self) -> None:
        _validate_object_id(self.object_id)
        _finite("text.rotation_deg", self.rotation_deg)
        if not self.style_role:
            raise ValueError("Text style_role cannot be empty")


@dataclass(frozen=True)
class IconObject:
    object_id: str
    asset_id: str
    position: Point = field(default_factory=Point)
    size: Size = field(default_factory=lambda: Size(2.0, 2.0))
    rotation_deg: float = 0.0
    kind: str = field(default="icon", init=False)

    def __post_init__(self) -> None:
        _validate_object_id(self.object_id)
        if not self.asset_id:
            raise ValueError("Icon asset_id cannot be empty")
        if self.size.width <= 0 or self.size.height <= 0:
            raise ValueError("Icon size must be greater than zero")
        _finite("icon.rotation_deg", self.rotation_deg)


@dataclass(frozen=True)
class ShapeObject:
    object_id: str
    shape: str = "rectangle"
    position: Point = field(default_factory=Point)
    size: Size = field(default_factory=Size)
    rotation_deg: float = 0.0
    content_ids: Tuple[str, ...] = ()
    kind: str = field(default="shape", init=False)

    def __post_init__(self) -> None:
        _validate_object_id(self.object_id)
        if self.shape not in SHAPE_KINDS:
            raise ValueError("Unsupported shape: {}".format(self.shape))
        object.__setattr__(self, "content_ids", tuple(self.content_ids))
        _finite("shape.rotation_deg", self.rotation_deg)


@dataclass(frozen=True)
class GuideObject:
    object_id: str
    guide_type: str = "rectangle"
    position: Point = field(default_factory=Point)
    size: Size = field(default_factory=Size)
    rotation_deg: float = 0.0
    exported: bool = False
    kind: str = field(default="guide", init=False)

    def __post_init__(self) -> None:
        _validate_object_id(self.object_id)
        if not self.guide_type:
            raise ValueError("Guide type cannot be empty")
        if self.exported:
            raise ValueError("Guide objects are preview-only and cannot be exported")
        _finite("guide.rotation_deg", self.rotation_deg)


@dataclass(frozen=True)
class GroupObject:
    object_id: str
    child_ids: Tuple[str, ...]
    position: Point = field(default_factory=Point)
    rotation_deg: float = 0.0
    kind: str = field(default="group", init=False)

    def __post_init__(self) -> None:
        _validate_object_id(self.object_id)
        object.__setattr__(self, "child_ids", tuple(self.child_ids))
        if not self.child_ids:
            raise ValueError("Group objects require at least one child")
        _finite("group.rotation_deg", self.rotation_deg)


CompositionObject = Union[TextObject, IconObject, ShapeObject, GuideObject, GroupObject]


def _validate_object_id(object_id: str) -> None:
    if not object_id or not object_id.strip():
        raise ValueError("object_id cannot be empty")


@dataclass(frozen=True)
class CompositionDocument:
    objects: Tuple[CompositionObject, ...]
    output_layer: str = FRONT_SILKSCREEN
    anchor: Point = field(default_factory=Point)
    origin: Point = field(default_factory=Point)
    size: Size = field(default_factory=Size)
    rotation_deg: float = 0.0
    alignment: str = "center"
    style: DocumentStyle = field(default_factory=DocumentStyle)
    schema_version: int = DOCUMENT_SCHEMA_VERSION
    generator_version: str = __version__

    def __post_init__(self) -> None:
        object.__setattr__(self, "objects", tuple(self.objects))
        if self.schema_version != DOCUMENT_SCHEMA_VERSION:
            raise ValueError("Unsupported composition schema: {}".format(self.schema_version))
        if self.output_layer not in SUPPORTED_OUTPUT_LAYERS:
            raise ValueError("Unsupported Kobee Studio output layer: {}".format(self.output_layer))
        if self.alignment not in ALIGNMENTS:
            raise ValueError("Unsupported document alignment: {}".format(self.alignment))
        _finite("document.rotation_deg", self.rotation_deg)
        if not self.generator_version:
            raise ValueError("generator_version cannot be empty")

        object_ids = [item.object_id for item in self.objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("Composition object IDs must be unique")
        known_ids = set(object_ids)
        for item in self.objects:
            references: Iterable[str] = ()
            if isinstance(item, ShapeObject):
                references = item.content_ids
            elif isinstance(item, GroupObject):
                references = item.child_ids
            missing = set(references) - known_ids
            if missing:
                raise ValueError("{} references missing objects: {}".format(item.object_id, sorted(missing)))
            if item.object_id in references:
                raise ValueError("{} cannot reference itself".format(item.object_id))

        groups = {item.object_id: item for item in self.objects if isinstance(item, GroupObject)}

        def visit(group_id: str, active: Tuple[str, ...] = ()) -> None:
            if group_id in active:
                raise ValueError("Composition groups cannot contain a reference cycle")
            group = groups[group_id]
            for child_id in group.child_ids:
                if child_id in groups:
                    visit(child_id, active + (group_id,))

        for group_id in groups:
            visit(group_id)

    @property
    def board_side(self) -> str:
        return "bottom" if is_bottom(self.output_layer) else "front"

    def to_dict(self) -> Dict[str, Any]:
        return document_to_dict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompositionDocument":
        return document_from_dict(data)

    @classmethod
    def from_json(cls, value: str) -> "CompositionDocument":
        data = json.loads(value)
        if not isinstance(data, Mapping):
            raise ValueError("Composition JSON must contain an object")
        return document_from_dict(data)


def _point_dict(point: Point) -> Dict[str, float]:
    return {"x": point.x, "y": point.y}


def _size_dict(size: Size) -> Dict[str, float]:
    return {"width": size.width, "height": size.height}


def _padding_dict(padding: Padding) -> Dict[str, float]:
    return {
        "top": padding.top,
        "right": padding.right,
        "bottom": padding.bottom,
        "left": padding.left,
    }


def _object_to_dict(item: CompositionObject) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "kind": item.kind,
        "object_id": item.object_id,
        "position": _point_dict(item.position),
        "rotation_deg": item.rotation_deg,
    }
    if isinstance(item, TextObject):
        data.update({"text": item.text, "style_role": item.style_role})
    elif isinstance(item, IconObject):
        data.update({"asset_id": item.asset_id, "size": _size_dict(item.size)})
    elif isinstance(item, ShapeObject):
        data.update({"shape": item.shape, "size": _size_dict(item.size), "content_ids": list(item.content_ids)})
    elif isinstance(item, GuideObject):
        data.update(
            {
                "guide_type": item.guide_type,
                "size": _size_dict(item.size),
                "exported": item.exported,
            }
        )
    elif isinstance(item, GroupObject):
        data.update({"child_ids": list(item.child_ids)})
    else:  # pragma: no cover - the type union is exhaustive
        raise TypeError("Unsupported composition object: {}".format(type(item).__name__))
    return data


def document_to_dict(document: CompositionDocument) -> Dict[str, Any]:
    shape = document.style.shape
    typography = document.style.typography
    style_data = {
        "typography": {
            "font_name": typography.font_name,
            "height_mm": typography.height_mm,
            "width_mm": typography.width_mm,
            "line_spacing": typography.line_spacing,
            "alignment": typography.alignment,
        },
        "shape": {
            "padding": _padding_dict(shape.padding),
            "border_thickness_mm": shape.border_thickness_mm,
            "corner_radius_mm": shape.corner_radius_mm,
            "feature_size_mm": shape.feature_size_mm,
            "filled": shape.filled,
            "inverted": shape.inverted,
            "direction": shape.direction,
            "start_cap": shape.start_cap,
            "end_cap": shape.end_cap,
        },
    }
    if document.style.secondary_typography is not None:
        secondary = document.style.secondary_typography
        style_data["secondary_typography"] = {
            "font_name": secondary.font_name,
            "height_mm": secondary.height_mm,
            "width_mm": secondary.width_mm,
            "line_spacing": secondary.line_spacing,
            "alignment": secondary.alignment,
        }
    return {
        "schema_version": document.schema_version,
        "generator_version": document.generator_version,
        "output_layer": document.output_layer,
        "anchor": _point_dict(document.anchor),
        "origin": _point_dict(document.origin),
        "size": _size_dict(document.size),
        "rotation_deg": document.rotation_deg,
        "alignment": document.alignment,
        "style": style_data,
        "objects": [_object_to_dict(item) for item in document.objects],
    }


def _point_from(data: Mapping[str, Any]) -> Point:
    return Point(float(data.get("x", 0.0)), float(data.get("y", 0.0)))


def _size_from(data: Mapping[str, Any]) -> Size:
    return Size(float(data.get("width", 0.0)), float(data.get("height", 0.0)))


def _padding_from(data: Mapping[str, Any]) -> Padding:
    return Padding(
        top=float(data.get("top", 0.0)),
        right=float(data.get("right", 0.0)),
        bottom=float(data.get("bottom", 0.0)),
        left=float(data.get("left", 0.0)),
    )


def _object_from_dict(data: Mapping[str, Any]) -> CompositionObject:
    kind = str(data.get("kind", ""))
    common = {
        "object_id": str(data.get("object_id", "")),
        "position": _point_from(data.get("position", {})),
        "rotation_deg": float(data.get("rotation_deg", 0.0)),
    }
    if kind == "text":
        return TextObject(text=str(data.get("text", "")), style_role=str(data.get("style_role", "primary")), **common)
    if kind == "icon":
        return IconObject(asset_id=str(data.get("asset_id", "")), size=_size_from(data.get("size", {})), **common)
    if kind == "shape":
        return ShapeObject(
            shape=str(data.get("shape", "rectangle")),
            size=_size_from(data.get("size", {})),
            content_ids=tuple(str(value) for value in data.get("content_ids", ())),
            **common
        )
    if kind == "guide":
        return GuideObject(
            guide_type=str(data.get("guide_type", "rectangle")),
            size=_size_from(data.get("size", {})),
            exported=bool(data.get("exported", False)),
            **common
        )
    if kind == "group":
        return GroupObject(child_ids=tuple(str(value) for value in data.get("child_ids", ())), **common)
    raise ValueError("Unsupported composition object kind: {}".format(kind))


def document_from_dict(data: Mapping[str, Any]) -> CompositionDocument:
    schema_version = int(data.get("schema_version", 0))
    if schema_version != DOCUMENT_SCHEMA_VERSION:
        raise ValueError("Unsupported composition schema: {}".format(schema_version))

    style_data = data.get("style", {})
    typography_data = style_data.get("typography", {})
    secondary_typography_data = style_data.get("secondary_typography")
    shape_data = style_data.get("shape", {})
    style = DocumentStyle(
        typography=TypographyStyle(
            font_name=str(typography_data.get("font_name", "UbuntuMono-B")),
            height_mm=float(typography_data.get("height_mm", 2.0)),
            width_mm=float(typography_data.get("width_mm", 0.0)),
            line_spacing=float(typography_data.get("line_spacing", 1.5)),
            alignment=str(typography_data.get("alignment", "center")).lower(),
        ),
        secondary_typography=(
            TypographyStyle(
                font_name=str(secondary_typography_data.get("font_name", "UbuntuMono-B")),
                height_mm=float(secondary_typography_data.get("height_mm", 1.0)),
                width_mm=float(secondary_typography_data.get("width_mm", 0.0)),
                line_spacing=float(secondary_typography_data.get("line_spacing", 1.2)),
                alignment=str(secondary_typography_data.get("alignment", "center")).lower(),
            )
            if isinstance(secondary_typography_data, Mapping)
            else None
        ),
        shape=ShapeStyle(
            padding=_padding_from(shape_data.get("padding", {})),
            border_thickness_mm=float(shape_data.get("border_thickness_mm", 0.0)),
            corner_radius_mm=float(shape_data.get("corner_radius_mm", 0.0)),
            feature_size_mm=float(shape_data.get("feature_size_mm", 0.75)),
            filled=bool(shape_data.get("filled", True)),
            inverted=bool(shape_data.get("inverted", False)),
            direction=str(shape_data.get("direction", "right")),
            start_cap=str(shape_data.get("start_cap", "square")),
            end_cap=str(shape_data.get("end_cap", "rounded")),
        ),
    )
    return CompositionDocument(
        objects=tuple(_object_from_dict(item) for item in data.get("objects", ())),
        output_layer=str(data.get("output_layer", FRONT_SILKSCREEN)),
        anchor=_point_from(data.get("anchor", {})),
        origin=_point_from(data.get("origin", {})),
        size=_size_from(data.get("size", {})),
        rotation_deg=float(data.get("rotation_deg", 0.0)),
        alignment=str(data.get("alignment", "center")).lower(),
        style=style,
        schema_version=schema_version,
        generator_version=str(data.get("generator_version", "unknown")),
    )

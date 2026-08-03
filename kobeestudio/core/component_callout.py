"""Pure data model for component-centred PCB callouts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

from ..version import __version__
from .composition import DocumentStyle
from .transforms import FRONT_SILKSCREEN, SUPPORTED_OUTPUT_LAYERS


COMPONENT_CALLOUT_SCHEMA_VERSION = 1
COMPONENT_POSITIONS = ("left", "right", "above", "below")
CUTOUT_SHAPES = ("rectangle", "rounded_rectangle", "pill", "tactile_switch")
ARRAY_ORIENTATIONS = ("vertical", "horizontal")


@dataclass(frozen=True)
class ComponentPreset:
    preset_id: str
    label: str
    width_mm: float
    height_mm: float
    cutout_shape: str = "rounded_rectangle"
    cutout_radius_mm: float = 0.2


# These are conservative artwork exclusion envelopes derived from representative
# manufacturer land patterns. They are starting points, not universal courtyard
# dimensions: real footprints remain authoritative and every value is editable.
COMPONENT_PRESETS: Tuple[ComponentPreset, ...] = (
    ComponentPreset("0402", "0402 / 1005 metric", 1.6, 0.8),
    ComponentPreset("0603", "0603 / 1608 metric", 2.2, 1.1),
    ComponentPreset("0805", "0805 / 2012 metric", 3.4, 1.5),
    ComponentPreset("1206", "1206 / 3216 metric", 4.5, 1.9),
    ComponentPreset("1210", "1210 / 3225 metric", 4.5, 2.9),
    ComponentPreset("sot23", "SOT-23", 3.2, 2.8),
    ComponentPreset("soic8", "SOIC-8", 6.2, 5.4),
    ComponentPreset("qfn32_5", "QFN-32 (5 × 5 mm)", 5.6, 5.6),
    ComponentPreset(
        "tactile_6",
        "Tactile switch (6 × 6 mm)",
        8.0,
        7.0,
        cutout_shape="rounded_rectangle",
        cutout_radius_mm=0.7,
    ),
)
COMPONENT_PRESET_BY_ID = {item.preset_id: item for item in COMPONENT_PRESETS}


def _positive(name: str, value: float) -> None:
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError("{} must be greater than zero".format(name))


def _non_negative(name: str, value: float) -> None:
    if not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError("{} must be non-negative".format(name))


@dataclass(frozen=True)
class ComponentCalloutSpec:
    title: str
    subtitle: str = ""
    preset_id: str = "custom"
    component_width_mm: float = 2.2
    component_height_mm: float = 1.1
    component_clearance_mm: float = 0.3
    cutout_shape: str = "rounded_rectangle"
    cutout_radius_mm: float = 0.7
    component_position: str = "left"
    component_to_text_gap_mm: float = 2.6
    array_count: int = 1
    array_orientation: str = "vertical"
    array_pitch_mm: float = 5.0
    subtitle_gap_mm: float = 0.25
    minimum_width_mm: float = 0.0
    minimum_height_mm: float = 0.0
    shape: str = "rounded_rectangle"
    output_layer: str = FRONT_SILKSCREEN
    style: DocumentStyle = field(default_factory=DocumentStyle)
    schema_version: int = COMPONENT_CALLOUT_SCHEMA_VERSION
    generator_version: str = __version__

    def __post_init__(self) -> None:
        if self.schema_version != COMPONENT_CALLOUT_SCHEMA_VERSION:
            raise ValueError("Unsupported component-callout schema: {}".format(self.schema_version))
        if not self.title.strip() and not self.subtitle.strip():
            raise ValueError("A component callout needs title or subtitle text")
        _positive("component_width_mm", self.component_width_mm)
        _positive("component_height_mm", self.component_height_mm)
        _positive("array_pitch_mm", self.array_pitch_mm)
        if int(self.array_count) != self.array_count or not 1 <= int(self.array_count) <= 16:
            raise ValueError("array_count must be between 1 and 16")
        if self.array_orientation not in ARRAY_ORIENTATIONS:
            raise ValueError("Unsupported component-array orientation: {}".format(self.array_orientation))
        if self.array_count > 1:
            rows = self.title.splitlines()
            if len(rows) != self.array_count or any(not row.strip() for row in rows):
                raise ValueError("Enter exactly {} component labels, one per line".format(self.array_count))
            if self.subtitle.strip():
                raise ValueError("Component arrays use one label per component; subtitles are not supported")
        for name in (
            "component_clearance_mm",
            "cutout_radius_mm",
            "component_to_text_gap_mm",
            "subtitle_gap_mm",
            "minimum_width_mm",
            "minimum_height_mm",
        ):
            _non_negative(name, getattr(self, name))
        if self.cutout_shape not in CUTOUT_SHAPES:
            raise ValueError("Unsupported component cutout shape: {}".format(self.cutout_shape))
        if self.component_position not in COMPONENT_POSITIONS:
            raise ValueError("Unsupported component position: {}".format(self.component_position))
        if self.output_layer not in SUPPORTED_OUTPUT_LAYERS:
            raise ValueError("Unsupported Kobee Studio output layer: {}".format(self.output_layer))

    @property
    def cutout_width_mm(self) -> float:
        return self.component_width_mm + 2.0 * self.component_clearance_mm

    @property
    def cutout_height_mm(self) -> float:
        return self.component_height_mm + 2.0 * self.component_clearance_mm

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "title": self.title,
            "subtitle": self.subtitle,
            "preset_id": self.preset_id,
            "component_width_mm": self.component_width_mm,
            "component_height_mm": self.component_height_mm,
            "component_clearance_mm": self.component_clearance_mm,
            "cutout_shape": self.cutout_shape,
            "cutout_radius_mm": self.cutout_radius_mm,
            "component_position": self.component_position,
            "component_to_text_gap_mm": self.component_to_text_gap_mm,
            "array_count": self.array_count,
            "array_orientation": self.array_orientation,
            "array_pitch_mm": self.array_pitch_mm,
            "subtitle_gap_mm": self.subtitle_gap_mm,
            "minimum_width_mm": self.minimum_width_mm,
            "minimum_height_mm": self.minimum_height_mm,
            "shape": self.shape,
            "output_layer": self.output_layer,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], style: DocumentStyle = None) -> "ComponentCalloutSpec":
        # The embedded composition document remains the authoritative style;
        # callers reopening a feature pass that document style here.
        return cls(
            title=str(data.get("title", "")),
            subtitle=str(data.get("subtitle", "")),
            preset_id=str(data.get("preset_id", "custom")),
            component_width_mm=float(data.get("component_width_mm", 2.2)),
            component_height_mm=float(data.get("component_height_mm", 1.1)),
            component_clearance_mm=float(data.get("component_clearance_mm", 0.3)),
            cutout_shape=str(data.get("cutout_shape", "rounded_rectangle")),
            cutout_radius_mm=float(data.get("cutout_radius_mm", 0.7)),
            component_position=str(data.get("component_position", "left")),
            component_to_text_gap_mm=float(data.get("component_to_text_gap_mm", 2.6)),
            array_count=int(data.get("array_count", 1)),
            array_orientation=str(data.get("array_orientation", "vertical")),
            array_pitch_mm=float(data.get("array_pitch_mm", 5.0)),
            subtitle_gap_mm=float(data.get("subtitle_gap_mm", 0.25)),
            minimum_width_mm=float(data.get("minimum_width_mm", 0.0)),
            minimum_height_mm=float(data.get("minimum_height_mm", 0.0)),
            shape=str(data.get("shape", "rounded_rectangle")),
            output_layer=str(data.get("output_layer", FRONT_SILKSCREEN)),
            style=style or DocumentStyle(),
            schema_version=int(data.get("schema_version", COMPONENT_CALLOUT_SCHEMA_VERSION)),
            generator_version=str(data.get("generator_version", "unknown")),
        )

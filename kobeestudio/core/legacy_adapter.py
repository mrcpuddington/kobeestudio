"""Compatibility adapter between the current dialog and composition documents."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from ..version import __version__
from .composition import (
    CompositionDocument,
    DocumentStyle,
    GroupObject,
    Padding,
    ShapeObject,
    ShapeStyle,
    Size,
    TextObject,
    TypographyStyle,
)
from .transforms import FRONT_SILKSCREEN, SUPPORTED_OUTPUT_LAYERS


FOOTPRINT_PAYLOAD_FORMAT = "kobee-studio-composition"


def _float(settings: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(settings.get(key, default))
    except (TypeError, ValueError):
        return default


def _canonical_layer(value: Any) -> str:
    layer = str(value or FRONT_SILKSCREEN)
    if layer in SUPPORTED_OUTPUT_LAYERS:
        return layer
    match = re.search(r"\(([^()]+)\)\s*$", layer)
    if match and match.group(1) in SUPPORTED_OUTPUT_LAYERS:
        return match.group(1)
    return FRONT_SILKSCREEN


def _alignment(value: Any) -> str:
    alignment = str(value or "center").lower()
    return alignment if alignment in ("left", "center", "right") else "center"


def _legacy_shape(settings: Mapping[str, Any]) -> str:
    left = str(settings.get("CapLeftChoice", ""))
    right = str(settings.get("CapRightChoice", ""))
    if left == "(" and right == ")":
        return "pill"
    if left or right:
        return "custom_ends"
    return "rectangle"


def document_from_legacy_settings(settings: Mapping[str, Any]) -> CompositionDocument:
    """Create the first versioned document without changing legacy output."""
    text = TextObject("text.primary", str(settings.get("MultiLineText", "")))
    objects = [text]
    left_cap = str(settings.get("CapLeftChoice", ""))
    right_cap = str(settings.get("CapRightChoice", ""))
    has_background = bool(left_cap or right_cap)
    if has_background:
        shape = ShapeObject(
            "shape.background",
            shape=_legacy_shape(settings),
            size=Size(max(0.0, _float(settings, "WidthCtrl")), 0.0),
            content_ids=(text.object_id,),
        )
        objects.append(shape)
        objects.append(GroupObject("group.label", (shape.object_id, text.object_id)))

    padding = Padding(
        top=max(0.0, _float(settings, "PaddingTopCtrl", 0.001)),
        right=max(0.0, _float(settings, "PaddingRightCtrl", 0.001)),
        bottom=max(0.0, _float(settings, "PaddingBottomCtrl", 0.001)),
        left=max(0.0, _float(settings, "PaddingLeftCtrl", 0.001)),
    )
    style = DocumentStyle(
        typography=TypographyStyle(
            font_name=str(settings.get("FontComboBox", "UbuntuMono-B")),
            height_mm=max(0.001, _float(settings, "HeightCtrl", 2.0)),
            width_mm=max(0.0, _float(settings, "WidthCtrl", 0.0)),
            line_spacing=max(0.0, _float(settings, "LineSpacingCtrl", 1.5)),
            alignment=_alignment(settings.get("AlignmentChoice", "center")),
        ),
        shape=ShapeStyle(
            padding=padding,
            corner_radius_mm=0.0,
            filled=has_background,
            inverted=has_background,
            border_thickness_mm=0.0 if has_background else 0.15,
            start_cap="rounded" if left_cap == "(" else "square",
            end_cap="rounded" if right_cap == ")" else "square",
        ),
    )
    return CompositionDocument(
        objects=tuple(objects),
        output_layer=_canonical_layer(settings.get("LayerComboBox")),
        alignment=style.typography.alignment,
        style=style,
        generator_version=__version__,
    )


def build_footprint_payload(
    settings: Mapping[str, Any],
    document: Optional[CompositionDocument] = None,
    feature: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Embed both the new document and old settings during the migration."""
    legacy_settings = dict(settings)
    payload = {
        "format": FOOTPRINT_PAYLOAD_FORMAT,
        "schema_version": 1,
        "generator_version": __version__,
        "document": (document or document_from_legacy_settings(legacy_settings)).to_dict(),
        "legacy_settings": legacy_settings,
    }
    if feature is not None:
        payload["feature"] = dict(feature)
    return payload


def legacy_settings_from_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Open both historical flat settings and new composition payloads."""
    if payload.get("format") == FOOTPRINT_PAYLOAD_FORMAT:
        settings = payload.get("legacy_settings", {})
        if not isinstance(settings, Mapping):
            raise ValueError("Kobee Studio footprint legacy_settings must be an object")
        return dict(settings)
    return dict(payload)

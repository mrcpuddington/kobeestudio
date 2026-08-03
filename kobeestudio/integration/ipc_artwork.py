"""Convert shared Kobee Studio geometry into KiCad IPC footprint items."""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from ..core.shape_geometry import Point, Polygon, polygon_bounds
from ..core.studio_artwork import StudioArtwork, StrokePath
from ..core.transforms import SUPPORTED_OUTPUT_LAYERS, is_bottom
from .ipc_session import IpcSession, IpcUnavailableError


METADATA_FIELD_NAME = "KOBEE_STUDIO_DATA"


@dataclass(frozen=True)
class IpcPolygon:
    points: Polygon
    filled: bool
    stroke_width_mm: float = 0.0


def _mirror_polygon(polygon: Polygon) -> Polygon:
    return tuple(Point(-point.x, point.y) for point in reversed(polygon))


def artwork_polygons(artwork: StudioArtwork, output_layer: str) -> Tuple[IpcPolygon, ...]:
    """Return the exact filled/stroked polygons the IPC footprint must contain."""
    if output_layer not in SUPPORTED_OUTPUT_LAYERS:
        raise ValueError("Unsupported Kobee Studio output layer: {}".format(output_layer))

    mirror = is_bottom(output_layer)

    def transform(polygon: Polygon) -> Polygon:
        return _mirror_polygon(polygon) if mirror else polygon

    primitives = [
        IpcPolygon(transform(polygon), filled=True)
        for polygon in artwork.filled_polygons
        if len(polygon) >= 3
    ]
    primitives.extend(
        IpcPolygon(
            transform(stroke.points),
            filled=False,
            stroke_width_mm=stroke.width_mm,
        )
        for stroke in artwork.strokes
        if len(stroke.points) >= 3
    )
    if not primitives:
        raise ValueError("Kobee Studio artwork is empty")
    return tuple(primitives)


def encode_metadata(payload: Mapping[str, Any]) -> str:
    data = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(data).decode("ascii")


def decode_metadata(value: str) -> Mapping[str, Any]:
    return json.loads(base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8"))


def selected_artwork(selection: Sequence[Any]):
    """Return settings and the selected IPC footprint, if exactly one is ours."""
    if len(selection) != 1:
        return None
    footprint = selection[0]
    definition = getattr(footprint, "definition", None)
    if definition is None:
        return None
    for item in getattr(definition, "items", ()):
        if getattr(item, "name", "") != METADATA_FIELD_NAME:
            continue
        text = getattr(item, "text", None)
        value = getattr(text, "value", "") if text is not None else ""
        try:
            payload = decode_metadata(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        settings = payload.get("legacy_settings", {})
        if not isinstance(settings, Mapping):
            return None
        loaded = dict(settings)
        loaded["_LoadedFootprintSettings"] = True
        return loaded, footprint
    return None


def selected_legacy_artwork(selection: Sequence[Any], selection_sexpr: str):
    """Open a selected 1.2.x SWIG footprint through IPC's text export.

    Released SWIG footprints store the same base64 payload in their `tags`
    field. kicad-python 0.7 does not expose footprint tags directly, but KiCad
    10 can serialise the current selection without using deprecated bindings.
    """
    if len(selection) != 1:
        return None
    match = re.search(r'\(tags\s+"kb_params=([^"\s]+)"\)', selection_sexpr)
    if match is None:
        return None
    try:
        payload = decode_metadata(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("format") == "kobee-studio-composition":
        settings = payload.get("legacy_settings", {})
    else:
        settings = payload
    if not isinstance(settings, Mapping):
        return None
    loaded = dict(settings)
    loaded["_LoadedFootprintSettings"] = True
    return loaded, selection[0]


class IpcArtworkPlacement:
    """Create or replace one Kobee Studio footprint through kicad-python."""

    def __init__(self, session: IpcSession):
        self.session = session

    @staticmethod
    def _api():
        try:
            from kipy.board_types import BoardPolygon, Field, Footprint, FootprintInstance
            from kipy.geometry import PolyLineNode, PolygonWithHoles, Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util import from_mm
        except ImportError as error:
            raise IpcUnavailableError(
                "The installed kicad-python package is incomplete: {}".format(error)
            ) from error
        return {
            "BoardPolygon": BoardPolygon,
            "Field": Field,
            "Footprint": Footprint,
            "FootprintInstance": FootprintInstance,
            "PolyLineNode": PolyLineNode,
            "PolygonWithHoles": PolygonWithHoles,
            "Vector2": Vector2,
            "BoardLayer": BoardLayer,
            "from_mm": from_mm,
        }

    @staticmethod
    def _layer(api, output_layer: str):
        layer = api["BoardLayer"]
        return {
            "F.Cu": layer.BL_F_Cu,
            "B.Cu": layer.BL_B_Cu,
            "F.SilkS": layer.BL_F_SilkS,
            "B.SilkS": layer.BL_B_SilkS,
            "F.Mask": layer.BL_F_Mask,
            "B.Mask": layer.BL_B_Mask,
        }[output_layer]

    @staticmethod
    def _owner_layer(api, output_layer: str):
        layer = api["BoardLayer"]
        return layer.BL_B_Cu if is_bottom(output_layer) else layer.BL_F_Cu

    def _polygon_item(self, api, primitive: IpcPolygon, output_layer: str):
        shape = api["BoardPolygon"]()
        shape.layer = self._layer(api, output_layer)
        shape.attributes.fill.filled = primitive.filled
        shape.attributes.stroke.width = api["from_mm"](
            0.0 if primitive.filled else max(0.001, primitive.stroke_width_mm)
        )
        polygon = api["PolygonWithHoles"]()
        for point in primitive.points:
            polygon.outline.append(
                api["PolyLineNode"].from_point(
                    api["Vector2"].from_xy_mm(point.x, point.y)
                )
            )
        polygon.outline.closed = True
        shape.polygons.append(polygon)
        return shape

    def build_footprint(
        self,
        artwork: StudioArtwork,
        payload: Mapping[str, Any],
        output_layer: str,
    ):
        api = self._api()
        name = "kobee-studio-{:08X}".format(int(round(time.time())))
        footprint = api["FootprintInstance"]()
        definition = footprint.definition
        definition.id.name = name
        for primitive in artwork_polygons(artwork, output_layer):
            definition.add_item(self._polygon_item(api, primitive, output_layer))

        metadata = api["Field"]()
        metadata.name = METADATA_FIELD_NAME
        metadata.layer = self._layer(api, output_layer)
        metadata.text.value = encode_metadata(payload)
        metadata.visible = False
        definition.add_item(metadata)

        footprint.layer = self._owner_layer(api, output_layer)
        footprint.attributes.not_in_schematic = True
        footprint.attributes.exclude_from_bill_of_materials = True
        footprint.attributes.exclude_from_position_files = True
        footprint.reference_field.name = "Reference"
        footprint.reference_field.text.value = name
        footprint.reference_field.visible = False
        footprint.value_field.name = "Value"
        footprint.value_field.text.value = "Kobee Studio"
        footprint.value_field.visible = False
        return footprint

    def _default_position(self, api):
        # Match the current plugin's predictable fallback. A later placement
        # milestone can ask KiCad to attach the new footprint to the cursor.
        return api["Vector2"].from_xy_mm(100.0, 100.0)

    def place(
        self,
        artwork: StudioArtwork,
        payload: Mapping[str, Any],
        output_layer: str,
        old_footprint: Optional[Any] = None,
    ):
        api = self._api()
        footprint = self.build_footprint(artwork, payload, output_layer)
        if old_footprint is not None:
            footprint.position = old_footprint.position
            footprint.orientation = old_footprint.orientation
        else:
            footprint.position = self._default_position(api)

        transaction = self.session.begin_commit()
        try:
            created = self.session.board.create_items(footprint)
            if old_footprint is not None:
                self.session.board.remove_items(old_footprint)
            self.session.commit(
                transaction,
                "Update Kobee Studio artwork" if old_footprint is not None else "Place Kobee Studio artwork",
            )
        except Exception:
            self.session.discard(transaction)
            raise

        placed = created[0] if created else None
        if placed is not None:
            try:
                self.session.board.add_to_selection(placed)
            except Exception:
                # Selection is convenience only; placement has already succeeded.
                pass
        return placed

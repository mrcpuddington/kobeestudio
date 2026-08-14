"""Convert shared Kobee Studio geometry into KiCad IPC footprint items."""

from __future__ import annotations

import base64
import json
import re
import uuid
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


def _translate_polygon(polygon: Polygon, offset: Point) -> Polygon:
    return tuple(Point(point.x + offset.x, point.y + offset.y) for point in polygon)


def artwork_polygons(
    artwork: StudioArtwork,
    output_layer: str,
    offset: Point | None = None,
) -> Tuple[IpcPolygon, ...]:
    """Return the exact filled/stroked polygons the IPC footprint must contain."""
    if output_layer not in SUPPORTED_OUTPUT_LAYERS:
        raise ValueError("Unsupported Kobee Studio output layer: {}".format(output_layer))

    mirror = is_bottom(output_layer)
    offset = offset or Point()

    def transform(polygon: Polygon) -> Polygon:
        transformed = _mirror_polygon(polygon) if mirror else polygon
        return _translate_polygon(transformed, offset)

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

    @staticmethod
    def _artwork_origin(artwork: StudioArtwork, output_layer: str) -> Point:
        origin = artwork.document.origin
        return Point(-origin.x, origin.y) if is_bottom(output_layer) else origin

    @classmethod
    def _artwork_offset(cls, artwork: StudioArtwork, output_layer: str) -> Point:
        origin = cls._artwork_origin(artwork, output_layer)
        return Point(-origin.x, -origin.y)

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
        output_layers: Optional[Sequence[str]] = None,
    ):
        layers = tuple(dict.fromkeys(output_layers or (output_layer,)))
        if not layers or any(layer not in SUPPORTED_OUTPUT_LAYERS for layer in layers):
            raise ValueError("Kobee Studio requires one or more supported output layers")
        if output_layer not in layers:
            output_layer = layers[0]
        api = self._api()
        # A second-resolution name caused every item in a bulk designator
        # operation to share one footprint-library identity.  KiCad accepts
        # the create request but can subsequently coalesce/drop those board
        # definitions.  Give every new definition an unambiguous identity.
        name = "kobee-studio-{}".format(uuid.uuid4().hex[:12])
        footprint = api["FootprintInstance"]()
        definition = footprint.definition
        definition.id.name = name
        for layer in layers:
            for primitive in artwork_polygons(
                artwork,
                layer,
                offset=self._artwork_offset(artwork, layer),
            ):
                definition.add_item(self._polygon_item(api, primitive, layer))

        metadata = api["Field"]()
        metadata.name = METADATA_FIELD_NAME
        metadata.layer = self._layer(api, output_layer)
        metadata.text.value = encode_metadata(payload)
        metadata.visible = False
        definition.add_item(metadata)

        owner_target = next((layer for layer in layers if not is_bottom(layer)), layers[0])
        footprint.layer = self._owner_layer(api, owner_target)
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

    def place(
        self,
        artwork: StudioArtwork,
        payload: Mapping[str, Any],
        output_layer: str,
        output_layers: Optional[Sequence[str]] = None,
        old_footprint: Optional[Any] = None,
        start_interactive_move: bool = True,
    ):
        api = self._api()
        footprint = self.build_footprint(artwork, payload, output_layer, output_layers=output_layers)
        if old_footprint is not None:
            # KiCad matches the top-level item by UUID, but preserving the
            # existing footprint definition identity avoids replacing an
            # edited board item with a logically new shell that can momentarily
            # drop out of the workspace on some edit paths.
            try:
                footprint.definition.proto.id.CopyFrom(old_footprint.definition.proto.id)
            except Exception:
                pass
            footprint.position = old_footprint.position
            footprint.orientation = old_footprint.orientation
            # KiCad updates board items by UUID. Preserve the selected
            # footprint's identity so this is a true in-place replacement.
            footprint.proto.id.CopyFrom(old_footprint.id)
            try:
                footprint.locked = old_footprint.locked
            except Exception:
                pass

        transaction = self.session.begin_commit()
        try:
            if old_footprint is not None:
                created = self.session.board.update_items(footprint)
            else:
                created = self.session.board.create_items(footprint)
            self.session.commit(
                transaction,
                "Update Kobee Studio artwork" if old_footprint is not None else "Place Kobee Studio artwork",
            )
        except Exception:
            self.session.discard(transaction)
            raise

        placed = created[0] if created else None
        if placed is not None and old_footprint is not None:
            try:
                self.session.board.add_to_selection(placed)
            except Exception:
                # Selection is convenience only; placement has already succeeded.
                pass
        if placed is not None and old_footprint is None and start_interactive_move:
            self.start_interactive_move(placed)
        return placed

    def start_interactive_move(self, placed: Any) -> None:
        """Attach a committed footprint after the plugin modal has closed."""
        try:
            self.session.board.add_to_selection(placed)
        except Exception:
            # Selection is convenience only; placement has already succeeded.
            pass
        self.session.board.interactive_move(placed.id)

    @staticmethod
    def _angle_from_degrees(value: float):
        try:
            from kipy.geometry import Angle
        except ImportError as error:
            raise IpcUnavailableError("The installed kicad-python package is incomplete") from error
        return Angle.from_degrees(float(value))

    def place_designators(self, records: Sequence[Tuple[Any, StudioArtwork, Mapping[str, Any], str, Optional[Any]]]):
        """Create/update linked designators, verify them, then hide native fields.

        KiCad does not expose uncommitted items through ``get_items_by_id``.
        Replacements are therefore committed and read back before the native
        references are touched.  A failed verification leaves the semantic
        reference visible instead of producing a blank board.
        """
        creates, updates, sources = [], [], []
        original_visibility = []
        for source, artwork, payload, output_layer, existing in records:
            footprint = self.build_footprint(artwork, payload, output_layer)
            footprint.position = source.reference_field.text.position
            footprint.orientation = self._angle_from_degrees(source.reference_field.text.attributes.angle)
            if existing is not None:
                footprint.proto.id.CopyFrom(existing.id)
                try: footprint.definition.proto.id.CopyFrom(existing.definition.proto.id)
                except Exception: pass
                updates.append(footprint)
            else:
                creates.append(footprint)
            sources.append(source)
            original_visibility.append(bool(source.reference_field.visible))
        artwork_transaction = self.session.begin_commit()
        replacements = []
        try:
            if creates:
                created_result = self.session.board.create_items(creates)
                if len(created_result or ()) != len(creates):
                    raise RuntimeError("KiCad did not create every designator; the operation was rolled back")
                replacements.extend(created_result)
            if updates:
                updated_result = self.session.board.update_items(updates)
                if len(updated_result or ()) != len(updates):
                    raise RuntimeError("KiCad did not update every designator; the operation was rolled back")
                replacements.extend(updated_result)
            self.session.commit(artwork_transaction, "Create Kobee Studio designators")
        except Exception:
            self.session.discard(artwork_transaction)
            raise

        # The response proves only that KiCad accepted each command.  Read the
        # committed board objects back and require at least one real geometry
        # primitive in every generated footprint before hiding anything.
        try:
            replacement_ids = [item.id for item in replacements]
            read_back = (
                tuple(self.session.board.get_items_by_id(replacement_ids))
                if replacement_ids and hasattr(self.session.board, "get_items_by_id")
                else tuple(replacements)
            )
            if len(read_back) != len(replacements):
                raise RuntimeError("KiCad did not retain every generated designator")
            for replacement in read_back:
                visible_items = tuple(
                    item for item in getattr(replacement.definition, "items", ())
                    if getattr(item, "name", "") != METADATA_FIELD_NAME
                )
                if not visible_items:
                    raise RuntimeError("KiCad retained a designator without any visible geometry")
        except Exception as error:
            # Do not remove a pre-existing designator update here: the central
            # safety guarantee is that native references remain unchanged.
            raise RuntimeError(
                "Generated designators could not be verified on the board. Native references were left visible: {}".format(error)
            )

        reference_transaction = self.session.begin_commit()
        try:
            for source in sources:
                source.reference_field.visible = False
            source_result = self.session.board.update_items(sources)
            if len(source_result or ()) != len(sources):
                raise RuntimeError("KiCad did not update every source footprint; native references were restored")
            self.session.commit(reference_transaction, "Hide native footprint references")
        except Exception:
            for source, visible in zip(sources, original_visibility):
                source.reference_field.visible = visible
            self.session.discard(reference_transaction)
            raise
        return len(creates), len(updates)

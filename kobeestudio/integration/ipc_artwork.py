"""Convert shared Kobee Studio geometry into KiCad IPC footprint items."""

from __future__ import annotations

import base64
import json
import re
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from ..core.composition import ShapeObject
from ..core.shape_geometry import Point, Polygon, polygon_bounds, shape_contour
from ..core.studio_artwork import StudioArtwork, StrokePath
from ..core.transforms import SUPPORTED_OUTPUT_LAYERS, is_bottom
from .ipc_session import IpcSession, IpcUnavailableError


METADATA_FIELD_NAME = "KOBEE_STUDIO_DATA"
DESIGNATOR_METADATA_FIELD_NAME = "KOBEE_DESIGNATOR_DATA"


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
        if not isinstance(payload, Mapping):
            return None
        settings = payload.get("legacy_settings", {})
        if not isinstance(settings, Mapping):
            return None
        loaded = dict(settings)
        feature = payload.get("feature", {})
        # Variable labels must always reopen through the Variables editor.
        # Early IPC builds recorded the variable expression under feature
        # metadata but did not always include StudioTool in legacy settings.
        # Retain the original ${...} expression so the preview can resolve it
        # against the active project and placement stays live in KiCad.
        if isinstance(feature, Mapping) and feature.get("kind") == "variable_label":
            template = feature.get("template")
            if isinstance(template, str) and template.strip():
                loaded["VariableTemplateText"] = template
            loaded["StudioTool"] = "Variables"
            loaded["StudioModeChoice"] = "Label"
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

    def _discard_or_report_unknown_state(self, transaction, operation_error: Exception) -> None:
        """Discard a failed edit without hiding an unconfirmed rollback.

        If KiCad has disconnected, ``drop_commit`` can fail too.  In that
        case the board may or may not contain part of the operation, so the
        caller must not present it as a normal failed placement.
        """
        try:
            self.session.discard(transaction)
        except Exception as discard_error:
            raise IpcUnavailableError(
                "KiCad rejected the operation and Kobee could not confirm its rollback. "
                "Check the board, then reopen it before retrying: {}".format(discard_error)
            ) from operation_error

    @staticmethod
    def _api():
        try:
            from kipy.board_types import BoardPolygon, BoardText, Field, Footprint, FootprintInstance
            from kipy.geometry import PolyLineNode, PolygonWithHoles, Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.proto.common import types as common_types
            from kipy.util import from_mm
        except ImportError as error:
            raise IpcUnavailableError(
                "The installed kicad-python package is incomplete: {}".format(error)
            ) from error
        return {
            "BoardPolygon": BoardPolygon,
            "BoardText": BoardText,
            "Field": Field,
            "Footprint": Footprint,
            "FootprintInstance": FootprintInstance,
            "PolyLineNode": PolyLineNode,
            "PolygonWithHoles": PolygonWithHoles,
            "Vector2": Vector2,
            "BoardLayer": BoardLayer,
            "CommonTypes": common_types,
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

    def _configure_hidden_field(self, api, field, output_layer, size_mm=1.0):
        # Zero-sized protobuf defaults are accepted by CreateItems, but KiCad's
        # native Footprint Properties dialog cannot save them (even hidden
        # fields). Keep every field valid so changing X/Y needs no repairs.
        field.layer = self._layer(api, output_layer)
        field.visible = False
        field.text.attributes.size = api["Vector2"].from_xy_mm(size_mm, size_mm)
        field.text.attributes.stroke_width = api["from_mm"](size_mm * 0.15)

    def _configure_standard_fields(self, api, footprint, output_layer):
        for attribute, name in (("reference_field", "Reference"), ("value_field", "Value"),
                                ("datasheet_field", "Datasheet"), ("description_field", "Description")):
            field = getattr(footprint, attribute)
            field.name = name
            self._configure_hidden_field(api, field, output_layer)

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
        # kicad-python's Polygon wrapper stores appended polygons in a private
        # list and does not pack that list when BoardGraphicShape.proto is
        # accessed.  Without this explicit pack/re-wrap, KiCad receives a
        # footprint child with an empty ``polygon {}`` message: the footprint
        # exists but renders nothing.  Re-wrapping also makes later footprint
        # move/rotation operations mutate the packed protobuf in place.
        shape._pack()
        return api["BoardPolygon"](shape.proto)

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
        self._configure_hidden_field(api, metadata, output_layer, size_mm=0.1)
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
        self._configure_standard_fields(api, footprint, output_layer)
        return footprint

    def build_variable_footprint(
        self,
        settings: Mapping[str, Any],
        payload: Mapping[str, Any],
        output_layer: str,
        output_layers: Optional[Sequence[str]] = None,
        container_artwork: Optional[StudioArtwork] = None,
    ):
        """Build a footprint containing native KiCad ``${VARIABLE}`` text.

        The polygon renderer is used only for the editor preview.  Keeping the
        original expression in BoardText is what lets KiCad resolve project
        values now and after an external source updates the ``.kicad_pro``.
        """
        layers = tuple(dict.fromkeys(output_layers or (output_layer,)))
        if not layers or any(layer not in SUPPORTED_OUTPUT_LAYERS for layer in layers):
            raise ValueError("Kobee Studio requires one or more supported output layers")
        if output_layer not in layers:
            output_layer = layers[0]
        raw_text = str(settings.get("VariableTemplateText", ""))
        if not raw_text.strip():
            raise ValueError("Variable template text cannot be empty")

        api = self._api()
        name = "kobee-variable-{}".format(uuid.uuid4().hex[:12])
        footprint = api["FootprintInstance"]()
        definition = footprint.definition
        definition.id.name = name
        common_types = api["CommonTypes"]
        alignment = {
            "Left": common_types.HorizontalAlignment.HA_LEFT,
            "Center": common_types.HorizontalAlignment.HA_CENTER,
            "Right": common_types.HorizontalAlignment.HA_RIGHT,
        }.get(str(settings.get("AlignmentChoice", "Center")), common_types.HorizontalAlignment.HA_CENTER)
        height_mm = max(0.1, float(settings.get("HeightCtrl", 1.2)))
        width_mm = max(0.1, float(settings.get("NativeTextWidthCtrl", height_mm)))
        stroke_mm = max(0.01, float(settings.get("NativeStrokeWidthCtrl", 0.18)))

        for layer in layers:
            # Keep the variable itself as native KiCad text. The optional
            # container is an outlined Kobee graphic, sized from the current
            # preview, so changing a project variable never turns the text
            # into stale static polygons.
            if container_artwork is not None:
                shape = next(
                    (
                        item
                        for item in container_artwork.document.objects
                        if isinstance(item, ShapeObject)
                        and item.object_id == "shape.background"
                    ),
                    None,
                )
                if shape is not None:
                    contour = shape_contour(
                        shape.shape,
                        shape.size,
                        container_artwork.document.style.shape,
                    )
                    outline = StudioArtwork(
                        (),
                        (StrokePath(contour, max(0.01, container_artwork.document.style.shape.border_thickness_mm)),),
                        (),
                        container_artwork.document,
                    )
                    for primitive in artwork_polygons(
                        outline,
                        layer,
                        offset=self._artwork_offset(container_artwork, layer),
                    ):
                        definition.add_item(self._polygon_item(api, primitive, layer))
            text = api["BoardText"]()
            text.value = raw_text
            text.layer = self._layer(api, layer)
            text.position = api["Vector2"].from_xy_mm(0.0, 0.0)
            attributes = text.attributes
            attributes.font_name = ""
            attributes.size = api["Vector2"].from_xy_mm(width_mm, height_mm)
            attributes.stroke_width = api["from_mm"](stroke_mm)
            attributes.angle = 0.0
            attributes.line_spacing = max(0.1, float(settings.get("LineSpacingCtrl", 1.5)))
            attributes.horizontal_alignment = alignment
            attributes.vertical_alignment = common_types.VerticalAlignment.VA_CENTER
            attributes.bold = bool(settings.get("NativeBoldCheckbox", False))
            attributes.italic = bool(settings.get("NativeItalicCheckbox", False))
            attributes.underlined = bool(settings.get("NativeUnderlineCheckbox", False))
            attributes.mirrored = is_bottom(layer)
            attributes.multiline = "\n" in raw_text
            attributes.keep_upright = bool(settings.get("NativeKeepUprightCheckbox", True))
            definition.add_item(text)

        metadata = api["Field"]()
        metadata.name = METADATA_FIELD_NAME
        metadata.layer = self._layer(api, output_layer)
        metadata.text.value = encode_metadata(payload)
        self._configure_hidden_field(api, metadata, output_layer, size_mm=0.1)
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
        footprint.value_field.text.value = "Kobee Studio variable label"
        footprint.value_field.visible = False
        self._configure_standard_fields(api, footprint, output_layer)
        return footprint

    def place_variable_text(
        self,
        settings: Mapping[str, Any],
        payload: Mapping[str, Any],
        output_layer: str,
        output_layers: Optional[Sequence[str]] = None,
        container_artwork: Optional[StudioArtwork] = None,
        old_footprint: Optional[Any] = None,
        start_interactive_move: bool = True,
    ):
        footprint = self.build_variable_footprint(
            settings,
            payload,
            output_layer,
            output_layers=output_layers,
            container_artwork=container_artwork,
        )
        return self._place_footprint(footprint, old_footprint, start_interactive_move, "variable label")

    def place(
        self,
        artwork: StudioArtwork,
        payload: Mapping[str, Any],
        output_layer: str,
        output_layers: Optional[Sequence[str]] = None,
        old_footprint: Optional[Any] = None,
        start_interactive_move: bool = True,
    ):
        footprint = self.build_footprint(artwork, payload, output_layer, output_layers=output_layers)
        return self._place_footprint(footprint, old_footprint, start_interactive_move, "artwork")

    def _place_footprint(self, footprint, old_footprint, start_interactive_move, label):
        replacement = (
            old_footprint is not None and sys.platform == "win32"
            and re.match(r"10\.0\.6(?:\D|$)", self.session.version()) is not None
        )
        if replacement:
            # CreateItems assigns a fresh identity. It cannot inherit the
            # original's group membership, so leave grouped artwork intact.
            board = self.session.board
            original = self._find_board_item(old_footprint.id)
            if original is None:
                raise RuntimeError("The original artwork is no longer on the board. Reopen the editor.")
            old_footprint = original
            if any(old_footprint.id in group.proto.items for group in board.get_groups()):
                raise RuntimeError("Ungroup this artwork before updating it on KiCad 10.0.6.")

        if old_footprint is not None:
            if not replacement:
                try:
                    footprint.definition.proto.id.CopyFrom(old_footprint.definition.proto.id)
                except Exception:
                    pass
                footprint.proto.id.CopyFrom(old_footprint.id)
            footprint.position = old_footprint.position
            footprint.orientation = old_footprint.orientation
            try:
                footprint.locked = old_footprint.locked
            except Exception:
                if replacement:
                    raise

        transaction = self.session.begin_commit()
        try:
            if old_footprint is not None and not replacement:
                created = self.session.board.update_items(footprint)
            else:
                created = self.session.board.create_items(footprint)
            if len(created or ()) != 1:
                raise RuntimeError("KiCad did not retain the artwork; the operation was rolled back")
            placed = created[0]
            if replacement:
                self._verify_replacement(footprint, placed, old_footprint)
                # Both operations are staged until PushCommit. A failure
                # before then leaves the original in place.
                self.session.board.remove_items(old_footprint)
            action = "Update" if old_footprint is not None else "Place"
            self.session.commit(transaction, "{} Kobee Studio {}".format(action, label))
        except Exception as error:
            self._discard_or_report_unknown_state(transaction, error)
            raise

        if replacement:
            # KiCad 10.0.6 returns an empty per-item deletion response.
            # Query the board after PushCommit to catch a refused deletion.
            if self._find_board_item(placed.id) is None:
                raise RuntimeError(
                    "KiCad could not confirm the replacement on the board. Undo the update before retrying."
                )
            if self._find_board_item(old_footprint.id) is not None:
                raise RuntimeError(
                    "KiCad kept both the original and the replacement. Undo the update before retrying."
                )

        if old_footprint is not None:
            try:
                self.session.board.add_to_selection(placed)
            except Exception:
                pass
        elif start_interactive_move:
            self.start_interactive_move(placed)
        return placed

    @staticmethod
    def _verify_replacement(expected, placed, original):
        from kipy.board_types import BoardText, to_concrete_board_shape

        def polygon_sizes(footprint):
            sizes = []
            for item in footprint.definition.shapes:
                shape = to_concrete_board_shape(item)
                sizes.append((shape.layer, tuple(len(polygon.outline.nodes) for polygon in shape.polygons)))
            return sorted(sizes)

        def native_text(footprint):
            return sorted((item.layer, item.value) for item in footprint.definition.items if isinstance(item, BoardText))

        def metadata(footprint):
            return [item.text.value for item in footprint.definition.items if getattr(item, "name", "") == METADATA_FIELD_NAME]

        if (
            not placed.id.value or placed.id == original.id
            or placed.position.proto != expected.position.proto
            or abs((placed.orientation.degrees - expected.orientation.degrees + 180) % 360 - 180) > 1e-6
            or placed.layer != expected.layer or placed.locked != expected.locked
            or polygon_sizes(placed) != polygon_sizes(expected)
            or native_text(placed) != native_text(expected)
            or metadata(placed) != metadata(expected)
        ):
            raise RuntimeError("KiCad did not retain the replacement artwork. The original was kept.")

    def start_interactive_move(self, placed: Any) -> None:
        """Attach a committed footprint after the plugin modal has closed."""
        if self._find_board_item(placed.id) is None:
            return
        try:
            self.session.board.add_to_selection(placed)
        except Exception:
            # Selection is convenience only; placement has already succeeded.
            pass
        self.session.board.interactive_move(placed.id)

    def _find_board_item(self, item_id):
        try:
            items = self.session.board.get_items_by_id([item_id])
        except Exception as error:
            from kipy.errors import ApiError
            from kipy.proto.common import ApiStatusCode

            # KiCad 10 reports an absent ID as a bad request, not an empty list.
            if (
                isinstance(error, ApiError) and error.code == ApiStatusCode.AS_BAD_REQUEST
                and str(error).endswith("none of the requested IDs were found or valid")
            ):
                return None
            raise
        return next((item for item in items if item.id == item_id), None)

    @staticmethod
    def _angle_from_degrees(value: float):
        try:
            from kipy.geometry import Angle
        except ImportError as error:
            raise IpcUnavailableError("The installed kicad-python package is incomplete") from error
        return Angle.from_degrees(float(value))

    def place_designators(self, records: Sequence[Tuple[Any, StudioArtwork, Mapping[str, Any], str, Optional[Any]]]):
        """Create movable designator footprints while atomically hiding references.

        A designator is deliberately a separate Kobee footprint: after it is
        created the PCB user can move or rotate it independently of its source
        component.  The source link in its metadata keeps reruns idempotent.
        Earlier releases embedded geometry in the source footprint; that data
        is removed as a one-time migration during the same undoable commit.
        """
        plans = []
        originals = []
        created_count = 0
        updated_count = 0
        for source, artwork, payload, output_layer, existing in records:
            original_items = list(source.definition.items)
            original_visibility = bool(source.reference_field.visible)
            embedded_metadata = next(
                (
                    item for item in original_items
                    if getattr(item, "name", "") == DESIGNATOR_METADATA_FIELD_NAME
                ),
                None,
            )
            embedded_ids = set()
            if embedded_metadata is not None:
                try:
                    prior_payload = decode_metadata(embedded_metadata.text.value)
                    prior_feature = prior_payload.get("feature", {})
                    if isinstance(prior_feature, Mapping):
                        embedded_ids.update(str(value) for value in prior_feature.get("embedded_item_ids", ()))
                except Exception:
                    pass
            retained = [
                item for item in original_items
                if getattr(item, "name", "") != DESIGNATOR_METADATA_FIELD_NAME
                and str(getattr(getattr(item, "id", None), "value", "")) not in embedded_ids
            ]
            generated = self.build_footprint(artwork, payload, output_layer)
            visible_items = [
                item for item in generated.definition.items
                if getattr(item, "name", "") != METADATA_FIELD_NAME
            ]
            if not visible_items:
                raise RuntimeError("The designator renderer produced no visible geometry")
            if existing is None:
                generated.position = source.reference_field.text.position
                generated.orientation = self._angle_from_degrees(
                    source.reference_field.text.attributes.angle
                )
                created_count += 1 if embedded_metadata is None else 0
                updated_count += 1 if embedded_metadata is not None else 0
            else:
                # Keep any manual PCB placement when refreshing a designator's
                # artwork; the source reference supplies the initial anchor.
                try:
                    generated.definition.proto.id.CopyFrom(existing.definition.proto.id)
                except Exception:
                    pass
                generated.position = existing.position
                generated.orientation = existing.orientation
                generated.proto.id.CopyFrom(existing.id)
                try:
                    generated.locked = existing.locked
                except Exception:
                    pass
                updated_count += 1
            plans.append((source, generated, existing, retained))
            originals.append((source, original_items, original_visibility))

        sources = tuple(source for source, _generated, _existing, _retained in plans)
        transaction = self.session.begin_commit()
        for source, _generated, _existing, retained in plans:
            source.definition.items = retained
            source.reference_field.visible = False
        new_designators = tuple(generated for _source, generated, existing, _retained in plans if existing is None)
        updated_designators = tuple(generated for _source, generated, existing, _retained in plans if existing is not None)
        try:
            updated_sources = tuple(self.session.board.update_items(sources) or ())
            if len(updated_sources) != len(sources):
                raise RuntimeError("KiCad did not update every selected footprint")
            created = tuple(self.session.board.create_items(new_designators) or ()) if new_designators else ()
            if len(created) != len(new_designators):
                raise RuntimeError("KiCad did not create every designator footprint")
            updated = tuple(self.session.board.update_items(updated_designators) or ()) if updated_designators else ()
            if len(updated) != len(updated_designators):
                raise RuntimeError("KiCad did not update every designator footprint")
            created_iter = iter(created)
            updated_iter = iter(updated)
            placed_by_plan = tuple(
                (next(updated_iter) if existing is not None else next(created_iter), source)
                for source, _generated, existing, _retained in plans
            )
            for placed, source in placed_by_plan:
                metadata = next(
                    (
                        item for item in getattr(placed.definition, "items", ())
                        if getattr(item, "name", "") == METADATA_FIELD_NAME
                    ),
                    None,
                )
                if metadata is None:
                    raise RuntimeError("KiCad dropped the movable designator metadata")
                feature = decode_metadata(metadata.text.value).get("feature", {})
                if not isinstance(feature, Mapping) or feature.get("kind") != "designator_label":
                    raise RuntimeError("KiCad dropped the movable designator source link")
                if bool(source.reference_field.visible):
                    raise RuntimeError("KiCad did not hide the native reference")
            self.session.commit(transaction, "Create or update Kobee Studio designators")
        except Exception as error:
            for source, items, visible in originals:
                source.definition.items = items
                source.reference_field.visible = visible
            self._discard_or_report_unknown_state(transaction, error)
            raise RuntimeError(
                "Designators were not changed because KiCad could not retain the replacement geometry: {}".format(error)
            ) from error
        return created_count, updated_count

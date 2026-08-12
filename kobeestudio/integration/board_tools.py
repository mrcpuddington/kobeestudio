"""Safe, transactional footprint cleanup operations through KiCad IPC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence, Tuple

from .ipc_artwork import METADATA_FIELD_NAME, decode_metadata


@dataclass(frozen=True)
class BoardToolResult:
    affected: int
    skipped: int
    removed_items: int = 0


def _id_text(item: Any) -> str:
    identifier = getattr(item, "id", "")
    return str(getattr(identifier, "value", identifier))


def _is_footprint(item: Any) -> bool:
    return hasattr(item, "definition") and hasattr(item, "reference_field")


def _is_generated(footprint: Any) -> bool:
    for item in getattr(footprint.definition, "items", ()):
        if getattr(item, "name", "") == METADATA_FIELD_NAME:
            return True
    reference = getattr(getattr(footprint.reference_field, "text", None), "value", "")
    return "kobee-studio" in str(reference).lower()


def _metadata(footprint: Any) -> Mapping[str, Any]:
    for item in getattr(footprint.definition, "items", ()):
        if getattr(item, "name", "") != METADATA_FIELD_NAME: continue
        try: return decode_metadata(getattr(item.text, "value", ""))
        except Exception: return {}
    return {}


class BoardToolsService:
    def __init__(self, session) -> None:
        self.session = session; self.board = session.board

    def footprints(self, scope: str) -> Tuple[Any, ...]:
        if scope == "selected": items = self.board.get_selection()
        elif scope == "board": items = self.board.get_footprints()
        else: raise ValueError("Board tool scope must be selected or board")
        return tuple(item for item in items if _is_footprint(item))

    def eligible(self, scope: str) -> Tuple[Tuple[Any, ...], int]:
        footprints = self.footprints(scope); usable = tuple(item for item in footprints if not getattr(item, "locked", False) and not _is_generated(item))
        return usable, len(footprints) - len(usable)

    def remove_designators(self, scope: str) -> BoardToolResult:
        footprints, skipped = self.eligible(scope)
        if not footprints: return BoardToolResult(0, skipped)
        source_ids = {_id_text(item) for item in footprints}
        generated = []
        for item in self.board.get_footprints():
            payload = _metadata(item); feature = payload.get("feature", {}) if isinstance(payload, Mapping) else {}
            if isinstance(feature, Mapping) and feature.get("kind") == "designator_label" and str(feature.get("source_footprint_id", "")) in source_ids:
                generated.append(item)
        for footprint in footprints:
            footprint.reference_field.visible = False
        transaction = self.session.begin_commit()
        try:
            self.board.update_items(footprints)
            if generated: self.board.remove_items(generated)
            self.session.commit(transaction, "Remove footprint designators")
        except Exception:
            self.session.discard(transaction); raise
        return BoardToolResult(len(footprints), skipped, len(generated))

    def remove_silkscreen(self, scope: str) -> BoardToolResult:
        footprints, skipped = self.eligible(scope)
        if not footprints: return BoardToolResult(0, skipped)
        front, back = self._silk_layers(); silk_layers = {front, back, "F.SilkS", "B.SilkS"}; removed = 0
        for footprint in footprints:
            for field in (footprint.reference_field, footprint.value_field):
                if getattr(field, "layer", None) in silk_layers: field.visible = False
            retained = []
            for item in footprint.definition.items:
                if getattr(item, "layer", None) not in silk_layers: retained.append(item); continue
                if hasattr(item, "visible") and hasattr(item, "name"):
                    item.visible = False; retained.append(item)
                elif type(item).__name__ in ("BoardText", "BoardTextBox", "BoardShape", "BoardSegment", "BoardArc", "BoardCircle", "BoardRectangle", "BoardPolygon", "BoardBezier"):
                    removed += 1
                else:
                    retained.append(item)
            footprint.definition.items = retained
        transaction = self.session.begin_commit()
        try:
            self.board.update_items(footprints)
            self.session.commit(transaction, "Remove footprint silkscreen")
        except Exception:
            self.session.discard(transaction); raise
        return BoardToolResult(len(footprints), skipped, removed)

    @staticmethod
    def _silk_layers():
        try:
            from kipy.proto.board.board_types_pb2 import BoardLayer
            return BoardLayer.BL_F_SilkS, BoardLayer.BL_B_SilkS
        except ImportError:
            # Stable test doubles and older wrappers can use KiCad's names.
            return "F.SilkS", "B.SilkS"

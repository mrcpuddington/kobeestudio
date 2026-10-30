"""Board selection helpers for non-artwork footprints.

Kobee Studio artwork footprints are recognised by their metadata field, so any
selected footprint without that field is a real component.  Reading its pads is
how the header overlay learns the pin names the user would otherwise retype.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from ..core.connector_labels import looks_like_connector, numbered_pad_labels
from .ipc_artwork import METADATA_FIELD_NAME


def _is_artwork(footprint: Any) -> bool:
    definition = getattr(footprint, "definition", None)
    if definition is None:
        return False
    for item in getattr(definition, "items", ()):
        if getattr(item, "name", "") == METADATA_FIELD_NAME:
            return True
    return False


def _pads_of(footprint: Any) -> List[Any]:
    definition = getattr(footprint, "definition", None)
    items = getattr(definition, "items", ()) if definition is not None else ()
    try:
        from kipy.board_types import Pad
    except Exception:  # pragma: no cover - only on KiCad versions without pads
        Pad = None
    pads = []
    for item in items:
        if Pad is not None:
            if isinstance(item, Pad):
                pads.append(item)
        elif hasattr(item, "number") and hasattr(item, "net"):
            pads.append(item)
    return pads


def selected_connector_labels(session: Any) -> Optional[Sequence[str]]:
    """Pin labels for a single selected connector, or ``None``.

    Returns ``None`` for empty or multi-item selections, for Kobee artwork (that
    opens as an artwork edit) and for anything that does not read as a single
    row of numbered pins.
    """
    try:
        selection = session.selected_items()
    except Exception:
        return None
    if not selection or len(selection) != 1:
        return None
    footprint = selection[0]
    if getattr(footprint, "definition", None) is None or _is_artwork(footprint):
        return None
    if not looks_like_connector(footprint):
        return None
    return numbered_pad_labels(_pads_of(footprint))

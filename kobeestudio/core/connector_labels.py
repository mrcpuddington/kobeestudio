"""Derive pin labels from a connector footprint.

The pin header overlay wants one label per pin, but that information already
exists on the board: a wired connector carries a net name on every pad.  This
module turns pads into that label list, and nothing here touches the KiCad API
so the rules stay unit-testable.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Sequence

#: Pads without a net reach us either empty or as KiCad's placeholder name.
UNCONNECTED_PREFIX = "unconnected-"

#: Library or footprint names that mark a footprint as a connector.  A plain
#: two-pad passive must not be mistaken for a header just because its pads are
#: numbered 1 and 2.
CONNECTOR_NAME_PATTERN = re.compile(
    r"conn|header|hdr|socket|terminal|jst|\bph\b|\bxh\b|pinhead",
    re.IGNORECASE,
)


def _net_label(pad: Any) -> str:
    """Return the label a pad's net suggests, or an empty string."""
    net = getattr(pad, "net", None)
    name = getattr(net, "name", "") if net is not None else ""
    name = (name or "").strip()
    if not name or name.startswith(UNCONNECTED_PREFIX):
        return ""
    # Hierarchical nets arrive as "/uart/RX"; the pin label wants the leaf.
    leaf = name.rsplit("/", 1)[-1].strip()
    return leaf or name


def numbered_pad_labels(pads: Iterable[Any]) -> Optional[Sequence[str]]:
    """Return one label per pin, or ``None`` if the pads are not a pin row.

    Pads qualify when their numbers form the contiguous range 1..N with N >= 2,
    which is the shape of a single-row connector.  Pads without a net fall back
    to ``Pin <number>`` so a partly wired connector still previews sensibly.
    """
    by_number: dict[int, Any] = {}
    for pad in pads:
        number = str(getattr(pad, "number", "") or "").strip()
        if not number.isdigit() or not number.isascii():
            return None
        index = int(number)
        if index < 1 or index in by_number:
            return None
        by_number[index] = pad
    if len(by_number) < 2:
        return None
    if sorted(by_number) != list(range(1, len(by_number) + 1)):
        return None
    return [
        _net_label(by_number[index]) or "Pin {}".format(index)
        for index in range(1, len(by_number) + 1)
    ]


def looks_like_connector(footprint: Any) -> bool:
    """True when the footprint's library id or name reads as a connector."""
    definition = getattr(footprint, "definition", None)
    identifier = getattr(definition, "id", None) if definition is not None else None
    parts = [
        getattr(identifier, "library", ""),
        getattr(identifier, "name", ""),
    ]
    haystack = " ".join(part for part in parts if part)
    return bool(CONNECTOR_NAME_PATTERN.search(haystack))

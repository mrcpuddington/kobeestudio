"""Suggest editable overlay settings for a selected straight connector row."""

import re

from ..core.pin_header import HEADER_PITCH_CHOICES, maximum_pin_label_height
from ..core.transforms import BOTTOM_SILKSCREEN, FRONT_SILKSCREEN


_CONNECTOR_NAME = re.compile(
    r"(?:^|[:_-])(?:connector|conn|pinheader|pinsocket|header|socket|terminalblock|jst)(?:[:_-]|$)",
    re.IGNORECASE,
)


def connector_prefill(selection):
    """Return one-shot defaults for a supported IPC connector, or None."""
    from kipy.board_types import FootprintInstance
    from kipy.proto.board.board_types_pb2 import BL_B_Cu

    if len(selection) != 1 or not isinstance(selection[0], FootprintInstance):
        return None
    footprint = selection[0]
    if not _CONNECTOR_NAME.search(str(footprint.definition.id)):
        return None
    pads = footprint.definition.pads
    if not 2 <= len(pads) <= 40:
        return None
    by_number = {pad.number: pad for pad in pads}
    if set(by_number) != {str(number) for number in range(1, len(pads) + 1)}:
        return None
    ordered = [by_number[str(number)] for number in range(1, len(pads) + 1)]
    first, last = ordered[0].position, ordered[-1].position
    horizontal = abs(last.x - first.x) >= abs(last.y - first.y)
    axis = "x" if horizontal else "y"
    cross = "y" if horizontal else "x"
    start = getattr(first, axis)
    step_mm = round((getattr(last, axis) - start) / (len(pads) - 1) / 1_000_000, 2)
    pitch = abs(step_mm)
    if not 0.50 <= pitch <= 20.00:
        return None

    labels = []
    for index, pad in enumerate(ordered):
        position = pad.position
        if (
            abs(getattr(position, cross) - getattr(first, cross)) > 10_000
            or abs(getattr(position, axis) - (start + index * step_mm * 1_000_000)) > 10_000
        ):
            return None
        net = pad.net.name
        label = " ".join(net.rsplit("/", 1)[-1].split())
        labels.append(label if label and not net.lower().startswith("unconnected-") else f"Pin {index + 1}")

    bottom = footprint.layer == BL_B_Cu
    # The bottom-layer artwork transform reverses X, including pin order.
    forward = (step_mm > 0) != (bottom and horizontal)
    pitch_label = f"{pitch:.2f} mm"
    # Leave room for ascenders and descenders beyond the nominal font height.
    label_height = min(1.2, round(maximum_pin_label_height(pitch) * 0.75, 2))
    return {
        "MultiLineText": "\n".join(labels),
        "HeaderPinCountCtrl": len(pads),
        "HeaderPitchChoice": pitch_label if pitch_label in HEADER_PITCH_CHOICES else "Custom",
        "HeaderCustomPitchCtrl": pitch,
        "HeaderOrientationChoice": "Horizontal" if horizontal else "Vertical",
        "HeaderPinSideChoice": "Top" if horizontal else "Left",
        "HeaderPin1Choice": "Start" if forward else "End",
        "HeaderPadClearanceCtrl": min(2.0, pitch),
        "HeightCtrl": label_height,
        "LayerComboBox": BOTTOM_SILKSCREEN if bottom else FRONT_SILKSCREEN,
    }

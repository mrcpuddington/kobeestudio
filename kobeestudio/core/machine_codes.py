"""Fabrication-aware QR Code and Code 128 vector generation."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Tuple

from .composition import Point, Size
from .shape_geometry import Polygon


QR_MIN_MODULE_MM = 0.35
QR_QUIET_ZONE_MODULES = 4
QR_MAX_PAYLOAD_BYTES = 512
CODE128_MIN_MODULE_MM = 0.20
CODE128_DEFAULT_MODULE_MM = 0.25
CODE128_MIN_HEIGHT_MM = 3.0
CODE128_DEFAULT_HEIGHT_MM = 4.0
CODE128_QUIET_ZONE_MODULES = 10
CODE128_MAX_CHARACTERS = 48
MACHINE_CODE_KINDS = ("qr", "code128")


def _add_vendor_path() -> None:
    package_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    vendor = os.path.join(package_root, "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


_add_vendor_path()


@dataclass(frozen=True)
class MachineCodeGeometry:
    kind: str
    payload: str
    polygons: Tuple[Polygon, ...]
    size: Size
    module_size_mm: float
    quiet_zone_modules: int
    module_columns: int
    module_rows: int


def _rectangle(left: float, top: float, right: float, bottom: float) -> Polygon:
    return (
        Point(left, top),
        Point(right, top),
        Point(right, bottom),
        Point(left, bottom),
    )


def _validate_payload(payload: str) -> str:
    if not isinstance(payload, str):
        raise ValueError("Code payload must be text")
    if not payload:
        raise ValueError("Enter a payload to generate a machine-readable code")
    return payload


def _matrix_polygons(matrix, module_size_mm: float) -> Tuple[Polygon, ...]:
    """Merge horizontal runs of dark modules into compact rectangles."""
    rows = len(matrix)
    columns = len(matrix[0]) if rows else 0
    left = -columns * module_size_mm / 2.0
    top = -rows * module_size_mm / 2.0
    polygons = []
    for row_index, row in enumerate(matrix):
        start = None
        for column_index in range(columns + 1):
            dark = column_index < columns and bool(row[column_index])
            if dark and start is None:
                start = column_index
            elif not dark and start is not None:
                polygons.append(
                    _rectangle(
                        left + start * module_size_mm,
                        top + row_index * module_size_mm,
                        left + column_index * module_size_mm,
                        top + (row_index + 1) * module_size_mm,
                    )
                )
                start = None
    return tuple(polygons)


def render_qr_code(payload: str, module_size_mm: float = QR_MIN_MODULE_MM) -> MachineCodeGeometry:
    payload = _validate_payload(payload)
    encoded = payload.encode("utf-8")
    if len(encoded) > QR_MAX_PAYLOAD_BYTES:
        raise ValueError(
            "QR payload is {} bytes; keep it at or below {} bytes for a practical PCB code".format(
                len(encoded), QR_MAX_PAYLOAD_BYTES
            )
        )
    if module_size_mm < QR_MIN_MODULE_MM:
        raise ValueError(
            "QR module size must be at least {:.2f} mm for reliable PCB reproduction".format(
                QR_MIN_MODULE_MM
            )
        )

    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    from qrcode.exceptions import DataOverflowError

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=1,
        border=0,
    )
    try:
        qr.add_data(payload)
        qr.make(fit=True)
    except DataOverflowError as error:
        raise ValueError("Payload is too large for a standard QR Code") from error
    matrix = tuple(tuple(bool(value) for value in row) for row in qr.get_matrix())
    modules = len(matrix)
    total_modules = modules + QR_QUIET_ZONE_MODULES * 2
    return MachineCodeGeometry(
        kind="qr",
        payload=payload,
        polygons=_matrix_polygons(matrix, module_size_mm),
        size=Size(total_modules * module_size_mm, total_modules * module_size_mm),
        module_size_mm=module_size_mm,
        quiet_zone_modules=QR_QUIET_ZONE_MODULES,
        module_columns=modules,
        module_rows=modules,
    )


def render_code128(
    payload: str,
    module_size_mm: float = CODE128_DEFAULT_MODULE_MM,
    bar_height_mm: float = CODE128_DEFAULT_HEIGHT_MM,
) -> MachineCodeGeometry:
    payload = _validate_payload(payload)
    if "\n" in payload or "\r" in payload:
        raise ValueError("Code 128 payload must be a single line")
    if len(payload) > CODE128_MAX_CHARACTERS:
        raise ValueError(
            "Code 128 payload has {} characters; keep it at or below {} so the PCB barcode remains practical".format(
                len(payload), CODE128_MAX_CHARACTERS
            )
        )
    invalid = tuple(character for character in payload if not 32 <= ord(character) <= 126)
    if invalid:
        raise ValueError("Code 128 currently accepts printable ASCII characters only")
    if module_size_mm < CODE128_MIN_MODULE_MM:
        raise ValueError(
            "Code 128 module width must be at least {:.2f} mm for PCB reproduction".format(
                CODE128_MIN_MODULE_MM
            )
        )
    if bar_height_mm < CODE128_MIN_HEIGHT_MM:
        raise ValueError(
            "Code 128 bar height must be at least {:.1f} mm for dependable scanning".format(
                CODE128_MIN_HEIGHT_MM
            )
        )

    from barcode.codex import Code128
    from barcode.errors import IllegalCharacterError

    try:
        pattern = Code128(payload).build()[0]
    except IllegalCharacterError as error:
        raise ValueError("Payload contains a character Code 128 cannot encode") from error

    pattern_width = len(pattern) * module_size_mm
    left = -pattern_width / 2.0
    top = -bar_height_mm / 2.0
    polygons = []
    start = None
    for index in range(len(pattern) + 1):
        dark = index < len(pattern) and pattern[index] == "1"
        if dark and start is None:
            start = index
        elif not dark and start is not None:
            polygons.append(
                _rectangle(
                    left + start * module_size_mm,
                    top,
                    left + index * module_size_mm,
                    top + bar_height_mm,
                )
            )
            start = None
    total_columns = len(pattern) + CODE128_QUIET_ZONE_MODULES * 2
    return MachineCodeGeometry(
        kind="code128",
        payload=payload,
        polygons=tuple(polygons),
        size=Size(total_columns * module_size_mm, bar_height_mm),
        module_size_mm=module_size_mm,
        quiet_zone_modules=CODE128_QUIET_ZONE_MODULES,
        module_columns=len(pattern),
        module_rows=1,
    )


def render_machine_code(
    kind: str,
    payload: str,
    module_size_mm: float,
    bar_height_mm: float = CODE128_DEFAULT_HEIGHT_MM,
) -> MachineCodeGeometry:
    if kind == "qr":
        return render_qr_code(payload, module_size_mm)
    if kind == "code128":
        return render_code128(payload, module_size_mm, bar_height_mm)
    raise ValueError("Unsupported machine-readable code type: {}".format(kind))

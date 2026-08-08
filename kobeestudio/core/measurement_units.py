"""Display-unit conversion while preserving millimetres internally."""

from __future__ import annotations

import math
from enum import Enum
from typing import Union


MM_PER_MIL = 0.0254


class MeasurementUnit(str, Enum):
    MILLIMETRES = "mm"
    MILS = "mil"

    @classmethod
    def parse(cls, value: Union[str, "MeasurementUnit"]) -> "MeasurementUnit":
        if isinstance(value, cls):
            return value
        normalised = str(value).strip().lower()
        aliases = {
            "mm": cls.MILLIMETRES,
            "millimeter": cls.MILLIMETRES,
            "millimeters": cls.MILLIMETRES,
            "millimetre": cls.MILLIMETRES,
            "millimetres": cls.MILLIMETRES,
            "mil": cls.MILS,
            "mils": cls.MILS,
            "thou": cls.MILS,
        }
        try:
            return aliases[normalised]
        except KeyError:
            raise ValueError("Unsupported measurement unit: {}".format(value))


def _finite(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Measurement must be finite")
    return result


def from_millimetres(value_mm: float, unit: Union[str, MeasurementUnit]) -> float:
    value_mm = _finite(value_mm)
    return value_mm if MeasurementUnit.parse(unit) is MeasurementUnit.MILLIMETRES else value_mm / MM_PER_MIL


def to_millimetres(value: float, unit: Union[str, MeasurementUnit]) -> float:
    value = _finite(value)
    return value if MeasurementUnit.parse(unit) is MeasurementUnit.MILLIMETRES else value * MM_PER_MIL


def format_measurement(value_mm: float, unit: Union[str, MeasurementUnit], decimals: int = 3) -> str:
    if not isinstance(decimals, int) or decimals < 0 or decimals > 9:
        raise ValueError("decimals must be between 0 and 9")
    parsed = MeasurementUnit.parse(unit)
    value = from_millimetres(value_mm, parsed)
    return "{value:.{decimals}f} {unit}".format(value=value, decimals=decimals, unit=parsed.value)

"""KiCad-independent geometry and footprint serialization."""

from .composition import CompositionDocument
from .pin_header import PinHeaderSpec

__all__ = ("CompositionDocument", "PinHeaderSpec")

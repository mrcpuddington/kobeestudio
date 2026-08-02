"""Footprint generation facades used by the UI and KiCad integration."""

from .studio_artwork import StudioArtwork, serialize_artwork
from .text_geometry import TextGeometry


def generate_footprint(geometry: TextGeometry, serialized_parameters: str, layer: str) -> str:
    return geometry.footprint(serialized_parameters, layer)


def generate_studio_footprint(artwork: StudioArtwork, serialized_parameters: str, layer: str) -> str:
    return serialize_artwork(artwork, serialized_parameters, layer)

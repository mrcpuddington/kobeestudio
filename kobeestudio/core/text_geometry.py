"""Adapter around the upstream, font-to-vector implementation.

The adapter has no dependency on ``pcbnew`` or an active KiCad process.
"""

from __future__ import annotations

import os
import sys

from .transforms import SUPPORTED_OUTPUT_LAYERS


def _add_bundled_dependency_paths() -> None:
    """Make the small runtime vendor bundle available before importing it."""
    package_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for path in (os.path.join(package_root, "vendor"),):
        if path not in sys.path:
            sys.path.insert(0, path)


_add_bundled_dependency_paths()
from ..rendering.buzzard import Buzzard  # noqa: E402


class TextGeometry:
    """Generate vectors and serialized footprints without KiCad bindings."""

    def __init__(self) -> None:
        self._buzzard = Buzzard()

    @property
    def buzzard(self):
        return self._buzzard

    def generate(self, text: str):
        return self._buzzard.generate(text)

    def footprint(self, parameters: str, layer: str) -> str:
        if layer not in SUPPORTED_OUTPUT_LAYERS:
            raise ValueError("Unsupported Kobee Studio output layer: {}".format(layer))
        self._buzzard.layer = layer
        return self._buzzard.create_v6_footprint(parameters, output_layer=layer)

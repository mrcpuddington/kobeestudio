"""Coordinate transforms shared by export and preview code."""

from __future__ import annotations


FRONT_COPPER = "F.Cu"
BOTTOM_COPPER = "B.Cu"
FRONT_SILKSCREEN = "F.SilkS"
BOTTOM_SILKSCREEN = "B.SilkS"
FRONT_MASK = "F.Mask"
BOTTOM_MASK = "B.Mask"

SUPPORTED_OUTPUT_LAYERS = (
    FRONT_SILKSCREEN,
    BOTTOM_SILKSCREEN,
    FRONT_COPPER,
    BOTTOM_COPPER,
    FRONT_MASK,
    BOTTOM_MASK,
)

# Compatibility name retained for code outside the Kobee Studio boundary.
SUPPORTED_SILKSCREEN_LAYERS = (FRONT_SILKSCREEN, BOTTOM_SILKSCREEN)


def is_bottom(layer: str) -> bool:
    if layer not in SUPPORTED_OUTPUT_LAYERS:
        raise ValueError("Unsupported Kobee Studio output layer: {}".format(layer))
    return layer.startswith("B.")


def preview_x(x: float, layer: str) -> float:
    """Return the front-view X coordinate for a generated preview point."""
    return -x if is_bottom(layer) else x


def preview_polygons(polygons, layer: str):
    """Convert generated point objects into immutable preview coordinates.

    Keeping this conversion outside the wx paint callback makes the renderer
    deterministic and, importantly, avoids mixing ``svg.Point`` objects and
    plain tuples during a paint event.
    """
    return [
        [(preview_x(float(point.x), layer), float(point.y)) for point in polygon]
        for polygon in polygons
        if polygon
    ]


def fit_preview_polygons(polygons, width: int, height: int, margin: float = 0.05):
    """Scale and centre preview polygons inside a pixel-sized rectangle."""
    if not polygons or width <= 0 or height <= 0:
        return []

    points = [point for polygon in polygons for point in polygon]
    if not points:
        return []

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    geometry_width = max_x - min_x
    geometry_height = max_y - min_y
    if geometry_width <= 0 or geometry_height <= 0:
        return []

    usable_width = width * max(0.0, 1.0 - margin * 2.0)
    usable_height = height * max(0.0, 1.0 - margin * 2.0)
    scale = min(usable_width / geometry_width, usable_height / geometry_height)
    centre_x = (min_x + max_x) / 2.0
    centre_y = (min_y + max_y) / 2.0

    return [
        [((x - centre_x) * scale, (y - centre_y) * scale) for x, y in polygon]
        for polygon in polygons
    ]

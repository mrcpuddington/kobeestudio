"""Original fabrication-friendly icons and built-in label presets."""

from __future__ import annotations

import math
from functools import lru_cache
from dataclasses import dataclass
from typing import Dict, Tuple

from .composition import Point, Size
from .shape_geometry import Polygon, polygon_bounds


@dataclass(frozen=True)
class BuiltinIcon:
    asset_id: str
    name: str
    category: str
    polygons: Tuple[Polygon, ...]
    nominal_size: Size = Size()


@dataclass(frozen=True)
class IconVectors:
    polygons: Tuple[Polygon, ...]
    size: Size


@dataclass(frozen=True)
class LabelPreset:
    preset_id: str
    text: str
    category: str
    icon_id: str = ""

    @property
    def display_name(self) -> str:
        return "{} — {}".format(self.category, self.text)


def _polygon(*coordinates: Tuple[float, float]) -> Polygon:
    return tuple(Point(x, y) for x, y in coordinates)


def _rectangle(left: float, top: float, right: float, bottom: float) -> Polygon:
    return _polygon((left, top), (right, top), (right, bottom), (left, bottom))


def _circle(radius: float, centre_x: float = 0.0, centre_y: float = 0.0, segments: int = 24) -> Polygon:
    return tuple(
        Point(
            centre_x + radius * math.cos(2.0 * math.pi * index / segments),
            centre_y + radius * math.sin(2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    )


def _arc_band(
    start_degrees: float,
    end_degrees: float,
    outer_radius: float,
    inner_radius: float,
    segments: int = 24,
) -> Polygon:
    outer = tuple(
        Point(
            outer_radius * math.cos(math.radians(start_degrees + (end_degrees - start_degrees) * index / segments)),
            outer_radius * math.sin(math.radians(start_degrees + (end_degrees - start_degrees) * index / segments)),
        )
        for index in range(segments + 1)
    )
    inner = tuple(
        Point(
            inner_radius * math.cos(math.radians(end_degrees - (end_degrees - start_degrees) * index / segments)),
            inner_radius * math.sin(math.radians(end_degrees - (end_degrees - start_degrees) * index / segments)),
        )
        for index in range(segments + 1)
    )
    return outer + inner


def _segmented_ring(
    centre_x: float,
    centre_y: float,
    outer_radius: float,
    inner_radius: float,
    gap_degrees: float = 2.0,
) -> Tuple[Polygon, ...]:
    """Return a visually closed ring as simple, non-self-intersecting arcs."""
    polygons = []
    for start in (0.0, 90.0, 180.0, 270.0):
        arc = _arc_band(
            start + gap_degrees,
            start + 90.0 - gap_degrees,
            outer_radius,
            inner_radius,
            segments=8,
        )
        polygons.append(
            tuple(Point(point.x + centre_x, point.y + centre_y) for point in arc)
        )
    return tuple(polygons)


def _thick_segment(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    thickness: float,
) -> Tuple[Polygon, ...]:
    """Return a round-ended filled segment as fabrication-safe polygons."""
    delta_x, delta_y = end_x - start_x, end_y - start_y
    length = math.hypot(delta_x, delta_y)
    if length <= 0:
        return (_circle(thickness / 2.0, start_x, start_y),)
    radius = thickness / 2.0
    normal_x = -delta_y / length * radius
    normal_y = delta_x / length * radius
    return (
        _polygon(
            (start_x + normal_x, start_y + normal_y),
            (end_x + normal_x, end_y + normal_y),
            (end_x - normal_x, end_y - normal_y),
            (start_x - normal_x, start_y - normal_y),
        ),
        _circle(radius, start_x, start_y, segments=16),
        _circle(radius, end_x, end_y, segments=16),
    )


def _polarity_marker(centre_x: float, positive: bool) -> Tuple[Polygon, ...]:
    marker = list(_segmented_ring(centre_x, 0.0, 0.42, 0.31))
    marker.append(_rectangle(centre_x - 0.22, -0.055, centre_x + 0.22, 0.055))
    if positive:
        marker.append(_rectangle(centre_x - 0.055, -0.22, centre_x + 0.055, 0.22))
    return tuple(marker)


def _dc_polarity_icon(asset_id: str, name: str, centre_positive: bool) -> BuiltinIcon:
    """Build the standard coaxial DC connector polarity diagram."""
    left_x, right_x = -1.45, 1.45
    return BuiltinIcon(
        asset_id,
        name,
        "Electrical",
        _polarity_marker(left_x, positive=not centre_positive)
        + (
            _rectangle(-1.03, -0.055, -0.50, 0.055),
            _arc_band(42.0, 318.0, 0.46, 0.35, segments=28),
            _circle(0.21),
            _rectangle(0.50, -0.055, 1.03, 0.055),
        )
        + _polarity_marker(right_x, positive=centre_positive),
    )


GROUND = BuiltinIcon(
    "builtin.ground",
    "Ground",
    "Electrical",
    (
        _rectangle(-0.07, -0.50, 0.07, -0.14),
        _rectangle(-0.43, -0.10, 0.43, 0.03),
        _rectangle(-0.29, 0.14, 0.29, 0.27),
        _rectangle(-0.14, 0.38, 0.14, 0.50),
    ),
)

LIGHTNING = BuiltinIcon(
    "builtin.lightning",
    "Power / lightning",
    "Electrical",
    (
        _polygon(
            (-0.02, -0.50),
            (0.39, -0.50),
            (0.13, -0.08),
            (0.42, -0.08),
            (-0.20, 0.50),
            (-0.05, 0.08),
            (-0.40, 0.08),
        ),
    ),
)

TEST_POINT = BuiltinIcon(
    "builtin.test_point",
    "Test point",
    "PCB",
    (
        _circle(0.25),
        _rectangle(-0.055, -0.50, 0.055, -0.34),
        _rectangle(-0.055, 0.34, 0.055, 0.50),
        _rectangle(-0.50, -0.055, -0.34, 0.055),
        _rectangle(0.34, -0.055, 0.50, 0.055),
    ),
)

INPUT = BuiltinIcon(
    "builtin.input",
    "Input",
    "Direction",
    (
        _rectangle(-0.50, -0.50, -0.43, 0.50),
        _polygon(
            (0.50, -0.12),
            (-0.02, -0.12),
            (-0.02, -0.34),
            (-0.39, 0.0),
            (-0.02, 0.34),
            (-0.02, 0.12),
            (0.50, 0.12),
        ),
    ),
)

OUTPUT = BuiltinIcon(
    "builtin.output",
    "Output",
    "Direction",
    (
        _rectangle(-0.50, -0.50, -0.43, 0.50),
        _polygon(
            (-0.39, -0.12),
            (0.11, -0.12),
            (0.11, -0.34),
            (0.50, 0.0),
            (0.11, 0.34),
            (0.11, 0.12),
            (-0.39, 0.12),
        ),
    ),
)

RESET = BuiltinIcon(
    "builtin.reset",
    "Reset",
    "Controls",
    (
        _arc_band(-145.0, 155.0, 0.47, 0.31),
        _polygon((-0.49, -0.30), (-0.48, 0.08), (-0.17, -0.15)),
    ),
)

WARNING = BuiltinIcon(
    "builtin.warning",
    "Warning",
    "Safety",
    _thick_segment(0.0, -0.46, 0.47, 0.36, 0.13)
    + _thick_segment(0.47, 0.36, -0.47, 0.36, 0.13)
    + _thick_segment(-0.47, 0.36, 0.0, -0.46, 0.13)
    + (
        _rectangle(-0.060, -0.20, 0.060, 0.10),
        _circle(0.070, centre_y=0.23, segments=16),
    ),
)

LED = BuiltinIcon(
    "builtin.led",
    "LED / indicator",
    "Controls",
    (
        _circle(0.25),
        _rectangle(-0.045, -0.50, 0.045, -0.35),
        _rectangle(-0.045, 0.35, 0.045, 0.50),
        _rectangle(-0.50, -0.045, -0.35, 0.045),
        _rectangle(0.35, -0.045, 0.50, 0.045),
        _polygon((-0.38, -0.45), (-0.29, -0.39), (-0.34, -0.31), (-0.45, -0.38)),
        _polygon((0.38, 0.45), (0.29, 0.39), (0.34, 0.31), (0.45, 0.38)),
    ),
)

CENTRE_POSITIVE = _dc_polarity_icon(
    "builtin.centre_positive", "DC centre positive", centre_positive=True
)

CENTRE_NEGATIVE = _dc_polarity_icon(
    "builtin.centre_negative", "DC centre negative", centre_positive=False
)

POSITIVE = BuiltinIcon(
    "builtin.positive",
    "Positive polarity",
    "Electrical",
    (
        _rectangle(-0.38, -0.075, 0.38, 0.075),
        _rectangle(-0.075, -0.38, 0.075, 0.38),
    ),
    Size(0.76, 0.76),
)

NEGATIVE = BuiltinIcon(
    "builtin.negative",
    "Negative polarity",
    "Electrical",
    (_rectangle(-0.38, -0.075, 0.38, 0.075),),
    Size(0.76, 0.76),
)

LIGHT_BULB = BuiltinIcon(
    "builtin.light_bulb",
    "Light bulb",
    "Controls",
    (
        _circle(0.35, centre_y=-0.15, segments=32),
        _rectangle(-0.19, 0.24, 0.19, 0.31),
        _rectangle(-0.15, 0.36, 0.15, 0.43),
        _rectangle(-0.075, 0.48, 0.075, 0.53),
    ),
)

BATTERY = BuiltinIcon(
    "builtin.battery",
    "Battery",
    "Electrical",
    (
        _rectangle(-0.58, -0.38, 0.43, -0.27),
        _rectangle(-0.58, 0.27, 0.43, 0.38),
        _rectangle(-0.58, -0.27, -0.47, 0.27),
        _rectangle(0.32, -0.27, 0.43, 0.27),
        _rectangle(0.47, -0.16, 0.58, 0.16),
        _rectangle(-0.35, -0.18, -0.26, 0.18),
        _rectangle(-0.13, -0.18, -0.04, 0.18),
        _rectangle(0.09, -0.18, 0.18, 0.18),
    ),
)

POWER_BUTTON = BuiltinIcon(
    "builtin.power_button",
    "Power button",
    "Controls",
    (
        _arc_band(-50.0, 230.0, 0.50, 0.35, segments=28),
        _rectangle(-0.075, -0.52, 0.075, -0.05),
    ),
)

PUSH_BUTTON = BuiltinIcon(
    "builtin.push_button",
    "Push button",
    "Controls",
    (
        _polygon(
            (-0.055, -0.52),
            (0.055, -0.52),
            (0.055, -0.25),
            (0.22, -0.39),
            (0.30, -0.29),
            (0.0, -0.02),
            (-0.30, -0.29),
            (-0.22, -0.39),
            (-0.055, -0.25),
        ),
        _rectangle(-0.50, 0.15, -0.31, 0.24),
        _rectangle(0.31, 0.15, 0.50, 0.24),
        _rectangle(-0.31, 0.04, 0.31, 0.13),
        _rectangle(-0.31, 0.26, 0.31, 0.35),
        _rectangle(-0.31, 0.13, -0.22, 0.26),
        _rectangle(0.22, 0.13, 0.31, 0.26),
    ),
)


BUILTIN_ICONS = (
    GROUND,
    LIGHTNING,
    TEST_POINT,
    INPUT,
    OUTPUT,
    RESET,
    WARNING,
    LED,
    CENTRE_POSITIVE,
    CENTRE_NEGATIVE,
    POSITIVE,
    NEGATIVE,
    LIGHT_BULB,
    BATTERY,
    POWER_BUTTON,
    PUSH_BUTTON,
)
ICON_BY_ID: Dict[str, BuiltinIcon] = {icon.asset_id: icon for icon in BUILTIN_ICONS}


LABEL_PRESETS = (
    LabelPreset("gnd", "GND", "Power", GROUND.asset_id),
    LabelPreset("pgnd", "PGND", "Power", GROUND.asset_id),
    LabelPreset("agnd", "AGND", "Power", GROUND.asset_id),
    LabelPreset("earth", "EARTH", "Power", GROUND.asset_id),
    LabelPreset("power", "POWER", "Power", LIGHTNING.asset_id),
    LabelPreset("vcc", "VCC", "Power", LIGHTNING.asset_id),
    LabelPreset("vdd", "VDD", "Power", LIGHTNING.asset_id),
    LabelPreset("vbat", "VBAT", "Power", BATTERY.asset_id),
    LabelPreset("vin", "VIN", "Power", LIGHTNING.asset_id),
    LabelPreset("vout", "VOUT", "Power", LIGHTNING.asset_id),
    LabelPreset("1v8", "+1V8", "Power", LIGHTNING.asset_id),
    LabelPreset("3v3", "+3V3", "Power", LIGHTNING.asset_id),
    LabelPreset("5v", "+5V", "Power", LIGHTNING.asset_id),
    LabelPreset("12v", "+12V", "Power", LIGHTNING.asset_id),
    LabelPreset("24v", "+24V", "Power", LIGHTNING.asset_id),
    LabelPreset("minus12v", "-12V", "Power", LIGHTNING.asset_id),
    LabelPreset("test_point", "TEST POINT", "Test", TEST_POINT.asset_id),
    LabelPreset("tp1", "TP1", "Test", TEST_POINT.asset_id),
    LabelPreset("debug", "DEBUG", "Test", TEST_POINT.asset_id),
    LabelPreset("reset", "RESET", "Programming", RESET.asset_id),
    LabelPreset("boot", "BOOT", "Programming"),
    LabelPreset("swdio", "SWDIO", "Programming"),
    LabelPreset("swclk", "SWCLK", "Programming"),
    LabelPreset("jtag", "JTAG", "Programming"),
    LabelPreset("usb", "USB", "Interface"),
    LabelPreset("ethernet", "ETHERNET", "Interface"),
    LabelPreset("rs485", "RS-485", "Interface"),
    LabelPreset("i2c", "I2C", "Interface"),
    LabelPreset("spi", "SPI", "Interface"),
    LabelPreset("uart", "UART", "Interface"),
    LabelPreset("can_h", "CAN H", "Interface"),
    LabelPreset("can_l", "CAN L", "Interface"),
    LabelPreset("sda", "SDA", "Interface"),
    LabelPreset("scl", "SCL", "Interface"),
    LabelPreset("mosi", "MOSI", "Interface", OUTPUT.asset_id),
    LabelPreset("miso", "MISO", "Interface", INPUT.asset_id),
    LabelPreset("sck", "SCK", "Interface"),
    LabelPreset("cs", "CS", "Interface"),
    LabelPreset("rx", "RX", "Interface", INPUT.asset_id),
    LabelPreset("tx", "TX", "Interface", OUTPUT.asset_id),
    LabelPreset("input", "INPUT", "Signal", INPUT.asset_id),
    LabelPreset("output", "OUTPUT", "Signal", OUTPUT.asset_id),
    LabelPreset("enable", "ENABLE", "Control"),
    LabelPreset("fault", "FAULT", "Control", WARNING.asset_id),
    LabelPreset("warning", "WARNING", "Control", WARNING.asset_id),
    LabelPreset("led", "LED", "Control", LED.asset_id),
    LabelPreset("status", "STATUS", "Control", LED.asset_id),
    LabelPreset("run", "RUN", "Control", LED.asset_id),
    LabelPreset("button", "BUTTON", "Control"),
    LabelPreset("dc_in", "DC IN", "Power", CENTRE_POSITIVE.asset_id),
    LabelPreset("dc_centre_negative", "DC CENTRE -", "Power", CENTRE_NEGATIVE.asset_id),
    LabelPreset("positive", "POSITIVE", "Power", POSITIVE.asset_id),
    LabelPreset("negative", "NEGATIVE", "Power", NEGATIVE.asset_id),
    LabelPreset("lamp", "LAMP", "Control", LIGHT_BULB.asset_id),
    LabelPreset("battery", "BATTERY", "Power", BATTERY.asset_id),
    LabelPreset("fan", "FAN", "Control"),
    LabelPreset("power_button", "POWER BUTTON", "Control", POWER_BUTTON.asset_id),
    LabelPreset("push_button", "PUSH BUTTON", "Control", PUSH_BUTTON.asset_id),
)
PRESET_BY_ID: Dict[str, LabelPreset] = {preset.preset_id: preset for preset in LABEL_PRESETS}


def _render_legacy_builtin_icon(asset_id: str, height_mm: float) -> IconVectors:
    """Scale and centre a built-in icon at a requested physical height."""
    if asset_id not in ICON_BY_ID:
        raise ValueError("Unknown built-in icon: {}".format(asset_id))
    if not math.isfinite(float(height_mm)) or height_mm <= 0:
        raise ValueError("Icon height must be greater than zero")

    icon = ICON_BY_ID[asset_id]
    minimum, maximum = polygon_bounds(icon.polygons)
    nominal = icon.nominal_size
    natural_height = nominal.height if nominal.height > 0 else maximum.y - minimum.y
    if natural_height <= 0:
        raise ValueError("Built-in icon has no measurable height: {}".format(asset_id))
    scale = height_mm / natural_height
    centre = Point(0.0, 0.0) if nominal.height > 0 else Point(
        (minimum.x + maximum.x) / 2.0,
        (minimum.y + maximum.y) / 2.0,
    )
    polygons = tuple(
        tuple(Point((point.x - centre.x) * scale, (point.y - centre.y) * scale) for point in polygon)
        for polygon in icon.polygons
    )
    bounds_min, bounds_max = polygon_bounds(polygons)
    rendered_size = (
        Size(nominal.width * scale, nominal.height * scale)
        if nominal.width > 0 and nominal.height > 0
        else Size(bounds_max.x - bounds_min.x, bounds_max.y - bounds_min.y)
    )
    return IconVectors(
        polygons=polygons,
        size=rendered_size,
    )


def render_builtin_icon(asset_id: str, height_mm: float) -> IconVectors:
    """Render production legacy geometry or the flagged bundled SVG equivalent."""
    from .feature_flags import SVG_SYMBOLS, development_feature_enabled

    if development_feature_enabled(SVG_SYMBOLS):
        from .svg_symbols import SymbolCatalog

        try:
            polygons, size = _bundled_svg_catalog().render(asset_id, height_mm)
        except ValueError as error:
            if "Unknown SVG symbol variant" in str(error):
                raise ValueError("Unknown built-in icon: {}".format(asset_id))
            raise
        return IconVectors(polygons=polygons, size=size)
    return _render_legacy_builtin_icon(asset_id, height_mm)


@lru_cache(maxsize=1)
def _bundled_svg_catalog():
    """Bundled resources cannot change during a running plugin process."""
    from .svg_symbols import SymbolCatalog

    return SymbolCatalog.discover()


def render_symbol(asset_id: str, height_mm: float, variant: str = "default", catalog=None) -> IconVectors:
    """Flag-gated entry point that also supports variants and custom symbols."""
    from .feature_flags import SVG_SYMBOLS, development_feature_enabled

    if not development_feature_enabled(SVG_SYMBOLS):
        if variant != "default":
            raise ValueError("Symbol variants require the svg_symbols development feature")
        return _render_legacy_builtin_icon(asset_id, height_mm)
    if catalog is None:
        from .svg_symbols import symbol_catalog_for_context

        catalog = symbol_catalog_for_context()
    polygons, size = catalog.render(asset_id, height_mm, variant)
    return IconVectors(polygons=polygons, size=size)

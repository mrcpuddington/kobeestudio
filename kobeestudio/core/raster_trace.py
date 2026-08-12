"""Deterministic PNG-to-filled-SVG conversion for PCB graphics."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Tuple


MAX_PNG_BYTES = 20 * 1024 * 1024
MAX_PNG_PIXELS = 20_000_000


@dataclass(frozen=True)
class RasterTraceSettings:
    threshold: int = 128
    invert: bool = False
    alpha_cutoff: int = 16
    auto_crop: bool = True
    smoothing: int = 0
    despeckle_pixels: int = 0
    width_mm: float = 20.0

    def __post_init__(self) -> None:
        if not 0 <= self.threshold <= 255 or not 0 <= self.alpha_cutoff <= 255:
            raise ValueError("Threshold and alpha cutoff must be 0–255")
        if not 0 <= self.smoothing <= 3 or not 0 <= self.despeckle_pixels <= 10000:
            raise ValueError("Smoothing or despeckle value is out of range")
        if not 0.1 <= self.width_mm <= 1000:
            raise ValueError("Output width must be between 0.1 and 1000 mm")


@dataclass(frozen=True)
class RasterTraceResult:
    svg: bytes
    preview_png: bytes
    pixel_size: Tuple[int, int]
    settings: RasterTraceSettings


def _pillow():
    try:
        from PIL import Image, ImageFilter
    except ImportError as error:
        raise RuntimeError("PNG conversion requires Pillow; recreate the KiCad plugin environment") from error
    return Image, ImageFilter


def trace_png_bytes(data: bytes, settings: RasterTraceSettings = RasterTraceSettings()) -> RasterTraceResult:
    if not isinstance(data, bytes) or not data or len(data) > MAX_PNG_BYTES:
        raise ValueError("PNG must be between 1 byte and 20 MiB")
    Image, ImageFilter = _pillow()
    try:
        image = Image.open(io.BytesIO(data)); image.load(); image = image.convert("RGBA")
    except Exception as error:
        raise ValueError("Could not read PNG: {}".format(error)) from error
    if image.width * image.height > MAX_PNG_PIXELS:
        raise ValueError("PNG exceeds the 20 megapixel safety limit")
    luminance = image.convert("L")
    if settings.smoothing:
        luminance = luminance.filter(ImageFilter.MedianFilter(settings.smoothing * 2 + 1))
    alpha = image.getchannel("A")
    mask = Image.new("1", image.size)
    pixels, values, alphas = mask.load(), luminance.load(), alpha.load()
    for y in range(image.height):
        for x in range(image.width):
            dark = values[x, y] < settings.threshold
            if settings.invert: dark = not dark
            pixels[x, y] = bool(dark and alphas[x, y] >= settings.alpha_cutoff)
    if settings.despeckle_pixels:
        _remove_small_components(mask, settings.despeckle_pixels)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError("Trace settings produced no visible graphic")
    if settings.auto_crop:
        mask = mask.crop(bbox)
    width, height = mask.size
    mm_per_pixel = settings.width_mm / float(width)
    # Run-length rectangles are deliberately simple, deterministic and preserve
    # holes. KiCad merges visually adjacent filled regions without raster loss.
    paths = []
    source = mask.load()
    for y in range(height):
        x = 0
        while x < width:
            while x < width and not source[x, y]: x += 1
            start = x
            while x < width and source[x, y]: x += 1
            if start < x:
                paths.append('<rect x="{}" y="{}" width="{}" height="1"/>'.format(start, y, x - start))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           'width="{mw}mm" height="{mh}mm"><g fill="#000">{paths}</g></svg>').format(
        w=width, h=height, mw=settings.width_mm, mh=height * mm_per_pixel, paths="".join(paths)
    ).encode("utf-8")
    preview = io.BytesIO(); mask.convert("L").save(preview, format="PNG")
    return RasterTraceResult(svg, preview.getvalue(), (width, height), settings)


def _remove_small_components(mask, minimum: int) -> None:
    pixels = mask.load(); width, height = mask.size; seen = set()
    for y in range(height):
        for x in range(width):
            if not pixels[x, y] or (x, y) in seen: continue
            stack = [(x, y)]; seen.add((x, y)); group = []
            while stack:
                point = stack.pop(); group.append(point); px, py = point
                for neighbour in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
                    nx, ny = neighbour
                    if 0 <= nx < width and 0 <= ny < height and pixels[nx,ny] and neighbour not in seen:
                        seen.add(neighbour); stack.append(neighbour)
            if len(group) < minimum:
                for px, py in group: pixels[px, py] = False


def trace_png_file(path: Path, settings: RasterTraceSettings = RasterTraceSettings()) -> RasterTraceResult:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("PNG must be a regular file")
    return trace_png_bytes(path.read_bytes(), settings)

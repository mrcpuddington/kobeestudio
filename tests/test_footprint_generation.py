"""Regression checks for the Kobee Studio geometry/export boundary.

Run with KiCad's embedded Python, for example:
``/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9 -m unittest``.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

try:
    import pcbnew
except ImportError:  # pragma: no cover - lets normal Python discover the suite
    pcbnew = None

from kibeezard.core.composition import CompositionDocument, DocumentStyle, Padding, ShapeStyle, TypographyStyle
from kibeezard.core.legacy_adapter import build_footprint_payload, legacy_settings_from_payload
from kibeezard.core.icon_catalog import BUILTIN_ICONS
from kibeezard.core.pin_header import PinHeaderSpec
from kibeezard.core.studio_artwork import TextVectorizer, render_header_artwork, render_label_artwork, serialize_artwork
from kibeezard.core.text_geometry import TextGeometry
from kibeezard.core.transforms import fit_preview_polygons, preview_polygons
from kibeezard.integration.kicad_compatibility import KiCadCompatibility


@unittest.skipIf(pcbnew is None, "requires KiCad's embedded Python")
class FootprintGenerationTests(unittest.TestCase):
    labels = ("FRONT", "BOTTOM", "ABC123", "R2D7")
    layer_cases = (
        ("F.SilkS", "F.Cu", "F.Silkscreen"),
        ("B.SilkS", "B.Cu", "B.Silkscreen"),
        ("F.Cu", "F.Cu", "F.Cu"),
        ("B.Cu", "B.Cu", "B.Cu"),
        ("F.Mask", "F.Cu", "F.Mask"),
        ("B.Mask", "B.Cu", "B.Mask"),
    )

    def make_output(self, text, layer, configure=None):
        geometry = TextGeometry()
        geometry.buzzard.fontName = "UbuntuMono-B"
        if configure:
            configure(geometry.buzzard)
        geometry.generate(text)
        return geometry.footprint("test", layer)

    def studio_style(self, filled=False):
        return DocumentStyle(
            typography=TypographyStyle(height_mm=1.0),
            shape=ShapeStyle(
                padding=Padding.symmetric(0.4, 0.3),
                border_thickness_mm=0.0 if filled else 0.2,
                corner_radius_mm=0.5,
                feature_size_mm=0.6,
                filled=filled,
                inverted=filled,
            ),
        )

    def test_acceptance_labels_parse_on_all_supported_layers(self):
        compatibility = KiCadCompatibility()
        for text in self.labels:
            for layer, owner, graphic in self.layer_cases:
                with self.subTest(text=text, layer=layer):
                    output = self.make_output(text, layer)
                    footprint = compatibility.parse_footprint(output)
                    self.assertEqual(owner, footprint.GetLayerName())
                    self.assertEqual({graphic}, {item.GetLayerName() for item in footprint.GraphicalItems()})

    def test_bottom_coordinates_are_a_single_x_mirror_of_front(self):
        pattern = r"\(xy (-?[0-9.]+) (-?[0-9.]+)\)"
        for front_layer, bottom_layer in (
            ("F.SilkS", "B.SilkS"),
            ("F.Cu", "B.Cu"),
            ("F.Mask", "B.Mask"),
        ):
            with self.subTest(front=front_layer, bottom=bottom_layer):
                front = self.make_output("R2D7", front_layer)
                bottom = self.make_output("R2D7", bottom_layer)
                front_points = [(float(x), float(y)) for x, y in re.findall(pattern, front)]
                bottom_points = [(float(x), float(y)) for x, y in re.findall(pattern, bottom)]
                self.assertEqual(len(front_points), len(bottom_points))
                for (front_x, front_y), (bottom_x, bottom_y) in zip(front_points, bottom_points):
                    self.assertAlmostEqual(-front_x, bottom_x, places=6)
                    self.assertAlmostEqual(front_y, bottom_y, places=6)

    def test_preview_conversion_keeps_one_coordinate_representation(self):
        source = [[SimpleNamespace(x=-2, y=-1), SimpleNamespace(x=2, y=1)]]
        front = preview_polygons(source, "F.SilkS")
        bottom = preview_polygons(source, "B.Mask")
        self.assertEqual([[(-2.0, -1.0), (2.0, 1.0)]], front)
        self.assertEqual([[(2.0, -1.0), (-2.0, 1.0)]], bottom)

        fitted = fit_preview_polygons(front, width=200, height=100)
        xs = [point[0] for polygon in fitted for point in polygon]
        ys = [point[1] for polygon in fitted for point in polygon]
        self.assertAlmostEqual(0.0, min(xs) + max(xs))
        self.assertAlmostEqual(0.0, min(ys) + max(ys))
        self.assertLessEqual(max(xs) - min(xs), 180.0)
        self.assertLessEqual(max(ys) - min(ys), 90.0)

    def test_generated_footprint_embeds_versioned_and_legacy_edit_data(self):
        settings = {
            "MultiLineText": "R2D7",
            "FontComboBox": "UbuntuMono-B",
            "HeightCtrl": "2.0",
            "WidthCtrl": "0.0",
            "LineSpacingCtrl": "1.5",
            "AlignmentChoice": "Center",
            "PaddingTopCtrl": "0.5",
            "PaddingRightCtrl": "0.5",
            "PaddingBottomCtrl": "0.5",
            "PaddingLeftCtrl": "0.5",
            "CapLeftChoice": "(",
            "CapRightChoice": ")",
            "LayerComboBox": "B.SilkS",
        }
        payload = build_footprint_payload(settings)
        encoded = base64.b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("ascii")
        footprint = KiCadCompatibility().parse_footprint(self.make_output("R2D7", "B.SilkS").replace("test", encoded, 1))
        embedded = footprint.GetKeywords()
        self.assertTrue(embedded.startswith("kb_params="))
        restored_payload = json.loads(base64.b64decode(embedded[10:]).decode("utf-8"))
        self.assertEqual(settings, legacy_settings_from_payload(restored_payload))
        self.assertEqual("B.SilkS", CompositionDocument.from_dict(restored_payload["document"]).output_layer)

    def test_all_studio_shapes_parse_and_keep_requested_layer(self):
        vectorizer = TextVectorizer(TextGeometry().buzzard)
        compatibility = KiCadCompatibility()
        for shape in (
            "rectangle",
            "rounded_rectangle",
            "pill",
            "custom_ends",
            "custom_long_edges",
            "pointer",
            "flag",
            "tab",
            "chamfer",
            "hexagon",
        ):
            for layer, owner, graphic in self.layer_cases:
                with self.subTest(shape=shape, layer=layer):
                    artwork = render_label_artwork(vectorizer, "R2D7", self.studio_style(), layer, shape)
                    footprint = compatibility.parse_footprint(serialize_artwork(artwork, "test", layer))
                    self.assertEqual(owner, footprint.GetLayerName())
                    self.assertEqual({graphic}, {item.GetLayerName() for item in footprint.GraphicalItems()})

    def test_pin_header_payload_parses_on_all_supported_layers(self):
        vectorizer = TextVectorizer(TextGeometry().buzzard)
        compatibility = KiCadCompatibility()
        settings = {"StudioModeChoice": "2.54 mm Pin Header"}
        for layer, owner, graphic in self.layer_cases:
            with self.subTest(layer=layer):
                spec = PinHeaderSpec(
                    pin_count=4,
                    pin_labels=("VCC", "GND", "SDA", "SCL"),
                    pad_clearance_mm=6.0,
                    opening_mode="continuous",
                    shape="rounded_rectangle",
                    output_layer=layer,
                    style=self.studio_style(),
                )
                artwork = render_header_artwork(vectorizer, spec)
                payload = build_footprint_payload(
                    settings,
                    document=artwork.document,
                    feature={"kind": "pin_header_2_54", "data": spec.to_dict()},
                )
                encoded = base64.b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("ascii")
                footprint = compatibility.parse_footprint(serialize_artwork(artwork, encoded, layer))
                self.assertEqual(owner, footprint.GetLayerName())
                self.assertEqual({graphic}, {item.GetLayerName() for item in footprint.GraphicalItems()})
                restored = json.loads(base64.b64decode(footprint.GetKeywords()[10:]).decode("utf-8"))
                self.assertEqual(spec, PinHeaderSpec.from_dict(restored["feature"]["data"]))
                self.assertEqual(5, len([item for item in artwork.document.objects if item.kind == "guide"]))

    def test_all_builtin_icons_parse_on_every_supported_layer(self):
        vectorizer = TextVectorizer(TextGeometry().buzzard)
        compatibility = KiCadCompatibility()
        for icon in BUILTIN_ICONS:
            for layer, owner, graphic in self.layer_cases:
                with self.subTest(icon=icon.asset_id, layer=layer):
                    artwork = render_label_artwork(
                        vectorizer,
                        "ICON",
                        self.studio_style(),
                        layer,
                        "rounded_rectangle",
                        icon_id=icon.asset_id,
                        icon_position="left",
                        icon_height_mm=1.0,
                    )
                    settings = {
                        "MultiLineText": "ICON",
                        "IconChoice": icon.name,
                        "IconPositionChoice": "Left of text",
                        "IconHeightCtrl": 1.0,
                        "IconGapCtrl": 0.3,
                    }
                    payload = build_footprint_payload(settings, document=artwork.document)
                    encoded = base64.b64encode(
                        json.dumps(payload, sort_keys=True).encode("utf-8")
                    ).decode("ascii")
                    footprint = compatibility.parse_footprint(
                        serialize_artwork(artwork, encoded, layer)
                    )
                    self.assertEqual(owner, footprint.GetLayerName())
                    self.assertEqual(
                        {graphic},
                        {item.GetLayerName() for item in footprint.GraphicalItems()},
                    )
                    restored = json.loads(
                        base64.b64decode(footprint.GetKeywords()[10:]).decode("utf-8")
                    )
                    self.assertEqual(settings, legacy_settings_from_payload(restored))
                    self.assertTrue(
                        any(
                            item["kind"] == "icon" and item["asset_id"] == icon.asset_id
                            for item in restored["document"]["objects"]
                        )
                    )

    def test_legacy_text_modes_still_generate(self):
        modes = {
            "plain": ("ABC123", lambda b: None),
            "background-tag": ("[ABC123]", lambda b: (setattr(b, "leftCap", "square"), setattr(b, "rightCap", "square"))),
            "inline-format": ("~{R2D7}", lambda b: setattr(b, "inlineFormat", True)),
            "fixed-width-aligned": ("FRONT", lambda b: (setattr(b, "width", 100), setattr(b, "alignment", "Center"))),
        }
        for name, (text, configure) in modes.items():
            with self.subTest(mode=name):
                output = self.make_output(text, "F.SilkS", configure)
                self.assertIn("(layer F.SilkS)", output)
                self.assertIn("(fp_poly", output)

    def test_font_selection_regression(self):
        for font in ("UbuntuMono-B", "FreddySpark-Regular", "mplus-1mn-medium"):
            with self.subTest(font=font):
                geometry = TextGeometry()
                geometry.buzzard.fontName = font
                self.assertTrue(geometry.generate("R2D7"))

    @unittest.skipUnless(os.path.exists("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"), "requires KiCad CLI on macOS")
    def test_acceptance_board_exports_all_supported_layer_gerbers(self):
        """Exercise the KiCad file parser and Gerber exporter, not only text output."""
        compatibility = KiCadCompatibility()
        cli = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
        with tempfile.TemporaryDirectory() as directory:
            board = pcbnew.BOARD()
            for index, (text, layer) in enumerate(
                (label, layer) for layer, _, _ in self.layer_cases for label in self.labels
            ):
                footprint = compatibility.parse_footprint(self.make_output(text, layer))
                footprint.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(20 + index * 12), pcbnew.FromMM(30)))
                board.Add(footprint)
            board_path = os.path.join(directory, "acceptance.kicad_pcb")
            self.assertTrue(board.Save(board_path))
            output = os.path.join(directory, "gerbers")
            subprocess.run(
                [
                    cli,
                    "pcb",
                    "export",
                    "gerbers",
                    "--layers",
                    ",".join(layer for layer, _, _ in self.layer_cases),
                    "--output",
                    output,
                    board_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            gerbers = [name for name in os.listdir(output) if not name.endswith(".gbrjob")]
            self.assertEqual(6, len(gerbers), gerbers)
            for gerber in gerbers:
                self.assertGreater(os.path.getsize(os.path.join(output, gerber)), 0)

    @unittest.skipUnless(os.path.exists("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"), "requires KiCad CLI on macOS")
    def test_studio_headers_export_all_supported_layer_gerbers(self):
        compatibility = KiCadCompatibility()
        vectorizer = TextVectorizer(TextGeometry().buzzard)
        cli = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
        with tempfile.TemporaryDirectory() as directory:
            board = pcbnew.BOARD()
            for index, (layer, _, _) in enumerate(self.layer_cases):
                spec = PinHeaderSpec(
                    pin_count=4,
                    pin_labels=("VCC", "GND", "SDA", "SCL"),
                    pad_clearance_mm=4.0,
                    opening_mode="continuous",
                    output_layer=layer,
                    style=self.studio_style(),
                )
                artwork = render_header_artwork(vectorizer, spec)
                footprint = compatibility.parse_footprint(serialize_artwork(artwork, "test", layer))
                footprint.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(20 + index * 10)))
                board.Add(footprint)
            board_path = os.path.join(directory, "studio-headers.kicad_pcb")
            self.assertTrue(board.Save(board_path))
            output = os.path.join(directory, "gerbers")
            subprocess.run(
                [
                    cli,
                    "pcb",
                    "export",
                    "gerbers",
                    "--layers",
                    ",".join(layer for layer, _, _ in self.layer_cases),
                    "--output",
                    output,
                    board_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            gerbers = [name for name in os.listdir(output) if not name.endswith(".gbrjob")]
            self.assertEqual(6, len(gerbers), gerbers)
            self.assertTrue(all(os.path.getsize(os.path.join(output, name)) > 0 for name in gerbers))

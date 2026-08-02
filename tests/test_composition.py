"""Milestone 1 checks for versioned Silk Studio composition documents."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError

from kibeezard.core.composition import (
    CompositionDocument,
    DocumentStyle,
    GroupObject,
    GuideObject,
    IconObject,
    Padding,
    Point,
    ShapeObject,
    ShapeStyle,
    Size,
    TextObject,
    TypographyStyle,
)
from kibeezard.core.legacy_adapter import (
    FOOTPRINT_PAYLOAD_FORMAT,
    build_footprint_payload,
    document_from_legacy_settings,
    legacy_settings_from_payload,
)


class CompositionDocumentTests(unittest.TestCase):
    def test_new_label_style_defaults_match_product_defaults(self):
        style = DocumentStyle()
        self.assertEqual(1.2, style.typography.height_mm)
        self.assertEqual(Padding(top=0.5, right=1.2, bottom=0.5, left=1.2), style.shape.padding)

    def make_document(self):
        text = TextObject("text.main", "POWER", Point(1.0, 2.0), 5.0)
        icon = IconObject("icon.power", "power", Point(-2.0, 0.0), Size(1.5, 1.5))
        shape = ShapeObject(
            "shape.background",
            "rounded_rectangle",
            size=Size(12.0, 5.0),
            content_ids=(text.object_id, icon.object_id),
        )
        guide = GuideObject("guide.anchor", "circle", size=Size(2.0, 2.0))
        group = GroupObject("group.label", (shape.object_id, icon.object_id, text.object_id))
        return CompositionDocument(
            objects=(text, icon, shape, guide, group),
            output_layer="B.Mask",
            anchor=Point(0.5, 0.25),
            origin=Point(4.0, 8.0),
            size=Size(12.0, 5.0),
            rotation_deg=90.0,
            alignment="left",
            style=DocumentStyle(
                typography=TypographyStyle("UbuntuMono-B", 2.0, 0.0, 1.5, "left"),
                shape=ShapeStyle(
                    padding=Padding(0.5, 1.0, 0.75, 1.25),
                    border_thickness_mm=0.2,
                    corner_radius_mm=1.0,
                    feature_size_mm=0.8,
                    filled=True,
                    inverted=True,
                    start_cap="rounded",
                    end_cap="square",
                ),
            ),
        )

    def test_round_trip_preserves_every_object_and_setting(self):
        document = self.make_document()
        restored = CompositionDocument.from_json(document.to_json())
        self.assertEqual(document, restored)
        self.assertEqual("bottom", restored.board_side)
        self.assertEqual(1, json.loads(document.to_json())["schema_version"])

    def test_documents_and_nested_values_are_immutable(self):
        document = self.make_document()
        with self.assertRaises(FrozenInstanceError):
            document.output_layer = "F.Cu"
        with self.assertRaises(FrozenInstanceError):
            document.style.shape.corner_radius_mm = 2.0

    def test_document_rejects_invalid_references_and_layers(self):
        with self.assertRaisesRegex(ValueError, "missing objects"):
            CompositionDocument(objects=(GroupObject("group", ("missing",)),))
        with self.assertRaisesRegex(ValueError, "Unsupported Kobee Studio output layer"):
            CompositionDocument(objects=(), output_layer="Edge.Cuts")
        with self.assertRaisesRegex(ValueError, "Unsupported composition schema"):
            CompositionDocument.from_dict({"schema_version": 99, "objects": []})
        with self.assertRaisesRegex(ValueError, "reference cycle"):
            CompositionDocument(
                objects=(
                    GroupObject("group.a", ("group.b",)),
                    GroupObject("group.b", ("group.a",)),
                )
            )

    def test_guide_objects_can_never_export(self):
        with self.assertRaisesRegex(ValueError, "preview-only"):
            GuideObject("guide", exported=True)

    def test_shape_style_validates_outline_and_inversion(self):
        with self.assertRaisesRegex(ValueError, "positive border"):
            ShapeStyle(filled=False, border_thickness_mm=0.0)
        with self.assertRaisesRegex(ValueError, "requires a filled shape"):
            ShapeStyle(filled=False, inverted=True, border_thickness_mm=0.2)

    def test_legacy_settings_adapter_builds_editable_payload(self):
        settings = {
            "MultiLineText": "GND",
            "FontComboBox": "UbuntuMono-B",
            "HeightCtrl": "2.0",
            "WidthCtrl": "8.0",
            "LineSpacingCtrl": "1.5",
            "AlignmentChoice": "Center",
            "PaddingTopCtrl": "0.5",
            "PaddingRightCtrl": "1.0",
            "PaddingBottomCtrl": "0.5",
            "PaddingLeftCtrl": "1.0",
            "CapLeftChoice": "(",
            "CapRightChoice": ")",
            "LayerComboBox": "Bottom Copper (B.Cu)",
        }
        document = document_from_legacy_settings(settings)
        self.assertEqual("B.Cu", document.output_layer)
        self.assertEqual("pill", next(item for item in document.objects if isinstance(item, ShapeObject)).shape)
        self.assertEqual("GND", next(item for item in document.objects if isinstance(item, TextObject)).text)

        payload = build_footprint_payload(settings)
        self.assertEqual(FOOTPRINT_PAYLOAD_FORMAT, payload["format"])
        self.assertEqual(settings, legacy_settings_from_payload(payload))
        self.assertEqual(settings, legacy_settings_from_payload(settings))
        self.assertEqual(document, CompositionDocument.from_dict(payload["document"]))


if __name__ == "__main__":
    unittest.main()

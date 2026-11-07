"""Exercise artwork families and cleanup on an explicitly named disposable board.

This writes test artwork and saves the board. Never point it at a real project.
Run with KiCad's Python, the IPC requirements installed, and PCB Editor open.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kobeestudio.core.component_callout import ComponentCalloutSpec
from kobeestudio.core.composition import DocumentStyle, GraphicObject, ShapeStyle, Size, TypographyStyle
from kobeestudio.core.legacy_adapter import build_footprint_payload
from kobeestudio.core.pin_header import PinHeaderSpec
from kobeestudio.core.studio_artwork import (
    TextVectorizer, render_component_callout_artwork, render_graphic_artwork,
    render_header_artwork, render_label_artwork, render_machine_code_artwork,
    render_multipart_label_artwork,
)
from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.integration.board_tools import BoardToolsService
from kobeestudio.integration.ipc_artwork import IpcArtworkPlacement, METADATA_FIELD_NAME, decode_metadata, selected_artwork
from kobeestudio.integration.ipc_session import IpcSession, unique_client_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--expected-board", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reuse-artwork", action="store_true", help="Resume cleanup after an artwork matrix completed on this disposable board")
    args = parser.parse_args()
    expected = Path(args.expected_board).resolve()
    if not expected.name.startswith("acceptance"):
        raise RuntimeError("The disposable board filename must begin with acceptance")
    session = IpcSession.connect(socket_path=args.socket, client_name=unique_client_name("Kobee acceptance"))
    try:
        board = session.board
        actual = Path(board.document.board_filename)
        if not actual.is_absolute():
            actual = Path(board.document.project.path) / actual
        if actual.resolve() != expected:
            raise RuntimeError("Refusing to change a board other than --expected-board")
        from kipy.geometry import Vector2
        from kipy.board_types import Pad
        from kipy.proto.board.board_types_pb2 import BoardLayer, PadType, PadStackShape

        placement = IpcArtworkPlacement(session)
        vectorizer = TextVectorizer(TextGeometry().buzzard)
        style = DocumentStyle(typography=TypographyStyle(font_name="UbuntuMono-B", height_mm=1.0),
                              shape=ShapeStyle(filled=True, inverted=True))
        graphic = GraphicObject("acceptance-graphic", "acceptance", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 12"><path fill-rule="evenodd" d="M0 0H20V12H0Z M3 3V9H17V3Z"/></svg>', size=Size(12, 8), rotation_deg=27)
        layers = ("F.SilkS", "B.SilkS", "F.Cu", "B.Cu", "F.Mask", "B.Mask")
        cases = []
        if args.reuse_artwork:
            available = {}
            for footprint in board.get_footprints():
                data = selected_artwork([footprint])
                if data:
                    available[data[0].get("MultiLineText")] = footprint
            for layer in layers:
                for name in ("label", "formatted", "symbol", "sections", "connector", "callout", "array", "qr", "barcode", "graphic"):
                    footprint = available["{} {}".format(name, layer)]
                    assert footprint.definition.shapes
                    cases.append({"tool": name, "layer": layer, "id": footprint.id.value, "placement_update": "completed in preceding matrix; existing metadata and geometry reverified"})
        for layer in (() if args.reuse_artwork else layers):
            renders = {
                "label": lambda: render_label_artwork(vectorizer, "R2D7\nREADY 1.5", replace(style, typography=replace(style.typography, alignment="right")), layer, shape="rounded_rectangle"),
                "formatted": lambda: render_label_artwork(vectorizer, "V^{2} D_{0}", style, layer, inline_format=True, underline=True, overline=True),
                "symbol": lambda: render_label_artwork(vectorizer, "GND", style, layer, icon_id="builtin.ground"),
                "sections": lambda: render_multipart_label_artwork(vectorizer, ("VCC", "GND"), style, layer),
                "connector": lambda: render_header_artwork(vectorizer, PinHeaderSpec(4, ("VCC", "GND", "SDA", "SCL"), output_layer=layer, style=style, opening_mode="continuous")),
                "callout": lambda: render_component_callout_artwork(vectorizer, ComponentCalloutSpec("BUTTON", output_layer=layer, style=style)),
                "array": lambda: render_component_callout_artwork(vectorizer, ComponentCalloutSpec("LED1\nLED2\nLED3", array_count=3, output_layer=layer, style=style)),
                "qr": lambda: render_machine_code_artwork("https://kobee.com.au", "qr", .35, 4, layer, vectorizer=vectorizer, presentation="rounded_caption"),
                "barcode": lambda: render_machine_code_artwork("KOBEE-001", "code128", .25, 4, layer, vectorizer=vectorizer, show_content_text=True, content_text="KOBEE-001"),
                "graphic": lambda: render_graphic_artwork(graphic, layer),
            }
            for name, render in renders.items():
                artwork = render()
                settings = {"MultiLineText": "{} {}".format(name, layer), "LayerComboBox": layer}
                payload = build_footprint_payload(settings, document=artwork.document)
                before = len(board.get_footprints())
                placed = placement.place(artwork, payload, layer, start_interactive_move=False)
                assert len(board.get_footprints()) == before + 1
                assert selected_artwork([placed])[0]["MultiLineText"] == settings["MultiLineText"]
                placed.position = Vector2.from_xy_mm(20 + len(cases) % 10 * 22, 20 + len(cases) // 10 * 24)
                placed = board.update_items(placed)[0]
                identifier = placed.id.value
                position = (placed.position.x, placed.position.y)
                updated = placement.place(artwork, payload, layer, old_footprint=placed, start_interactive_move=False)
                assert updated.id.value == identifier
                assert (updated.position.x, updated.position.y) == position
                assert len(board.get_footprints()) == before + 1
                cases.append({"tool": name, "layer": layer, "id": identifier, "placement_update": "passed"})
                print("Passed {} on {}".format(name, layer), flush=True)

        # Ordinary/locked/generated selections exercise the actual cleanup API.
        artwork = render_label_artwork(vectorizer, "R17", style, "F.SilkS")
        source = placement.build_footprint(artwork, {}, "F.SilkS", output_layers=("F.SilkS", "B.SilkS", "F.Cu", "B.Cu", "F.Mask", "B.Mask"))
        source.definition.items = [item for item in source.definition.items if getattr(item, "name", "") != METADATA_FIELD_NAME]
        source.reference_field.text.value = "R17"
        source.reference_field.visible = True
        source.value_field.text.value = "10k"
        source.position = Vector2.from_xy_mm(30, 190)
        source.reference_field.text.position = Vector2.from_xy_mm(30, 187)
        pad = Pad()
        pad.number = "1"
        pad.position = Vector2.from_xy_mm(0, 0)
        pad.pad_type = PadType.PT_SMD
        pad.padstack.layers = (BoardLayer.BL_F_Cu, BoardLayer.BL_F_Paste, BoardLayer.BL_F_Mask)
        pad.padstack.copper_layer(BoardLayer.BL_F_Cu).size = Vector2.from_xy_mm(1, 2)
        pad.padstack.copper_layer(BoardLayer.BL_F_Cu).shape = PadStackShape.PSS_RECTANGLE
        source.definition.add_item(pad)
        source = board.create_items(source)[0]
        board.clear_selection()
        board.add_to_selection(source)
        designator_payload = build_footprint_payload({"MultiLineText": "R17"}, document=artwork.document, feature={"kind": "designator_label", "source_footprint_id": source.id.value})
        assert placement.place_designators(((source, artwork, designator_payload, "F.SilkS", None),)) == (1, 0)
        generated = next(
            item for item in board.get_footprints()
            if any(getattr(field, "name", "") == METADATA_FIELD_NAME
                   and decode_metadata(field.text.value).get("feature", {}).get("source_footprint_id") == source.id.value
                   for field in item.definition.items)
        )
        assert placement.place_designators(((source, artwork, designator_payload, "F.SilkS", generated),)) == (0, 1)
        service = BoardToolsService(session)
        # KiCad invalidates the native selection when replacing a footprint.
        # Reselect the refreshed component, as a user does for a later action.
        source = board.get_items_by_id([source.id])[0]
        board.clear_selection()
        board.add_to_selection(source)
        result = service.remove_designators("selected")
        assert result.affected == 1 and result.removed_items == 1
        source = board.get_items_by_id([source.id])[0]
        assert source.reference_field.text.value == "R17" and not source.reference_field.visible
        non_silk = [item.proto.SerializeToString() for item in source.definition.items if getattr(item, "layer", None) not in (BoardLayer.BL_F_SilkS, BoardLayer.BL_B_SilkS)]
        board.clear_selection()
        board.add_to_selection(source)
        result = service.remove_silkscreen("selected")
        assert result.affected == 1 and result.removed_items > 0
        source = board.get_items_by_id([source.id])[0]
        assert non_silk == [item.proto.SerializeToString() for item in source.definition.items if getattr(item, "layer", None) not in (BoardLayer.BL_F_SilkS, BoardLayer.BL_B_SilkS)]
        assert source.reference_field.text.value == "R17" and source.value_field.text.value == "10k"
        source.locked = True
        board.update_items(source)
        board.clear_selection()
        generated_for_skip = next(item for item in board.get_footprints() if item.id.value == cases[0]["id"])
        board.add_to_selection([source, generated_for_skip])
        skipped = service.remove_silkscreen("selected")
        assert skipped.affected == 0 and skipped.skipped == 2
        before_board_cleanup = board.get_footprints()
        artwork_ids = {case["id"] for case in cases}
        protected = {
            item.id.value: item.proto.SerializeToString()
            for item in before_board_cleanup if item.locked or item.id.value in artwork_ids
        }
        for operation in (service.remove_designators, service.remove_silkscreen):
            operation("board")
            refreshed = {item.id.value: item for item in board.get_footprints()}
            for identifier, data in protected.items():
                assert refreshed[identifier].proto.SerializeToString() == data
        source = board.get_items_by_id([source.id])[0]
        assert source.reference_field.text.value == "R17" and source.value_field.text.value == "10k"
        board.save()
        report = {"version": "1.5.20", "kicad": session.version(), "board": str(expected), "cases": cases,
                  "cleanup": {"designator_create_update_remove": "passed", "silkscreen_removal": "passed", "non_silk_and_pad_preservation": "passed", "locked_and_generated_skip": "passed", "whole_board_scope_preserves_locked_and_generated": "passed"},
                  "saved": True, "reused_artwork": args.reuse_artwork, "footprints": len(board.get_footprints())}
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(json.dumps({"artwork_cases": len(cases), "cleanup": report["cleanup"], "saved": True}))
    finally:
        session.close()


if __name__ == "__main__":
    main()

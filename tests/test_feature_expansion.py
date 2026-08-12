from __future__ import annotations

import json
import tempfile
import unittest
import io
from pathlib import Path

from kobeestudio.core.component_presets import ComponentPresetStore
from kobeestudio.core.composition import CompositionDocument, DocumentStyle, GraphicObject, Point, Size, TypographyStyle
from kobeestudio.core.font_library import FontLibraryStore
from kobeestudio.core.library_archive import export_library, restore_library
from kobeestudio.core.pin_header import PinHeaderSpec, maximum_pin_label_height
from kobeestudio.core.raster_trace import RasterTraceSettings, trace_png_bytes
from kobeestudio.core.svg_symbols import validate_svg_bytes
from kobeestudio.integration.board_tools import BoardToolsService


class GraphicObjectTests(unittest.TestCase):
    def test_graphic_round_trip_keeps_fallback_and_transform(self):
        graphic = GraphicObject("graphic", "custom.asset", "<svg/>", Point(2, -3), Size(10, 4),
                                37.5, True, False)
        restored = CompositionDocument.from_json(CompositionDocument((graphic,)).to_json())
        self.assertEqual(graphic, restored.objects[0])

    def test_graphics_accept_static_strokes_while_symbol_rules_remain_strict(self):
        stroked=b'<svg xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="0" x2="10" y2="0" fill="none" stroke="black" stroke-width="2"/></svg>'
        validate_svg_bytes(stroked, require_renderable=True, allow_strokes=True)
        with self.assertRaisesRegex(ValueError,"converted to filled paths"):
            validate_svg_bytes(stroked, require_renderable=True)


class ComponentPresetStoreTests(unittest.TestCase):
    def test_global_and_project_presets_are_independent_and_update_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            global_store = ComponentPresetStore.global_store(root / "data")
            project_store = ComponentPresetStore.project_store(root / "board.kicad_pcb")
            saved = global_store.save("My QFN", 5.2, 5.1, "rounded_rectangle", 0.25)
            changed = global_store.save("My QFN edited", 5.3, 5.1, "pill", 0.3, saved.preset_id)
            project_store.save("Project body", 7, 8, "rectangle", 0)
            self.assertEqual("My QFN edited", global_store.list()[0].name)
            self.assertEqual("Project body", project_store.list()[0].name)
            global_store.delete(changed.preset_id)
            self.assertEqual((), global_store.list())


class FontLibraryStoreTests(unittest.TestCase):
    def test_bundled_catalog_is_available_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            families = FontLibraryStore(Path(directory)).load_catalog()
            self.assertIn("Roboto", {item["family"] for item in families})


class LibraryArchiveExpansionTests(unittest.TestCase):
    def test_fonts_and_component_presets_are_backed_up_and_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination, archive = root / "source", root / "destination", root / "data.zip"
            (source / "fonts/v1/x").mkdir(parents=True)
            (source / "fonts/v1/x/font.ttf").write_bytes(b"font")
            (source / "component-presets/v1").mkdir(parents=True)
            (source / "component-presets/v1/x.json").write_text("{}")
            self.assertEqual(2, export_library(source, archive))
            self.assertEqual(2, restore_library(archive, destination))
            self.assertTrue((destination / "fonts/v1/x/font.ttf").is_file())
            self.assertTrue((destination / "component-presets/v1/x.json").is_file())


class ConnectorPitchTests(unittest.TestCase):
    def test_common_pitches_round_trip_and_drive_typography_limit(self):
        for pitch in (1.0, 1.25, 1.27, 1.5, 2.0, 2.5, 2.54, 3.5, 3.81, 5.0, 5.08):
            spec = PinHeaderSpec(pin_count=1, pin_labels=("1",), pitch_mm=pitch,
                                 style=DocumentStyle(typography=TypographyStyle(height_mm=min(0.7, pitch - 0.2))))
            self.assertEqual(spec, PinHeaderSpec.from_dict(spec.to_dict()))
            self.assertAlmostEqual(pitch - 0.2, maximum_pin_label_height(pitch))


class RasterTraceTests(unittest.TestCase):
    def test_transparency_invert_crop_and_despeckle_are_deterministic(self):
        from PIL import Image
        image = Image.new("RGBA", (8, 6), (255, 255, 255, 0))
        for y in range(1, 5):
            for x in range(2, 6): image.putpixel((x, y), (0, 0, 0, 255))
        image.putpixel((7, 5), (0, 0, 0, 255))
        data = io.BytesIO(); image.save(data, "PNG")
        settings = RasterTraceSettings(threshold=128, alpha_cutoff=10, auto_crop=True, despeckle_pixels=2, width_mm=4)
        first = trace_png_bytes(data.getvalue(), settings)
        second = trace_png_bytes(data.getvalue(), settings)
        self.assertEqual(first.svg, second.svg)
        self.assertEqual((4, 4), first.pixel_size)
        validate_svg_bytes(first.svg, require_renderable=True)


class _Text:
    def __init__(self, value="R1", layer="F.SilkS"): self.value=value; self.layer=layer
class _Field:
    def __init__(self, name="Reference", value="R1", layer="F.SilkS"): self.name=name; self.text=_Text(value,layer); self.layer=layer; self.visible=True
class BoardText:
    def __init__(self, layer): self.layer=layer
class BoardShape:
    def __init__(self, layer): self.layer=layer
class Pad:
    def __init__(self, layer): self.layer=layer
class _Definition:
    def __init__(self): self.items=[BoardText("F.SilkS"),BoardShape("B.SilkS"),BoardShape("F.Fab"),Pad("F.Cu")]
class _Footprint:
    def __init__(self, identifier="one", locked=False):
        self.id=identifier; self.locked=locked; self.definition=_Definition(); self.reference_field=_Field(); self.value_field=_Field("Value","10k")
class _Board:
    def __init__(self, footprints): self.items=footprints; self.updated=[]; self.removed=[]; self.events=[]
    def get_selection(self): return self.items
    def get_footprints(self): return self.items
    def update_items(self, items): self.updated.extend(items); return list(items)
    def remove_items(self, items): self.removed.extend(items)
    def begin_commit(self): self.events.append("begin"); return "tx"
    def push_commit(self, tx, message): self.events.append(("push",message))
    def drop_commit(self, tx): self.events.append("drop")
class _Session:
    def __init__(self, board): self.board=board
    def begin_commit(self): return self.board.begin_commit()
    def commit(self, tx, message): self.board.push_commit(tx,message)
    def discard(self, tx): self.board.drop_commit(tx)


class BoardToolsTests(unittest.TestCase):
    def test_designator_cleanup_hides_semantic_field_in_one_commit(self):
        footprint=_Footprint(); board=_Board([footprint]); result=BoardToolsService(_Session(board)).remove_designators("selected")
        self.assertFalse(footprint.reference_field.visible); self.assertEqual(1,result.affected)
        self.assertEqual("begin",board.events[0]); self.assertEqual("push",board.events[-1][0])

    def test_silkscreen_cleanup_preserves_fab_pads_and_field_values(self):
        footprint=_Footprint(); board=_Board([footprint]); result=BoardToolsService(_Session(board)).remove_silkscreen("board")
        self.assertEqual(["F.Fab","F.Cu"],[item.layer for item in footprint.definition.items])
        self.assertEqual("R1",footprint.reference_field.text.value); self.assertFalse(footprint.reference_field.visible)
        self.assertEqual(2,result.removed_items)

    def test_locked_footprints_are_skipped(self):
        board=_Board([_Footprint(locked=True)]); result=BoardToolsService(_Session(board)).remove_designators("selected")
        self.assertEqual((0,1),(result.affected,result.skipped)); self.assertEqual([],board.events)


if __name__ == "__main__":
    unittest.main()

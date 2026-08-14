from __future__ import annotations

import json
import tempfile
import unittest
import io
import zipfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from kobeestudio.core.component_presets import ComponentPresetStore
from kobeestudio.core.composition import CompositionDocument, DocumentStyle, GraphicObject, Point, Size, TypographyStyle
from kobeestudio.core.font_library import (
    PCB_SYMBOL_GLYPHS,
    FontLibraryStore,
    catalog_family_likely_supports_symbols,
    missing_font_glyphs,
)
from kobeestudio.core.library_archive import export_library, restore_library
from kobeestudio.core.pin_header import PinHeaderSpec, maximum_pin_label_height
from kobeestudio.core.raster_trace import RasterTraceSettings, trace_png_bytes
from kobeestudio.core.svg_symbols import SvgAssetStore, validate_svg_bytes
from kobeestudio.core.studio_artwork import render_graphic_artwork
from kobeestudio.integration.board_tools import BoardToolsService
from kobeestudio.integration.ipc_artwork import (
    DESIGNATOR_METADATA_FIELD_NAME,
    encode_metadata,
)


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

    def test_embedded_graphic_fallback_applies_position_size_rotation_and_mirror(self):
        svg='<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="5"/></svg>'
        graphic=GraphicObject("graphic","missing.asset",svg,Point(3,4),Size(20,10),90,True,False)
        artwork=render_graphic_artwork(graphic,"F.SilkS")
        points=[point for polygon in artwork.filled_polygons for point in polygon]
        self.assertAlmostEqual(3,sum(point.x for point in points)/len(points),places=6)
        self.assertAlmostEqual(4,sum(point.y for point in points)/len(points),places=6)
        self.assertEqual(graphic,artwork.document.objects[0])
        self.assertTrue(artwork.guides)


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
            self.assertGreaterEqual(len(families), 1900)
            roboto = next(item for item in families if item["family"] == "Roboto")
            self.assertIn("400i", roboto["fonts"])
            self.assertTrue(catalog_family_likely_supports_symbols(roboto))

    def test_symbol_filter_is_coarse_but_face_coverage_is_exact(self):
        fonts = Path(__file__).resolve().parents[1] / "kobeestudio/fonts"
        self.assertEqual((), missing_font_glyphs(fonts / "mplus-1mn-medium.ttf", PCB_SYMBOL_GLYPHS))
        self.assertEqual(("μ",), missing_font_glyphs(fonts / "FreddySpark-Regular.ttf", PCB_SYMBOL_GLYPHS))
        self.assertTrue(catalog_family_likely_supports_symbols({"family": "Example", "subsets": ["greek"]}))
        self.assertTrue(catalog_family_likely_supports_symbols({"family": "Noto Sans Math", "subsets": ["menu"]}))
        self.assertFalse(catalog_family_likely_supports_symbols({"family": "Example", "subsets": ["latin"]}))

    def test_install_retains_licence_and_missing_face_can_be_repaired_in_place(self):
        bundled = Path(__file__).resolve().parents[1] / "kobeestudio/fonts/FreddySpark-Regular.ttf"
        with tempfile.TemporaryDirectory() as directory:
            store = FontLibraryStore(Path(directory))
            face = store.install_bytes(bundled.read_bytes(), family="Example Sans", licence_text="OFL text", licence_url="https://example.test/OFL.txt")
            self.assertEqual("OFL text", (face.path.parent / "LICENSE.txt").read_text())
            renderer_name = face.renderer_name
            face.path.unlink()
            self.assertEqual((), store.list())
            self.assertTrue(store.records()[0].missing)
            with patch.object(store, "_google_face_bytes", return_value=(bundled.read_bytes(), "https://fonts.test/font.woff2")), patch.object(store, "_google_licence", return_value=("Restored OFL", "https://fonts.test/OFL.txt")):
                repaired = store.repair(face.face_id)
            self.assertEqual(renderer_name, repaired.renderer_name)
            self.assertFalse(repaired.missing)
            self.assertEqual("Restored OFL", (repaired.path.parent / "LICENSE.txt").read_text())

    def test_failed_catalog_refresh_keeps_bundled_offline_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FontLibraryStore(Path(directory))
            with patch("kobeestudio.core.font_library._urlopen", side_effect=OSError("offline")):
                with self.assertRaises(OSError): store.refresh_catalog()
            self.assertIn("Roboto", {item["family"] for item in store.load_catalog()})

    def test_selected_face_preview_is_cached_and_install_reuses_its_download(self):
        bundled = Path(__file__).resolve().parents[1] / "kobeestudio/fonts/FreddySpark-Regular.ttf"
        with tempfile.TemporaryDirectory() as directory:
            store = FontLibraryStore(Path(directory))
            with patch.object(
                store, "_google_face_bytes",
                return_value=(bundled.read_bytes(), "https://fonts.test/face.woff2"),
            ) as download, patch.object(
                store, "_google_licence",
                return_value=("OFL", "https://fonts.test/OFL.txt"),
            ):
                first_path, _url, first_cached = store.preview_face("Preview Sans", 400, "normal")
                second_path, _url, second_cached = store.preview_face("Preview Sans", 400, "normal")
                installed = store.download_google_face("Preview Sans", 400, "normal")
            self.assertFalse(first_cached)
            self.assertTrue(second_cached)
            self.assertEqual(first_path, second_path)
            self.assertTrue(first_path.is_file())
            self.assertTrue(installed.path.is_file())
            download.assert_called_once_with("Preview Sans", 400, "normal")

    def test_preview_cache_is_not_part_of_portable_library_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cache/font-previews/v1").mkdir(parents=True)
            (root / "cache/font-previews/v1/preview.ttf").write_bytes(b"cache")
            archive = root / "backup.zip"
            self.assertEqual(0, export_library(root, archive))
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual([], bundle.namelist())


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

    def test_custom_pitch_boundaries_are_enforced(self):
        for pitch in (0.5, 20.0):
            PinHeaderSpec(pin_count=1, pin_labels=("1",), pitch_mm=pitch,
                          style=DocumentStyle(typography=TypographyStyle(height_mm=0.2)))
        for pitch in (0.49, 20.01):
            with self.assertRaisesRegex(ValueError, "0.50 and 20.00"):
                PinHeaderSpec(pin_count=1, pin_labels=("1",), pitch_mm=pitch,
                              style=DocumentStyle(typography=TypographyStyle(height_mm=0.2)))


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

    def test_saved_png_trace_reopens_and_updates_same_asset(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "mark.png"
            image = Image.new("RGBA", (4, 2), (0, 0, 0, 255)); image.save(source)
            store = SvgAssetStore.global_store(root / "data")
            first = trace_png_bytes(source.read_bytes(), RasterTraceSettings(width_mm=4))
            asset = store.upload_traced_png(source, first.svg, "Mark", asdict(first.settings))
            retained_source, raw = store.traced_png_details(asset)
            self.assertEqual(source.read_bytes(), retained_source.read_bytes())
            changed = trace_png_bytes(source.read_bytes(), RasterTraceSettings(width_mm=8, invert=False))
            updated = store.update_traced_png(asset, changed.svg, asdict(changed.settings))
            self.assertEqual(asset.asset_id, updated.asset_id)
            self.assertEqual(8, store.traced_png_details(updated)[1]["width_mm"])


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
        self.id=identifier; self.locked=locked; self.definition=_Definition(); self.reference_field=_Field(); self.value_field=_Field("Value","10k"); self.datasheet_field=_Field("Datasheet","url"); self.description_field=_Field("Description","part")
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

    def test_designator_cleanup_removes_only_linked_embedded_geometry(self):
        footprint = _Footprint()
        generated = BoardShape("F.SilkS")
        generated.id = type("Id", (), {"value": "kobee-shape"})()
        metadata = _Field(DESIGNATOR_METADATA_FIELD_NAME, "", "F.SilkS")
        metadata.text.value = encode_metadata(
            {"feature": {"kind": "designator_label", "embedded_item_ids": ["kobee-shape"]}}
        )
        unrelated = BoardShape("F.SilkS")
        unrelated.id = type("Id", (), {"value": "user-shape"})()
        footprint.definition.items.extend((generated, metadata, unrelated))
        board = _Board([footprint])
        result = BoardToolsService(_Session(board)).remove_designators("selected")
        self.assertIn(unrelated, footprint.definition.items)
        self.assertNotIn(generated, footprint.definition.items)
        self.assertNotIn(metadata, footprint.definition.items)
        self.assertEqual(2, result.removed_items)

    def test_silkscreen_cleanup_preserves_fab_pads_and_field_values(self):
        footprint=_Footprint(); board=_Board([footprint]); result=BoardToolsService(_Session(board)).remove_silkscreen("board")
        self.assertEqual(["F.Fab","F.Cu"],[item.layer for item in footprint.definition.items])
        self.assertEqual("R1",footprint.reference_field.text.value); self.assertFalse(footprint.reference_field.visible)
        self.assertEqual(2,result.removed_items)

    def test_silkscreen_cleanup_hides_all_semantic_fields_without_erasing_values(self):
        footprint=_Footprint(); board=_Board([footprint]); BoardToolsService(_Session(board)).remove_silkscreen("board")
        self.assertFalse(footprint.datasheet_field.visible); self.assertFalse(footprint.description_field.visible)
        self.assertEqual(("url","part"),(footprint.datasheet_field.text.value,footprint.description_field.text.value))

    def test_silkscreen_cleanup_preserves_linked_designator_artwork(self):
        footprint = _Footprint()
        designator = BoardShape("F.SilkS")
        designator.id = type("Id", (), {"value": "kobee-designator"})()
        metadata = _Field(DESIGNATOR_METADATA_FIELD_NAME, "", "F.SilkS")
        metadata.text.value = encode_metadata(
            {"feature": {"kind": "designator_label", "embedded_item_ids": ["kobee-designator"]}}
        )
        component_mark = BoardShape("F.SilkS")
        footprint.definition.items.extend((designator, metadata, component_mark))
        result = BoardToolsService(_Session(_Board([footprint]))).remove_silkscreen("board")
        self.assertIn(designator, footprint.definition.items)
        self.assertIn(metadata, footprint.definition.items)
        self.assertNotIn(component_mark, footprint.definition.items)
        self.assertEqual(3, result.removed_items)

    def test_partial_ipc_update_rolls_back_instead_of_committing(self):
        footprint=_Footprint(); board=_Board([footprint]); board.update_items=lambda items: []
        with self.assertRaisesRegex(RuntimeError,"rolled back"):
            BoardToolsService(_Session(board)).remove_designators("selected")
        self.assertIn("drop",board.events)
        self.assertFalse(any(isinstance(item,tuple) and item[0]=="push" for item in board.events))

    def test_locked_footprints_are_skipped(self):
        board=_Board([_Footprint(locked=True)]); result=BoardToolsService(_Session(board)).remove_designators("selected")
        self.assertEqual((0,1),(result.affected,result.skipped)); self.assertEqual([],board.events)


if __name__ == "__main__":
    unittest.main()

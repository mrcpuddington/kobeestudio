"""Checks for SVG discovery, variants, linked labels, and custom uploads."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kobeestudio.core.icon_catalog import BUILTIN_ICONS, LABEL_PRESETS, render_builtin_icon, render_symbol
from kobeestudio.core.feature_flags import FeatureFlags
from kobeestudio.core.svg_symbols import (
    SvgAssetStore,
    SymbolCatalog,
    discover_bundled_symbols,
    format_symbol_reference,
    parse_symbol_reference,
    symbol_catalog_for_context,
    validate_svg_bytes,
)
from kobeestudio.core.quick_labels import QuickLabelStore


SIMPLE_SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20">
  <title>Custom mark</title><path d="M 0 0 L 10 0 L 10 20 L 0 20 Z"/>
</svg>'''


class BundledSymbolTests(unittest.TestCase):
    def test_every_legacy_symbol_has_a_discovered_default_svg(self):
        symbols = discover_bundled_symbols()
        self.assertEqual(len(BUILTIN_ICONS), len([symbol for symbol in symbols if symbol.variant == "default"]))
        self.assertEqual(
            {icon.asset_id for icon in BUILTIN_ICONS},
            {symbol.asset_id for symbol in symbols if symbol.variant == "default"},
        )
        catalog = SymbolCatalog.discover()
        for symbol in symbols:
            with self.subTest(symbol=symbol.asset_id):
                polygons, size = catalog.render(symbol.asset_id, 1.6, symbol.variant)
                self.assertTrue(polygons)
                self.assertAlmostEqual(1.6, size.height)

    def test_linked_labels_resolve_stable_symbol_ids_and_variants(self):
        catalog = SymbolCatalog.discover()
        linked = {label.preset_id: label for label in catalog.labels}
        legacy = {label.preset_id: label for label in LABEL_PRESETS}
        self.assertEqual(set(legacy), set(linked))
        for preset_id, old in legacy.items():
            self.assertEqual(old.text, linked[preset_id].text)
            self.assertEqual(old.category, linked[preset_id].category)
            self.assertEqual(old.icon_id, linked[preset_id].symbol_id)
        self.assertEqual("builtin.ground", linked["gnd"].symbol_id)
        self.assertEqual("default", linked["gnd"].symbol_variant)
        self.assertEqual("", linked["boot"].symbol_id)

    def test_variant_filename_is_discovered_without_a_python_list_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            category = root / "electrical"
            category.mkdir()
            (category / "ground--rounded.svg").write_bytes(SIMPLE_SVG)
            symbols = discover_bundled_symbols(root)
            self.assertEqual(("builtin.ground", "rounded"), symbols[0].key)

    def test_symbol_references_keep_default_ids_backward_compatible(self):
        self.assertEqual("builtin.ground", format_symbol_reference("builtin.ground"))
        self.assertEqual(
            ("builtin.ground", "rounded"),
            parse_symbol_reference(format_symbol_reference("builtin.ground", "rounded")),
        )

    def test_flag_switches_to_each_bundled_svg_renderer(self):
        for icon in BUILTIN_ICONS:
            with self.subTest(icon=icon.asset_id):
                with patch.dict(os.environ, {"KOBEE_DEV_FEATURES": ""}, clear=False):
                    legacy = render_builtin_icon(icon.asset_id, 1.2)
                with patch.dict(os.environ, {"KOBEE_DEV_FEATURES": "svg_symbols"}, clear=False):
                    svg = render_builtin_icon(icon.asset_id, 1.2)
                self.assertAlmostEqual(legacy.size.height, svg.size.height, places=6)
                self.assertTrue(svg.polygons)


class SvgSafetyTests(unittest.TestCase):
    def test_active_and_external_svg_content_is_rejected(self):
        for unsafe in (
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/a.png"/></svg>',
            b'<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>',
        ):
            with self.subTest(svg=unsafe):
                with self.assertRaises(ValueError):
                    validate_svg_bytes(unsafe)

    def test_stroke_only_symbol_explains_that_outlines_are_required(self):
        stroked = b'<svg xmlns="http://www.w3.org/2000/svg"><path fill="none" stroke="black" d="M0 0 L1 1"/></svg>'
        with self.assertRaisesRegex(ValueError, "converted to filled paths"):
            validate_svg_bytes(stroked, require_renderable=True)

    def test_difference_cutouts_with_evenodd_are_converted_to_safe_regions(self):
        donut = b'''<svg xmlns="http://www.w3.org/2000/svg"><path fill-rule="evenodd" d="
            M0 0 L10 0 L10 10 L0 10 Z M2 2 L2 8 L8 8 L8 2 Z"/></svg>'''
        self.assertIsNotNone(validate_svg_bytes(donut, require_renderable=True))
        with self.assertRaisesRegex(ValueError, "evenodd"):
            validate_svg_bytes(donut.replace(b' fill-rule="evenodd"', b""), require_renderable=True)

    def test_inkscape_defs_and_rounded_rectangles_are_safe_geometry(self):
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg"><defs id="metadata"/>
            <rect x="1" y="2" width="10" height="8" rx="2"/></svg>'''
        self.assertIsNotNone(validate_svg_bytes(svg, require_renderable=True))


class CustomAssetStoreTests(unittest.TestCase):
    def test_global_symbol_upload_variants_persist_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.svg"
            source.write_bytes(SIMPLE_SVG)
            store = SvgAssetStore.global_store(root / "user-data")
            default = store.upload(source, "symbols", "My mark")
            rounded = store.upload(
                source,
                "symbols",
                "My mark",
                slug="my_mark",
                variant="rounded",
                asset_id=default.asset_id,
            )
            with self.assertRaisesRegex(ValueError, "already has"):
                store.upload(
                    source,
                    "symbols",
                    "My mark",
                    slug="my_mark",
                    variant="rounded",
                    asset_id=default.asset_id,
                )
            reopened = SvgAssetStore.global_store(root / "user-data")
            self.assertEqual({"default", "rounded"}, {item.variant for item in reopened.list("symbols")})
            catalog = SymbolCatalog.discover(custom_stores=(reopened,))
            self.assertEqual("rounded", catalog.resolve(default.asset_id, "rounded").variant)
            self.assertEqual(1, reopened.delete("symbols", rounded.asset_id, "rounded"))
            self.assertEqual(("default",), tuple(item.variant for item in reopened.list("symbols")))

    def test_project_uploads_are_separate_from_global_and_survive_store_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "board" / "design.kicad_pro"
            project.parent.mkdir()
            source = root / "graphic.svg"
            source.write_bytes(SIMPLE_SVG)
            project_store = SvgAssetStore.project_store(project)
            uploaded = project_store.upload(source, "graphics", "Logo")
            self.assertEqual("project", uploaded.scope)
            self.assertEqual(1, len(SvgAssetStore.project_store(project).list("graphics")))
            self.assertEqual((), SvgAssetStore.global_store(root / "global").list("graphics"))

    def test_context_catalog_only_exposes_uploads_when_the_flag_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "symbol.svg"
            source.write_bytes(SIMPLE_SVG)
            uploaded = SvgAssetStore.global_store(root).upload(source, "symbols", "Private")
            disabled = symbol_catalog_for_context(data_root=root, flags=FeatureFlags())
            with self.assertRaises(ValueError):
                disabled.resolve(uploaded.asset_id)
            enabled = symbol_catalog_for_context(
                data_root=root,
                flags=FeatureFlags(frozenset(("custom_assets", "svg_symbols"))),
            )
            self.assertEqual(uploaded.asset_id, enabled.resolve(uploaded.asset_id).asset_id)

    def test_custom_symbol_requires_both_asset_and_renderer_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "symbol.svg"
            source.write_bytes(SIMPLE_SVG)
            uploaded = SvgAssetStore.global_store(root).upload(source, "symbols", "Private")
            for flags in (
                FeatureFlags(frozenset(("custom_assets",))),
                FeatureFlags(frozenset(("svg_symbols",))),
            ):
                with self.assertRaises(ValueError):
                    symbol_catalog_for_context(data_root=root, flags=flags).resolve(uploaded.asset_id)

    def test_changed_uploaded_bytes_are_rejected_by_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "symbol.svg"
            source.write_bytes(SIMPLE_SVG)
            store = SvgAssetStore.global_store(root / "data")
            uploaded = store.upload(source, "symbols", "Private")
            uploaded.path.write_bytes(SIMPLE_SVG.replace(b"10 20", b"10 21"))
            self.assertEqual((), store.list("symbols"))

    def test_corrupt_entries_are_isolated_instead_of_breaking_the_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SvgAssetStore.global_store(Path(directory))
            broken = store.root / "symbols" / "broken"
            broken.mkdir(parents=True)
            (broken / "metadata.json").write_text("not json")
            (broken / "asset.svg").write_bytes(SIMPLE_SVG)
            self.assertEqual((), store.list("symbols"))


class QuickLabelStoreTests(unittest.TestCase):
    def test_user_quick_labels_are_individual_update_safe_files_and_join_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = QuickLabelStore.global_store(root)
            label = store.save("My AGND", "Power", "builtin.ground")
            self.assertTrue((root / "labels" / "v1" / "items" / (label.preset_id + ".json")).is_file())
            catalog = symbol_catalog_for_context(
                data_root=root,
                flags=FeatureFlags(frozenset(("custom_assets", "svg_symbols"))),
            )
            self.assertEqual("My AGND", {item.preset_id: item.text for item in catalog.labels}[label.preset_id])
            store.delete(label.preset_id)
            self.assertEqual((), store.list())

    def test_hidden_symbols_do_not_hide_linked_quick_labels(self):
        catalog = symbol_catalog_for_context(
            flags=FeatureFlags(), hidden_symbol_ids=("builtin.ground",), hidden_label_ids=("boot",)
        )
        self.assertNotIn("builtin.ground", {item.asset_id for item in catalog.symbols})
        self.assertIn("gnd", {item.preset_id for item in catalog.labels})
        self.assertNotIn("boot", {item.preset_id for item in catalog.labels})


if __name__ == "__main__":
    unittest.main()

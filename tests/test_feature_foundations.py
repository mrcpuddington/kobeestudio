"""Checks for flags, measurement preferences, and persistent profiles."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kobeestudio.core.app_preferences import AppPreferences, AppPreferencesStore
from kobeestudio.core.data_paths import project_data_root, user_data_root
from kobeestudio.core.feature_flags import FeatureFlags, SVG_SYMBOLS
from kobeestudio.core.library_archive import export_library, import_library, reset_library, restore_library
from kobeestudio.core.measurement_units import (
    MeasurementUnit,
    format_measurement,
    from_millimetres,
    to_millimetres,
)
from kobeestudio.core.settings_profiles import SettingsProfileStore, profile_module_for_mode


class FeatureFlagTests(unittest.TestCase):
    def test_features_are_off_by_default_and_parse_explicit_environment(self):
        self.assertFalse(FeatureFlags.from_environment({}).enabled(SVG_SYMBOLS))
        flags = FeatureFlags.from_environment({"KOBEE_DEV_FEATURES": "svg_symbols, alternative_units"})
        self.assertTrue(flags.enabled(SVG_SYMBOLS))

    def test_unknown_flags_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            FeatureFlags.from_environment({"KOBEE_DEV_FEATURES": "typo"})


class DataPathTests(unittest.TestCase):
    def test_platform_data_roots_are_outside_the_install(self):
        self.assertEqual(
            Path("/Users/test/Library/Application Support/Kobee Studio"),
            user_data_root("darwin", {}, Path("/Users/test")),
        )
        self.assertEqual(
            Path("/projects/board/.kobeestudio"),
            project_data_root("/projects/board/design.kicad_pro"),
        )
        self.assertEqual(
            Path("/projects/board/.kobeestudio"),
            project_data_root("/projects/board/design.kicad_pcb"),
        )


class AppPreferencesTests(unittest.TestCase):
    def test_preferences_persist_and_corrupt_files_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AppPreferencesStore(Path(directory))
            store.save(AppPreferences(appearance="dark", measurement_unit="mil"))
            reopened = AppPreferencesStore(Path(directory)).load()
            self.assertEqual("dark", reopened.appearance)
            self.assertIs(MeasurementUnit.MILS, reopened.measurement_unit)
            store.path.write_text("not json", encoding="utf-8")
            self.assertEqual(AppPreferences(), store.load())

    def test_hidden_bundled_library_entries_persist_without_changing_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AppPreferencesStore(Path(directory))
            store.save(AppPreferences(hidden_symbol_ids=("builtin.ground",), hidden_label_ids=("gnd",)))
            reopened = store.load()
            self.assertEqual(("builtin.ground",), reopened.hidden_symbol_ids)
            self.assertEqual(("gnd",), reopened.hidden_label_ids)


class MeasurementUnitTests(unittest.TestCase):
    def test_mils_round_trip_without_changing_internal_millimetres(self):
        self.assertAlmostEqual(100.0, from_millimetres(2.54, MeasurementUnit.MILS))
        self.assertAlmostEqual(2.54, to_millimetres(100.0, "mils"))
        self.assertEqual("100.0 mil", format_measurement(2.54, "mil", decimals=1))

    def test_non_finite_and_unknown_values_are_rejected(self):
        with self.assertRaises(ValueError):
            to_millimetres(float("nan"), "mm")
        with self.assertRaises(ValueError):
            MeasurementUnit.parse("inch")


class SettingsProfileStoreTests(unittest.TestCase):
    def test_modes_map_to_independent_profile_modules(self):
        self.assertEqual("labels", profile_module_for_mode("Label"))
        self.assertEqual("component_arrays", profile_module_for_mode("Component Array"))
        with self.assertRaises(ValueError):
            profile_module_for_mode("unknown")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "do not match"):
                SettingsProfileStore(Path(directory)).save(
                    "labels",
                    "Wrong module",
                    {"StudioModeChoice": "Component Array"},
                )

    def test_module_profiles_persist_recall_update_and_default(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsProfileStore(Path(directory))
            profile = store.save(
                "labels",
                "Fine silk",
                {"height_mm": 1.2, "measurement_unit": "mil"},
                make_default=True,
            )
            reopened = SettingsProfileStore(Path(directory))
            self.assertEqual(profile.profile_id, reopened.default_id("labels"))
            self.assertEqual(1.2, reopened.load("labels").settings["height_mm"])

            updated = reopened.save(
                "labels",
                "Fine silk",
                {"height_mm": 1.5},
                profile_id=profile.profile_id,
            )
            self.assertEqual(profile.created_at, updated.created_at)
            self.assertEqual(1.5, reopened.load("labels", profile.profile_id).settings["height_mm"])
            self.assertEqual((), reopened.list("pin_headers"))

            reopened.delete("labels", profile.profile_id)
            self.assertIsNone(reopened.default_id("labels"))
            with self.assertRaises(LookupError):
                reopened.load("labels", profile.profile_id)

    def test_profile_files_are_versioned_json_and_names_are_unique_per_module(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsProfileStore(Path(directory))
            profile = store.save("labels", "Default", {"padding": 0.3})
            path = Path(directory) / "profiles" / "v1" / "labels" / "items" / (profile.profile_id + ".json")
            self.assertEqual(1, json.loads(path.read_text())["schema_version"])
            with self.assertRaisesRegex(ValueError, "already exists"):
                store.save("labels", "default", {})
            store.save("pin_headers", "Default", {})

    def test_corrupt_or_misfiled_profiles_do_not_break_other_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsProfileStore(Path(directory))
            valid = store.save("labels", "Valid", {"HeightCtrl": 1.2})
            item_root = Path(directory) / "profiles" / "v1" / "labels" / "items"
            (item_root / "broken.json").write_text("not json", encoding="utf-8")
            payload = json.loads((item_root / (valid.profile_id + ".json")).read_text())
            payload["module"] = "pin_headers"
            (item_root / "00000000-0000-0000-0000-000000000000.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            self.assertEqual((valid,), store.list("labels"))


class PortableLibraryTests(unittest.TestCase):
    def test_export_then_import_merges_only_allowed_library_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target, archive = root / "source", root / "target", root / "library.zip"
            (source / "labels" / "v1" / "items").mkdir(parents=True)
            (source / "labels" / "v1" / "items" / "label.json").write_text("{}", encoding="utf-8")
            (source / "unrelated.txt").write_text("not portable", encoding="utf-8")
            self.assertEqual(1, export_library(source, archive))
            self.assertEqual(1, import_library(archive, target))
            self.assertTrue((target / "labels" / "v1" / "items" / "label.json").is_file())
            self.assertFalse((target / "unrelated.txt").exists())

    def test_restore_replaces_existing_portable_library_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target, archive = root / "source", root / "target", root / "library.zip"
            (source / "preferences.json").parent.mkdir(parents=True)
            (source / "preferences.json").write_text('{"appearance": "dark"}', encoding="utf-8")
            (target / "preferences.json").parent.mkdir(parents=True)
            (target / "preferences.json").write_text('{"appearance": "light"}', encoding="utf-8")
            self.assertEqual(1, export_library(source, archive))
            self.assertEqual(1, restore_library(archive, target))
            self.assertIn("dark", (target / "preferences.json").read_text(encoding="utf-8"))

    def test_reset_removes_only_mutable_library_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets" / "v1").mkdir(parents=True)
            (root / "labels" / "v1").mkdir(parents=True)
            (root / "preferences.json").write_text("{}", encoding="utf-8")
            (root / "unrelated.txt").write_text("keep", encoding="utf-8")
            reset_library(root)
            self.assertFalse((root / "assets").exists())
            self.assertFalse((root / "labels").exists())
            self.assertFalse((root / "preferences.json").exists())
            self.assertTrue((root / "unrelated.txt").is_file())


if __name__ == "__main__":
    unittest.main()

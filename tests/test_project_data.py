import tempfile
import unittest
from pathlib import Path
import json

from kobeestudio.core.project_data import (
    FieldDefinition,
    ProjectData,
    ProjectDataCatalog,
    ProjectDataCatalogStore,
    ProjectDataConflictError,
    ProjectDataRecoveryError,
    ProjectDataStore,
    adopt_kicad_variables,
    fields_for,
    generated_variables,
    merge_kicad_variables,
)


class ProjectDataTests(unittest.TestCase):
    @staticmethod
    def revision_values(revision, **extra):
        values = {
            "default_revision": revision,
            "default_issue_date": "2026-08-15",
            "default_status": "Draft",
        }
        values.update(extra)
        return values

    def test_round_trip_checkpoint_restore_and_delete(self):
        project = ProjectData.empty().with_checkpoint(self.revision_values("A"))
        first = project.active_revision()
        self.assertEqual(first.values["default_revision"], "A")
        project = project.with_checkpoint(self.revision_values("B"))
        restored = project.restore_to_draft(first.revision_id)
        self.assertEqual(restored.revision_draft["default_revision"], "A")
        self.assertEqual(len(restored.revisions), 2)
        deleted = restored.delete_revision(project.active_revision_id)
        self.assertEqual(deleted.active_revision_id, first.revision_id)
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectDataStore(Path(directory) / "example.kicad_pro")
            store.save(deleted)
            self.assertEqual(store.load().active_revision_id, first.revision_id)
            self.assertTrue((Path(directory) / "kobee-project.json").is_file())

    def test_reusable_fields_and_hidden_defaults(self):
        reusable = FieldDefinition(
            "custom_assembly", "Assembly house", "ASSEMBLY_HOUSE", "project", "text"
        )
        catalog = ProjectDataCatalog(reusable_fields=(reusable,), hidden_default_field_ids=("default_hardware_version",))
        project = ProjectData.empty()
        self.assertIn(reusable, fields_for("project", project, catalog))
        self.assertNotIn("default_hardware_version", [item.field_id for item in fields_for("revision", project, catalog)])
        excluded = ProjectData(excluded_reusable_field_ids=(reusable.field_id,))
        self.assertNotIn(reusable, fields_for("project", excluded, catalog))

    def test_generated_variables_keep_hidden_values_and_external_merge(self):
        catalog = ProjectDataCatalog(
            global_values={"default_global_company_name": "Kobee"},
            hidden_default_field_ids=("default_hardware_version",),
        )
        project = ProjectData(
            project_values={"default_board_name": "Main board"},
            revision_draft={"default_revision": "A", "default_hardware_version": "1.2"},
        ).with_checkpoint(self.revision_values("A", default_hardware_version="1.2"))
        variables = generated_variables(project, catalog)
        self.assertEqual(variables["KOBEE_GLOBAL_COMPANY_NAME"], "Kobee")
        self.assertEqual(variables["KOBEE_PROJECT_BOARD_NAME"], "Main board")
        self.assertEqual(variables["KOBEE_HARDWARE_VERSION"], "1.2")
        merged, managed = merge_kicad_variables(
            {"EXTERNAL": "keep", "KOBEE_OLD": "remove"}, variables, ("KOBEE_OLD",)
        )
        self.assertEqual(merged["EXTERNAL"], "keep")
        self.assertNotIn("KOBEE_OLD", merged)
        self.assertIn("KOBEE_REVISION", managed)

    def test_catalog_round_trip(self):
        catalog = ProjectDataCatalog(global_fields=(FieldDefinition("custom_site", "Website", "WEBSITE", "global", "url"),))
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectDataCatalogStore(Path(directory))
            store.save(catalog)
            self.assertEqual(store.load().global_fields[0].key, "WEBSITE")

    def test_catalog_refuses_to_replace_an_unreadable_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectDataCatalogStore(Path(directory))
            store.path.parent.mkdir(parents=True)
            store.path.write_text('{"schema_version": 999}', encoding="utf-8")
            with self.assertRaises(ProjectDataRecoveryError):
                store.save(ProjectDataCatalog.empty())

    def test_adopts_recognised_kobee_variables_without_touching_unknown_names(self):
        project, catalog = adopt_kicad_variables({
            "KOBEE_PROJECT_BOARD_NAME": "Control board",
            "KOBEE_REVISION": "C",
            "KOBEE_GLOBAL_COMPANY_NAME": "Kobee Studio",
            "KOBEE_NOT_A_MANAGED_VALUE": "leave alone",
        }, ProjectDataCatalog.empty())
        self.assertEqual(project.project_values["default_board_name"], "Control board")
        self.assertEqual(project.revision_draft["default_revision"], "C")
        self.assertEqual(catalog.global_values["default_global_company_name"], "Kobee Studio")
        self.assertNotIn("KOBEE_NOT_A_MANAGED_VALUE", project.managed_variable_names)

    def test_reusable_typed_fields_export_in_their_scope(self):
        project_field = FieldDefinition("custom_customer", "Customer build", "CUSTOMER_BUILD", "project", "checkbox", default_value=False)
        revision_field = FieldDefinition("custom_release", "Release URL", "RELEASE_URL", "revision", "url")
        catalog = ProjectDataCatalog(reusable_fields=(project_field, revision_field))
        project = ProjectData(
            project_values={"custom_customer": True},
            revision_draft={"custom_release": "https://example.test/release"},
        ).with_checkpoint(self.revision_values("A", custom_release="https://example.test/release"))
        variables = generated_variables(project, catalog)
        self.assertEqual(variables["KOBEE_PROJECT_CUSTOMER_BUILD"], "Yes")
        self.assertEqual(variables["KOBEE_REVISION_RELEASE_URL"], "https://example.test/release")

    def test_checkpoint_requires_release_identity_and_unique_revision(self):
        with self.assertRaisesRegex(ValueError, "Revision is required"):
            ProjectData.empty().with_checkpoint({})
        project = ProjectData.empty().with_checkpoint(self.revision_values("A"))
        with self.assertRaisesRegex(ValueError, "already exists"):
            project.with_checkpoint(self.revision_values("A"))

    def test_store_detects_external_change_and_backs_up_corrupt_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectDataStore(Path(directory) / "example.kicad_pro")
            fingerprint = store.save(ProjectData.empty())
            store.path.write_text(json.dumps(ProjectData(managed_variable_names=("KOBEE_REVISION",)).to_dict()), encoding="utf-8")
            with self.assertRaises(ProjectDataConflictError):
                store.save(ProjectData.empty(), expected_fingerprint=fingerprint)
            store.path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
            with self.assertRaises(ProjectDataRecoveryError):
                store.load()
            backup = store.backup_corrupt_record()
            self.assertTrue(backup.is_file())
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["schema_version"], 999)
            with self.assertRaises(ProjectDataRecoveryError):
                store.save(ProjectData.empty(), expected_fingerprint=store.fingerprint())
            store.remove_corrupt_record_after_backup(backup)
            store.save(ProjectData.empty())
            self.assertEqual(store.load(), ProjectData.empty())

    def test_pending_sync_state_survives_a_restart_until_marked_synced(self):
        project = ProjectData.empty().with_checkpoint(self.revision_values("A"))
        project = project.with_managed_variable_names(("KOBEE_REVISION",)).with_sync_state(pending=True)
        self.assertTrue(project.sync_pending)
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectDataStore(Path(directory) / "example.kicad_pro")
            fingerprint = store.save(project)
            reopened = store.load()
            self.assertTrue(reopened.sync_pending)
            synced = reopened.mark_synced()
            store.save(synced, expected_fingerprint=fingerprint)
            self.assertFalse(store.load().sync_pending)
            self.assertTrue(store.load().last_synced_at)

    def test_record_can_be_read_for_explicit_import_after_a_project_move(self):
        with tempfile.TemporaryDirectory() as directory:
            original = ProjectDataStore(Path(directory) / "old" / "example.kicad_pro")
            original.save(ProjectData.empty())
            imported = ProjectDataStore.read_record(original.path)
            destination = ProjectDataStore(Path(directory) / "new" / "example.kicad_pro")
            destination.save(imported)
            self.assertEqual(destination.load(), ProjectData.empty())


if __name__ == "__main__":
    unittest.main()

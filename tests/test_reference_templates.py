from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kobeestudio.core.library_archive import export_library, import_library
from kobeestudio.core.reference_templates import (
    ReferenceTemplateStore,
    resolve_reference_template,
    template_placeholders,
)


class ReferenceTemplateTests(unittest.TestCase):
    def test_numbered_repeated_and_plural_placeholders(self):
        template = "$designator2 / $designator1\nAgain: $designator2\n$designators"
        self.assertEqual(
            "C10 / R2\nAgain: C10\nR2\nC10\nU3",
            resolve_reference_template(template, ("R2", "C10", "U3")),
        )
        self.assertEqual(
            ("$designator2", "$designator1", "$designators"),
            template_placeholders(template),
        )

    def test_first_alias_case_insensitive_and_actionable_errors(self):
        self.assertEqual("R7 + R7", resolve_reference_template("$Designator + $designator1", ("R7",)))
        with self.assertRaisesRegex(ValueError, "only 1 footprint"):
            resolve_reference_template("$designator2", ("R1",))
        with self.assertRaisesRegex(ValueError, "Unsupported placeholder"):
            resolve_reference_template("$value1", ("R1",))

    def test_global_store_crud_and_archive_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            destination = Path(temporary) / "destination"
            archive = Path(temporary) / "library.zip"
            store = ReferenceTemplateStore.global_store(root)
            saved = store.save(
                "Power pair",
                "$designator1\n$designator2",
                {"FontComboBox": "FreddySpark-Regular", "HeightCtrl": 1.2},
            )
            self.assertEqual((saved,), store.list())
            updated = store.save("Power pair", "$designators", {"HeightCtrl": 1.4}, saved.template_id)
            self.assertEqual("$designators", updated.template_text)
            self.assertGreater(export_library(root, archive), 0)
            self.assertGreater(import_library(archive, destination), 0)
            restored = ReferenceTemplateStore.global_store(destination).list()
            self.assertEqual("Power pair", restored[0].name)
            self.assertEqual("$designators", restored[0].template_text)
            store.delete(saved.template_id)
            self.assertEqual((), store.list())


if __name__ == "__main__":
    unittest.main()

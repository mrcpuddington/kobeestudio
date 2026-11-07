from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kobeestudio.core.library_archive import export_library, import_library
from kobeestudio.core.variable_templates import (
    VariableTemplateStore,
    expand_variable_template,
    multipart_sections,
    validate_variable_template,
    variable_names,
)


class VariableTemplateTests(unittest.TestCase):
    def test_known_values_expand_for_preview_and_unknown_values_remain_native(self):
        template = "${BOARD_NAME}\nRev ${REVISION} / ${MISSING}\n${REVISION}"
        self.assertEqual(("BOARD_NAME", "REVISION", "MISSING"), variable_names(template))
        self.assertEqual(
            "Controller\nRev B / ${MISSING}\nB",
            expand_variable_template(template, {"BOARD_NAME": "Controller", "REVISION": "B"}),
        )
        self.assertEqual(template, validate_variable_template(template))
        self.assertEqual("  ${REVISION}\n", validate_variable_template("  ${REVISION}\n"))

    def test_invalid_or_empty_expressions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "KiCad syntax"):
            validate_variable_template("${REVISION")
        with self.assertRaisesRegex(ValueError, "KiCad syntax"):
            validate_variable_template("${}")
        with self.assertRaisesRegex(ValueError, "leading or trailing"):
            validate_variable_template("${ REVISION }")
        with self.assertRaisesRegex(ValueError, "1 to 8000"):
            validate_variable_template("")

    def test_multipart_sections_require_strict_bracketed_sections(self):
        template = "[${PROJECT_NUMBER}] [Rev ${KOBEE_REVISION}] [${KOBEE_HARDWARE_VERSION}]"
        self.assertEqual(
            ("${PROJECT_NUMBER}", "Rev ${KOBEE_REVISION}", "${KOBEE_HARDWARE_VERSION}"),
            multipart_sections(template),
        )
        self.assertEqual(("", ""), multipart_sections("[] []"))
        with self.assertRaisesRegex(ValueError, "bracketed sections"):
            multipart_sections("${PROJECT_NUMBER} [Rev ${KOBEE_REVISION}]")

    def test_global_store_crud_and_archive_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            destination = Path(temporary) / "destination"
            archive = Path(temporary) / "library.zip"
            store = VariableTemplateStore.global_store(root)
            saved = store.save(
                "Board identity",
                "${BOARD_NAME}\n${PCB_PART_NUMBER}",
                {"HeightCtrl": 1.2, "NativeStrokeWidthCtrl": 0.18},
            )
            self.assertEqual((saved,), store.list())
            updated = store.save(
                "Board identity", "${REVISION}", {"HeightCtrl": 1.4}, saved.template_id
            )
            self.assertEqual("${REVISION}", updated.template_text)
            self.assertGreater(export_library(root, archive), 0)
            self.assertGreater(import_library(archive, destination), 0)
            restored = VariableTemplateStore.global_store(destination).list()
            self.assertEqual("Board identity", restored[0].name)
            self.assertEqual("${REVISION}", restored[0].template_text)
            store.delete(saved.template_id)
            self.assertEqual((), store.list())


if __name__ == "__main__":
    unittest.main()

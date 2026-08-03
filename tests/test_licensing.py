"""Regression checks for project-level licensing and attribution files."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LicensingTests(unittest.TestCase):
    def test_kibuzzard_mit_notice_is_preserved(self):
        notice = (ROOT / "kobeestudio/vendor/licenses/kiBuzzard-LICENSE").read_text()
        self.assertIn("MIT License", notice)
        self.assertIn("Copyright (c) 2020 Greg Davill <greg.davill@gmail.com>", notice)
        self.assertIn("The above copyright notice and this permission notice", notice)

    def test_pcm_metadata_keeps_the_kicad_accepted_license_value(self):
        metadata = json.loads((ROOT / "pcm/metadata_template.json").read_text())
        self.assertEqual("GPL-2.0", metadata["license"])

    def test_third_party_notice_explains_the_kibuzzard_relationship(self):
        notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
        for required_text in (
            "Kobee Studio originated as a fork of",
            "KiBuzzard is licensed under the MIT",
            "Greg Davill",
            "GPL-2.0-only",
        ):
            self.assertIn(required_text, notice)


if __name__ == "__main__":
    unittest.main()

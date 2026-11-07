import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pcm import build


class PackageBuildTests(unittest.TestCase):
    def test_epoch_dated_resources_produce_a_complete_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "plugin"
            staging.mkdir()
            resource = staging / "legacy-asset.svg"
            resource.write_text("<svg/>")
            os.utime(resource, (0, 0))
            with patch.object(build, "BUILD", root), patch.object(build, "STAGING", staging):
                archive = build._build_archive("1.0.0")
            with zipfile.ZipFile(archive) as package:
                self.assertIsNone(package.testzip())
                self.assertEqual(b"<svg/>", package.read("legacy-asset.svg"))
                self.assertEqual(1980, package.getinfo("legacy-asset.svg").date_time[0])

"""Protect published PCM history and the identity of release artifacts."""

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.prepare_kicad_submission import IDENTIFIER, main, prepare_metadata, verify_public_archive


class ReleasePreparationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.archive = self.root / "Kobee-Studio-1.5.20-pcm.zip"
        self.metadata = {
            "$schema": "https://go.kicad.org/pcm/schemas/v2",
            "identifier": IDENTIFIER, "name": "Kobee Studio", "type": "plugin",
            "versions": [{"version": "1.5.20", "status": "testing", "runtime": "ipc", "kicad_version": "10.0"}],
        }
        self.upstream = copy.deepcopy(self.metadata)
        self.upstream["versions"] = [{"version": "1.4.1", "status": "stable", "download_sha256": "old", "download_size": 10}]
        self.write_archive()

    def tearDown(self):
        self.directory.cleanup()

    def write_archive(self, extra=None):
        with zipfile.ZipFile(self.archive, "w") as package:
            package.writestr("metadata.json", json.dumps(self.metadata))
            package.writestr("plugins/" + IDENTIFIER + "/plugin.json", json.dumps({"identifier": IDENTIFIER}))
            if extra:
                package.writestr(extra, "unexpected")

    def test_new_release_preserves_old_entry_and_derives_exact_sizes_and_checksum(self):
        before = copy.deepcopy(self.upstream)
        merged, version = prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")
        self.assertEqual(before, self.upstream)
        self.assertEqual(before["versions"], merged["versions"][1:])
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), version["download_sha256"])
        self.assertEqual(self.archive.stat().st_size, version["download_size"])
        with zipfile.ZipFile(self.archive) as package:
            self.assertEqual(sum(info.file_size for info in package.infolist()), version["install_size"])
        self.assertIn("/v1.5.20-beta.1/", version["download_url"])

    def test_published_version_cannot_be_replaced_by_different_bytes(self):
        merged, _ = prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")
        self.write_archive("plugins/" + IDENTIFIER + "/new.py")
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare_metadata(self.archive, merged, "v1.5.20-beta.1")

    def test_identical_rerun_preserves_the_existing_version(self):
        merged, _ = prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")
        again, _ = prepare_metadata(self.archive, merged, "v1.5.20-beta.1")
        self.assertEqual(merged, again)

    def test_development_build_and_wrong_channel_tag_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Testing release tag"):
            prepare_metadata(self.archive, self.upstream, "v1.5.20")
        self.metadata["versions"][0]["status"] = "development"
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "testing or stable"):
            prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")

    def test_stable_build_requires_a_matching_stable_tag(self):
        self.metadata["versions"][0]["status"] = "stable"
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "Stable release tag"):
            prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")
        _, version = prepare_metadata(self.archive, self.upstream, "v1.5.20")
        self.assertIn("/v1.5.20/", version["download_url"])

    def test_unsafe_or_unexpected_archive_paths_are_rejected(self):
        for path in ("../secret", "/absolute", "plugins\\escape", "README.md"):
            with self.subTest(path=path):
                self.write_archive(path)
                with self.assertRaises(ValueError):
                    prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")

    def test_other_package_identity_and_embedded_download_fields_are_rejected(self):
        other = copy.deepcopy(self.upstream)
        other["identifier"] = "com.example.other"
        with self.assertRaisesRegex(ValueError, "identifiers"):
            prepare_metadata(self.archive, other, "v1.5.20-beta.1")
        self.metadata["versions"][0]["download_url"] = "https://example.org/file.zip"
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "Download fields"):
            prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")

    def test_public_archive_must_match_the_exact_bytes(self):
        _, version = prepare_metadata(self.archive, self.upstream, "v1.5.20-beta.1")
        with patch("tools.prepare_kicad_submission.read_public", return_value=self.archive.read_bytes()):
            verify_public_archive(version)
        with patch("tools.prepare_kicad_submission.read_public", return_value=b"different"):
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_public_archive(version)

    def test_failed_public_verification_leaves_a_reviewable_unverified_draft(self):
        upstream = self.root / "upstream.json"
        upstream.write_text(json.dumps(self.upstream))
        output = self.root / "submission"
        with patch("tools.prepare_kicad_submission.read_public", side_effect=OSError("not published")):
            result = main(["--archive", str(self.archive), "--release-tag", "v1.5.20-beta.1",
                           "--upstream-metadata", str(upstream), "--output", str(output), "--verify-download"])
        self.assertEqual(1, result)
        self.assertFalse(json.loads((output / "readiness.json").read_text())["public_archive_verified"])
        self.assertTrue((output / "packages" / IDENTIFIER / "metadata.json").is_file())

    def test_generated_patch_applies_to_the_existing_metadata(self):
        upstream = self.root / "upstream.json"
        upstream.write_text(json.dumps(self.upstream, indent=2) + "\n")
        output = self.root / "submission"
        self.assertEqual(0, main(["--archive", str(self.archive), "--release-tag", "v1.5.20-beta.1",
                                  "--upstream-metadata", str(upstream), "--output", str(output)]))
        checkout = self.root / "checkout"
        target = checkout / "packages" / IDENTIFIER / "metadata.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(upstream.read_bytes())
        subprocess.run(["git", "apply", str(output / "metadata.patch")], cwd=checkout, check=True, capture_output=True)
        self.assertEqual((output / "packages" / IDENTIFIER / "metadata.json").read_bytes(), target.read_bytes())

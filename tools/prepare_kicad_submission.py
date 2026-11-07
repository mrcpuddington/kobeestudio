"""Prepare an update to KiCad's official metadata repository without publishing.

Read the exact release ZIP, retain upstream version history, and optionally
verify that the public download serves those same bytes. Uses only stdlib.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen


IDENTIFIER = "com.github.mrcpuddington.kobeestudio"
UPSTREAM_URL = (
    "https://gitlab.com/kicad/addons/metadata/-/raw/main/packages/"
    + IDENTIFIER + "/metadata.json"
)


def read_public(url):
    request = Request(url, headers={"User-Agent": "Kobee-Studio-release-preparation"})
    with urlopen(request, timeout=45) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("Public release resources must remain on HTTPS")
        return response.read()


def prepare_metadata(archive, upstream, release_tag):
    """Derive all new artifact fields from the ZIP and preserve prior entries."""
    archive = Path(archive)
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Archive contains duplicate paths")
        for info in package.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise ValueError("Unsafe archive path: " + info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Archive must not contain symlinks")
            if not info.is_dir() and not (
                info.filename in ("metadata.json", "resources/icon.png")
                or info.filename.startswith("plugins/" + IDENTIFIER + "/")
            ):
                raise ValueError("Unexpected package file: " + info.filename)
        if package.testzip() is not None:
            raise ValueError("Archive failed its ZIP integrity check")
        packaged = json.loads(package.read("metadata.json"))
        plugin = json.loads(package.read("plugins/" + IDENTIFIER + "/plugin.json"))
        install_size = sum(info.file_size for info in package.infolist() if not info.is_dir())
    if packaged.get("identifier") != IDENTIFIER or upstream.get("identifier") != IDENTIFIER:
        raise ValueError("Package and upstream identifiers must both be " + IDENTIFIER)
    if plugin.get("identifier") != IDENTIFIER or packaged.get("type") != "plugin":
        raise ValueError("IPC plugin identity does not match package metadata")
    versions = packaged.get("versions", [])
    if len(versions) != 1:
        raise ValueError("The archive must contain exactly one version")
    version = copy.deepcopy(versions[0])
    number = version.get("version", "")
    if not re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", number):
        raise ValueError("PCM version must be numeric major.minor.patch")
    if version.get("status") not in ("testing", "stable"):
        raise ValueError("Build a testing or stable package before preparing a submission")
    if version.get("runtime") != "ipc" or version.get("kicad_version") != "10.0":
        raise ValueError("This release must declare the KiCad 10 IPC runtime")
    if any(key.startswith("download_") for key in version):
        raise ValueError("Download fields must not appear inside the archive")
    if archive.name != "Kobee-Studio-{}-pcm.zip".format(number):
        raise ValueError("Archive filename does not match its embedded version")
    expected_tag = "v" + number
    if version["status"] == "stable":
        if release_tag != expected_tag:
            raise ValueError("Stable release tag must be " + expected_tag)
    elif not re.fullmatch(re.escape(expected_tag) + r"-beta\.[1-9][0-9]*", release_tag):
        raise ValueError("Testing release tag must be " + expected_tag + "-beta.N")
    version.update(
        download_url="https://github.com/mrcpuddington/kobeestudio/releases/download/{}/{}".format(
            quote(release_tag, safe=""), archive.name),
        download_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        download_size=archive.stat().st_size,
        install_size=install_size,
    )
    previous = copy.deepcopy(upstream.get("versions", []))
    numbers = [item["version"] for item in previous]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Upstream metadata contains duplicate versions")
    if number in numbers:
        existing = previous[numbers.index(number)]
        if existing != version:
            raise ValueError("Version already exists upstream; do not replace a published artifact")
    else:
        previous.insert(0, version)
    # Keep extra upstream package fields while updating the current description.
    merged = copy.deepcopy(upstream)
    merged.update({key: value for key, value in packaged.items() if key != "versions"})
    merged["versions"] = previous
    return merged, version


def verify_public_archive(version):
    data = read_public(version["download_url"])
    if len(data) != version["download_size"] or hashlib.sha256(data).hexdigest() != version["download_sha256"]:
        raise ValueError("Public download differs from the prepared ZIP; regenerate from the released artifact")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--upstream-metadata", type=Path,
                        help="Saved upstream metadata for offline preparation; otherwise fetch current main")
    parser.add_argument("--output", type=Path, default=Path("pcm/build/official-submission"))
    parser.add_argument("--verify-download", action="store_true",
                        help="Require the public release URL to serve the exact archive bytes")
    args = parser.parse_args(argv)
    try:
        upstream_bytes = (args.upstream_metadata.read_bytes() if args.upstream_metadata else read_public(UPSTREAM_URL))
        upstream = json.loads(upstream_bytes)
        metadata, version = prepare_metadata(args.archive, upstream, args.release_tag)
        # Create a reviewable local draft before checking a not-yet-published URL.
        destination = args.output / "packages" / IDENTIFIER
        destination.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
        (destination / "metadata.json").write_text(rendered, encoding="utf-8")
        (args.output / "upstream-metadata.json").write_bytes(upstream_bytes)
        relative = "packages/" + IDENTIFIER + "/metadata.json"
        patch_text = "".join(difflib.unified_diff(
            upstream_bytes.decode("utf-8").splitlines(keepends=True), rendered.splitlines(keepends=True),
            fromfile="a/" + relative, tofile="b/" + relative))
        (args.output / "metadata.patch").write_text(patch_text, encoding="utf-8")
        readiness = {
            "version": version["version"], "status": version["status"],
            "release_tag": args.release_tag, "artifact": version,
            "upstream_url": UPSTREAM_URL,
            "upstream_metadata_sha256": hashlib.sha256(upstream_bytes).hexdigest(),
            "public_archive_verified": False,
            "next_steps": [
                "Publish the intended archive from the tested source revision.",
                "Regenerate from the exact released ZIP with --verify-download and fresh upstream metadata.",
                "Run the official validator and test its temporary PCM repository before submitting the merge request.",
                "Complete release acceptance before promoting to stable; preserve all published version entries.",
            ],
        }
        state_path = args.output / "readiness.json"
        state_path.write_text(json.dumps(readiness, indent=2) + "\n", encoding="utf-8")
        body = (
            "# Update Kobee Studio to {number} ({status})\n\n"
            "Updates `packages/{identifier}/metadata.json` and retains all existing version entries.\n\n"
            "This release adds font management, SVG/PNG artwork workflows, variable labels, placement anchors, "
            "text formatting and UI/lifecycle hardening. It also reduces polygon count for complex inverted artwork "
            "and guards the affected older KiCad transaction path.\n\n"
            "- Runtime: KiCad 10 IPC.\n"
            "- Archive: {url}\n"
            "- SHA-256: `{sha}`\n"
            "- Download size: {size} bytes; installed size: {installed} bytes.\n\n"
            "## Before submitting\n\n"
            "- [ ] Public archive downloaded and checksum/size matched (`--verify-download`).\n"
            "- [ ] Official metadata validator and GitLab CI passed.\n"
            "- [ ] Installed and updated through GitLab's temporary PCM repository.\n"
            "- [ ] Intended release channel and outstanding platform acceptance reviewed.\n\n"
            "Draft generated locally; unchecked items are not claimed as complete.\n"
        ).format(number=version["version"], status=version["status"], identifier=IDENTIFIER,
                 url=version["download_url"], sha=version["download_sha256"],
                 size=version["download_size"], installed=version["install_size"])
        (args.output / "merge-request.md").write_text(body, encoding="utf-8")
        if args.verify_download:
            verify_public_archive(version)
            readiness["public_archive_verified"] = True
            state_path.write_text(json.dumps(readiness, indent=2) + "\n", encoding="utf-8")
        print("Prepared " + str(destination / "metadata.json"))
        print("Public archive verified: " + str(readiness["public_archive_verified"]))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print("Release preparation failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

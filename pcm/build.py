"""Build a KiCad Plugin and Content Manager archive for the IPC runtime."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = HERE / "build"
STAGING = BUILD / "plugin"
PLUGINS = STAGING / "plugins"
PLUGIN_DIR = PLUGINS / "com.github.mrcpuddington.kobeestudio"
METADATA_TEMPLATE = HERE / "metadata_template.json"


def _copy_plugin() -> None:
    PLUGIN_DIR.mkdir(parents=True)
    for filename in (
        "plugin.json",
        "requirements.txt",
        "kobeestudio_ipc.py",
        "kobee-toolbar-24.png",
        "kobee-toolbar-48.png",
    ):
        shutil.copy2(ROOT / "ipc_plugin" / filename, PLUGIN_DIR / filename)
    shutil.copytree(
        ROOT / "kobeestudio",
        PLUGIN_DIR / "kobeestudio",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
    )
    for filename in ("LICENCE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / filename, PLUGIN_DIR / filename)


def _write_metadata() -> tuple[dict, str]:
    metadata = json.loads(METADATA_TEMPLATE.read_text(encoding="utf-8"))
    (STAGING / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    version = metadata["versions"][0]["version"]
    return metadata, version


def _build_archive(version: str) -> Path:
    archive_base = BUILD / "Kobee-Studio-{}-pcm".format(version)
    shutil.make_archive(str(archive_base), "zip", STAGING)
    return Path(str(archive_base) + ".zip")


def _write_repository_metadata(metadata: dict, version: str, archive: Path) -> None:
    package_name = archive.name
    metadata["versions"][0].update(
        {
            "install_size": sum(
                item.stat().st_size for item in STAGING.rglob("*") if item.is_file()
            ),
            "download_size": archive.stat().st_size,
            "download_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "download_url": (
                "https://github.com/mrcpuddington/kobeestudio/"
                "releases/download/v{}/{}"
            ).format(version, package_name),
        }
    )
    (BUILD / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    _copy_plugin()
    shutil.copytree(HERE / "resources", STAGING / "resources")
    metadata, version = _write_metadata()
    archive = _build_archive(version)
    _write_repository_metadata(metadata, version, archive)
    print(archive)


if __name__ == "__main__":
    main()

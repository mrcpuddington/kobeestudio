"""Build a self-contained development directory for KiCad's IPC plugin loader."""

from __future__ import annotations

import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = HERE / "build"
PACKAGE = BUILD / "kobeestudio-ipc"
PLUGIN_DIR = PACKAGE / "com.github.mrcpuddington.kobeestudio"


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    PLUGIN_DIR.mkdir(parents=True)

    for filename in (
        "plugin.json",
        "requirements.txt",
        "kobeestudio_ipc.py",
        "kobee-toolbar-24.png",
        "kobee-toolbar-48.png",
    ):
        shutil.copy2(HERE / filename, PLUGIN_DIR / filename)

    shutil.copytree(
        ROOT / "kobeestudio",
        PLUGIN_DIR / "kobeestudio",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
    )
    shutil.copy2(ROOT / "LICENCE", PLUGIN_DIR / "LICENCE")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", PLUGIN_DIR / "THIRD_PARTY_NOTICES.md")
    shutil.make_archive(str(BUILD / "Kobee-Studio-IPC-development"), "zip", PACKAGE)


if __name__ == "__main__":
    main()

"""Build a self-contained development directory for KiCad's IPC plugin loader."""

from __future__ import annotations

import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = HERE / "build"
PACKAGE = BUILD / "kobeestudio-ipc"


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    PACKAGE.mkdir(parents=True)

    for filename in (
        "plugin.json",
        "requirements.txt",
        "kobeestudio_ipc.py",
        "kobee-bee.png",
    ):
        shutil.copy2(HERE / filename, PACKAGE / filename)

    shutil.copytree(
        ROOT / "kobeestudio",
        PACKAGE / "kobeestudio",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
    )
    shutil.copy2(ROOT / "LICENCE", PACKAGE / "LICENCE")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", PACKAGE / "THIRD_PARTY_NOTICES.md")
    shutil.make_archive(str(BUILD / "Kobee-Studio-IPC-development"), "zip", PACKAGE)


if __name__ == "__main__":
    main()

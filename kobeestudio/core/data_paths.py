"""Stable user/project data locations kept outside the installed package."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Union


APP_DIRECTORY_NAME = "kobee-studio"
PROJECT_DATA_DIRECTORY = ".kobeestudio"


def user_data_root(
    platform: Optional[str] = None,
    environment: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    """Return a per-user update-safe data root without depending on wx."""
    platform = platform or sys.platform
    environment = environment if environment is not None else os.environ
    home = Path(home) if home is not None else Path.home()
    if platform == "win32":
        base = Path(environment.get("APPDATA") or environment.get("LOCALAPPDATA") or home / "AppData" / "Roaming")
        return base / "Kobee Studio"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Kobee Studio"
    return Path(environment.get("XDG_DATA_HOME") or home / ".local" / "share") / APP_DIRECTORY_NAME


def project_data_root(project: Union[str, Path]) -> Path:
    """Return the data directory beside a project directory or KiCad project file."""
    path = Path(project).expanduser()
    if path.suffix.lower() in (".kicad_pcb", ".kicad_pro", ".brd", ".pro"):
        path = path.parent
    return path / PROJECT_DATA_DIRECTORY

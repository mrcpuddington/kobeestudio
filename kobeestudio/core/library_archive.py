"""Safe portable archive support for a user's Kobee Studio data library."""

from __future__ import annotations

import shutil
import os
import tempfile
import uuid
import zipfile
from pathlib import Path


_ALLOWED_PREFIXES = ("assets/v1/", "profiles/v1/", "labels/v1/")
_MAX_FILES = 5000
_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


def _allowed(relative: str) -> bool:
    return relative == "preferences.json" or relative.startswith(_ALLOWED_PREFIXES)


def export_library(source_root: Path, destination: Path) -> int:
    """Write custom assets, labels, profiles, and preferences to a portable zip."""
    source_root, destination = Path(source_root), Path(destination)
    count = 0
    with zipfile.ZipFile(str(destination), "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_root.rglob("*")) if source_root.exists() else ():
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(source_root).as_posix()
            if _allowed(relative):
                archive.write(str(path), relative)
                count += 1
    return count


def import_library(source: Path, destination_root: Path) -> int:
    """Merge an exported library without overwriting existing local files."""
    source, destination_root = Path(source), Path(destination_root)
    with zipfile.ZipFile(str(source), "r") as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_FILES or sum(info.file_size for info in infos) > _MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Library archive is too large")
        safe = []
        for info in infos:
            relative = Path(info.filename)
            if info.is_dir():
                continue
            if relative.is_absolute() or ".." in relative.parts or not _allowed(relative.as_posix()):
                raise ValueError("Library archive contains an invalid path")
            safe.append((info, relative))
        copied = 0
        for info, relative in safe:
            target = destination_root / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as incoming, target.open("xb") as output:
                shutil.copyfileobj(incoming, output)
            copied += 1
    return copied


def restore_library(source: Path, destination_root: Path) -> int:
    """Replace the portable library contents from a validated archive.

    The caller must obtain an explicit confirmation: existing preferences,
    assets, profiles, and quick labels are moved aside before replacement, so
    an interrupted write can restore the prior library rather than half-merge
    unrelated records.
    """
    source, destination_root = Path(source), Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(source), "r") as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_FILES or sum(info.file_size for info in infos) > _MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Library archive is too large")
        safe = []
        for info in infos:
            relative = Path(info.filename)
            if info.is_dir():
                continue
            if relative.is_absolute() or ".." in relative.parts or not _allowed(relative.as_posix()):
                raise ValueError("Library archive contains an invalid path")
            safe.append((info, relative))
        staging = Path(tempfile.mkdtemp(prefix=".library-restore-", dir=str(destination_root.parent)))
        backup = destination_root.parent / ".library-backup-{}".format(uuid.uuid4())
        roots = ("assets", "profiles", "labels", "preferences.json")
        try:
            for info, relative in safe:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as incoming, target.open("xb") as output:
                    shutil.copyfileobj(incoming, output)
            backup.mkdir()
            for name in roots:
                current = destination_root / name
                if current.exists() or current.is_symlink():
                    os.replace(str(current), str(backup / name))
            for name in roots:
                incoming = staging / name
                if incoming.exists():
                    os.replace(str(incoming), str(destination_root / name))
        except Exception:
            for name in roots:
                current, prior = destination_root / name, backup / name
                if not prior.exists() and not prior.is_symlink():
                    continue
                if current.exists() or current.is_symlink():
                    if current.is_dir() and not current.is_symlink():
                        shutil.rmtree(str(current))
                    else:
                        current.unlink()
                os.replace(str(prior), str(current))
            raise
        finally:
            shutil.rmtree(str(staging), ignore_errors=True)
        shutil.rmtree(str(backup), ignore_errors=True)
    return len(safe)


def reset_library(destination_root: Path) -> None:
    """Remove all mutable library data, leaving the bundled defaults intact."""
    destination_root = Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    names = ("assets", "profiles", "labels", "preferences.json")
    tombstone = destination_root.parent / ".library-reset-{}".format(uuid.uuid4())
    try:
        tombstone.mkdir()
        for name in names:
            current = destination_root / name
            if current.exists() or current.is_symlink():
                os.replace(str(current), str(tombstone / name))
    except Exception:
        for name in names:
            prior, current = tombstone / name, destination_root / name
            if prior.exists() or prior.is_symlink():
                os.replace(str(prior), str(current))
        raise
    shutil.rmtree(str(tombstone), ignore_errors=True)

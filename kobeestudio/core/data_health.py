"""Read-only diagnostics and non-destructive backups for user data.

The normal stores intentionally keep working when one optional record is
broken.  This module makes those skipped records visible so a later save does
not look like it silently erased something.  It never changes a source file.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Tuple

from .font_library import MAX_CATALOG_BYTES


_PORTABLE_ROOTS = (
    "assets", "profiles", "labels", "fonts", "component-presets",
    "reference-templates", "variable-templates", "project-data",
)
_MAX_JSON_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DataHealthIssue:
    """One local data file that Kobee deliberately did not trust."""

    path: Path
    relative_path: str
    detail: str


def _expected_schema(relative: Path):
    """Return the schema version for records that are versioned as v1."""
    text = relative.as_posix()
    if text == "preferences.json" or text == "project-data/v1/catalog.json":
        return 1
    if text.endswith("/metadata.json") and (
        text.startswith("assets/v1/") or text.startswith("fonts/v1/")
    ):
        return 1
    if text.startswith(("profiles/v1/", "labels/v1/", "component-presets/v1/", "reference-templates/v1/", "variable-templates/v1/")):
        return 1
    return None


def _candidate_files(root: Path) -> Iterable[Path]:
    preference_path = root / "preferences.json"
    if preference_path.exists() or preference_path.is_symlink():
        yield preference_path
    for name in _PORTABLE_ROOTS:
        directory = root / name
        if directory.is_symlink():
            yield directory
            continue
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.json"):
            yield path


def scan_user_data(root: Path) -> Tuple[DataHealthIssue, ...]:
    """Report malformed, unreadable, or symlinked user-data JSON records.

    The scan is intentionally bounded and read-only.  Schema validation stays
    conservative: it flags unsupported versions without guessing how to
    migrate them.
    """
    root = Path(root)
    issues = []
    for path in _candidate_files(root):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        display = relative.as_posix()
        if path.is_symlink():
            issues.append(DataHealthIssue(path, display, "Symlinks are not trusted for Kobee data"))
            continue
        if not path.is_file():
            issues.append(DataHealthIssue(path, display, "Expected a regular JSON file"))
            continue
        try:
            # A refreshed Google catalogue contains thousands of families and
            # legitimately exceeds the limit for individual user records.
            # Keep this exact cache path aligned with the downloader's bound.
            max_bytes = MAX_CATALOG_BYTES if display == "fonts/v1/catalog.json" else _MAX_JSON_BYTES
            if path.stat().st_size > max_bytes:
                raise ValueError("JSON record exceeds the {} MiB safety limit".format(max_bytes // (1024 * 1024)))
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON record must contain an object")
            expected = _expected_schema(relative)
            if expected is not None and payload.get("schema_version") != expected:
                raise ValueError("Unsupported schema version (expected {})".format(expected))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            issues.append(DataHealthIssue(path, display, str(error)))
    return tuple(sorted(issues, key=lambda item: item.relative_path))


def backup_data_issues(root: Path, issues: Iterable[DataHealthIssue]) -> Path:
    """Copy diagnosed regular files into a timestamped recovery folder.

    Originals remain untouched.  Symlinks and files outside ``root`` are never
    copied, even if a stale UI report includes them.
    """
    root = Path(root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = root / "recovery" / "v1" / "{}-{}".format(timestamp, uuid.uuid4().hex[:8])
    destination.mkdir(parents=True, exist_ok=False)
    copied = []
    try:
        for issue in issues:
            source = Path(issue.path)
            try:
                relative = source.relative_to(root)
            except ValueError:
                continue
            if source.is_symlink() or not source.is_file():
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(target), follow_symlinks=False)
            copied.append({"path": relative.as_posix(), "detail": issue.detail})
        report = destination / "report.json"
        descriptor, temporary = tempfile.mkstemp(prefix=".recovery-report-", suffix=".tmp", dir=str(destination))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({"schema_version": 1, "issues": copied}, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, str(report))
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    except Exception:
        # A failed backup must not leave a folder that looks complete.
        shutil.rmtree(str(destination), ignore_errors=True)
        raise
    return destination

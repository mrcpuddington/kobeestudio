"""Update-safe, user-managed quick-label storage.

Bundled labels are deliberately read-only.  User labels live as individual
versioned JSON files so they can be edited, deleted, backed up, and merged
without touching an installed package.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from .data_paths import project_data_root, user_data_root


QUICK_LABEL_SCHEMA_VERSION = 1


def _text(value: str, field: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 100 or any(ord(character) < 32 for character in value):
        raise ValueError("{} must contain 1 to 100 printable characters".format(field))
    return value


def _variant(value: str) -> str:
    value = str(value).strip().lower()
    if not value or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value):
        raise ValueError("Symbol variant must use lowercase letters, numbers, and underscores")
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".quick-label-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class QuickLabel:
    preset_id: str
    text: str
    category: str
    symbol_id: str = ""
    symbol_variant: str = "default"
    scope: str = "global"

    def __post_init__(self) -> None:
        if self.scope not in ("global", "project"):
            raise ValueError("Quick-label scope must be global or project")
        if not self.preset_id.startswith("custom_"):
            raise ValueError("Custom quick-label ids must start with custom_")
        _text(self.text, "Label text")
        _text(self.category, "Label category")
        _variant(self.symbol_variant)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": QUICK_LABEL_SCHEMA_VERSION,
            "preset_id": self.preset_id,
            "text": self.text,
            "category": self.category,
            "symbol_id": self.symbol_id,
            "symbol_variant": self.symbol_variant,
            "scope": self.scope,
        }


class QuickLabelStore:
    """A global or project-local collection of individual quick-label files."""

    def __init__(self, root: Path, scope: str) -> None:
        if scope not in ("global", "project"):
            raise ValueError("Quick-label scope must be global or project")
        self.root = Path(root) / "labels" / "v1" / "items"
        self.scope = scope

    @classmethod
    def global_store(cls, root: Optional[Path] = None) -> "QuickLabelStore":
        return cls(Path(root) if root is not None else user_data_root(), "global")

    @classmethod
    def project_store(cls, project: Union[str, Path]) -> "QuickLabelStore":
        return cls(project_data_root(project), "project")

    def list(self) -> Tuple[QuickLabel, ...]:
        if not self.root.exists():
            return ()
        labels = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != QUICK_LABEL_SCHEMA_VERSION or payload.get("scope") != self.scope:
                    continue
                label = QuickLabel(
                    str(payload["preset_id"]), str(payload["text"]), str(payload["category"]),
                    str(payload.get("symbol_id", "")), str(payload.get("symbol_variant", "default")), self.scope,
                )
                if path.name != label.preset_id + ".json":
                    continue
                labels.append(label)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(sorted(labels, key=lambda item: (item.category.casefold(), item.text.casefold(), item.preset_id)))

    def save(
        self, text: str, category: str, symbol_id: str = "", symbol_variant: str = "default", preset_id: Optional[str] = None
    ) -> QuickLabel:
        label = QuickLabel(
            preset_id or "custom_{}".format(uuid.uuid4().hex), text, category, str(symbol_id).strip(), symbol_variant, self.scope
        )
        _atomic_json(self.root / (label.preset_id + ".json"), label.to_dict())
        return label

    def delete(self, preset_id: str) -> None:
        path = self.root / (str(preset_id) + ".json")
        if path.is_symlink() or not path.is_file():
            raise LookupError("Quick label was not found")
        path.unlink()

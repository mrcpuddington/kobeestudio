"""User-defined component geometry presets with global/project scope."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

from .component_callout import CUTOUT_SHAPES
from .data_paths import project_data_root, user_data_root


COMPONENT_PRESET_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CustomComponentPreset:
    preset_id: str
    name: str
    width_mm: float
    height_mm: float
    cutout_shape: str = "rounded_rectangle"
    cutout_radius_mm: float = 0.2
    scope: str = "global"

    def __post_init__(self) -> None:
        if not self.preset_id or not self.name.strip() or len(self.name.strip()) > 100 or any(ord(character) < 32 for character in self.name):
            raise ValueError("Component preset needs an id and a 1–100 character name")
        if self.scope not in ("global", "project"):
            raise ValueError("Component preset scope must be global or project")
        if self.cutout_shape not in CUTOUT_SHAPES:
            raise ValueError("Unsupported component cutout shape")
        if not all(math.isfinite(value) for value in (self.width_mm, self.height_mm, self.cutout_radius_mm)) or self.width_mm <= 0 or self.height_mm <= 0 or self.cutout_radius_mm < 0:
            raise ValueError("Component dimensions must be positive and radius non-negative")


class ComponentPresetStore:
    def __init__(self, root: Path, scope: str) -> None:
        self.root = Path(root) / "component-presets" / "v1"
        self.scope = scope

    @classmethod
    def global_store(cls, root: Optional[Path] = None) -> "ComponentPresetStore":
        return cls(Path(root) if root is not None else user_data_root(), "global")

    @classmethod
    def project_store(cls, project: Union[str, Path]) -> "ComponentPresetStore":
        return cls(project_data_root(project), "project")

    def list(self) -> Tuple[CustomComponentPreset, ...]:
        items = []
        if not self.root.exists():
            return ()
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.pop("schema_version", None) != COMPONENT_PRESET_SCHEMA_VERSION:
                    continue
                item = CustomComponentPreset(**payload)
                if item.scope == self.scope and path.stem == item.preset_id:
                    items.append(item)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(sorted(items, key=lambda item: item.name.casefold()))

    def save(self, name: str, width_mm: float, height_mm: float, cutout_shape: str,
             cutout_radius_mm: float, preset_id: Optional[str] = None) -> CustomComponentPreset:
        preset_id = str(uuid.UUID(preset_id)) if preset_id else str(uuid.uuid4())
        item = CustomComponentPreset(preset_id, name.strip(), float(width_mm), float(height_mm),
                                     cutout_shape, float(cutout_radius_mm), self.scope)
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / "{}.json".format(preset_id)
        descriptor, temporary = tempfile.mkstemp(prefix=".preset-", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(dict(asdict(item), schema_version=COMPONENT_PRESET_SCHEMA_VERSION), stream,
                          ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, str(destination))
        except Exception:
            try: os.unlink(temporary)
            except OSError: pass
            raise
        return item

    def delete(self, preset_id: str) -> None:
        path = self.root / "{}.json".format(uuid.UUID(str(preset_id)))
        if path.is_symlink() or not path.is_file():
            raise LookupError("Component preset was not found")
        tombstone = path.with_name(".delete-{}.json".format(uuid.uuid4()))
        os.replace(str(path), str(tombstone)); tombstone.unlink()

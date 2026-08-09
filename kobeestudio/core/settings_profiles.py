"""Versioned, module-scoped settings profiles stored outside app installs."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .data_paths import user_data_root


PROFILE_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_SETTINGS_BYTES = 512 * 1024
PROFILE_MODULE_BY_MODE = {
    "Label": "labels",
    "2.54 mm Pin Header": "pin_headers",
    "Component Callout": "component_callouts",
    "Component Array": "component_arrays",
    "QR / Barcode": "machine_codes",
}


def profile_module_for_mode(mode: str) -> str:
    try:
        return PROFILE_MODULE_BY_MODE[str(mode)]
    except KeyError:
        raise ValueError("Unsupported profile mode: {}".format(mode))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_module(module: str) -> str:
    module = str(module).strip().lower()
    if not _IDENTIFIER.fullmatch(module):
        raise ValueError("Profile module must use lowercase letters, numbers, and underscores")
    return module


def _validate_name(name: str) -> str:
    name = str(name).strip()
    if not name or len(name) > 100 or any(ord(character) < 32 for character in name):
        raise ValueError("Profile name must contain 1 to 100 printable characters")
    return name


def _safe_settings(settings: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(settings, Mapping):
        raise ValueError("Profile settings must be a mapping")
    copied = dict(settings)
    try:
        encoded = json.dumps(copied, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("Profile settings must be finite JSON values: {}".format(error))
    if len(encoded) > _MAX_SETTINGS_BYTES:
        raise ValueError("Profile settings exceed the 512 KiB limit")
    return json.loads(encoded.decode("utf-8"))


def _validate_settings_module(module: str, settings: Mapping[str, Any]) -> None:
    mode = settings.get("StudioModeChoice")
    if mode is not None and profile_module_for_mode(str(mode)) != module:
        raise ValueError("Profile settings do not match the {} module".format(module))


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".{}-".format(path.name), suffix=".tmp", dir=str(path.parent))
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
class SettingsProfile:
    profile_id: str
    module: str
    name: str
    settings: Mapping[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SettingsProfile":
        if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
            raise ValueError("Unsupported settings profile schema")
        module = _validate_module(payload["module"])
        settings = _safe_settings(payload["settings"])
        _validate_settings_module(module, settings)
        return cls(
            profile_id=str(uuid.UUID(str(payload["profile_id"]))),
            module=module,
            name=_validate_name(payload["name"]),
            settings=settings,
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "module": self.module,
            "name": self.name,
            "settings": dict(self.settings),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SettingsProfileStore:
    """A per-file profile store; defaults and modules cannot corrupt each other."""

    def __init__(self, data_root: Optional[Path] = None) -> None:
        self.root = Path(data_root) if data_root is not None else user_data_root()
        self.profiles_root = self.root / "profiles" / "v1"

    def _module_root(self, module: str) -> Path:
        return self.profiles_root / _validate_module(module)

    def _profile_path(self, module: str, profile_id: str) -> Path:
        return self._module_root(module) / "items" / "{}.json".format(uuid.UUID(str(profile_id)))

    def list(self, module: str) -> Tuple[SettingsProfile, ...]:
        module = _validate_module(module)
        items = []
        directory = self._module_root(module) / "items"
        if not directory.exists():
            return ()
        for path in sorted(directory.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                profile = SettingsProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if profile.module != module or path.stem != profile.profile_id:
                    continue
                items.append(profile)
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
                continue
        return tuple(sorted(items, key=lambda item: (item.name.casefold(), item.profile_id)))

    def save(
        self,
        module: str,
        name: str,
        settings: Mapping[str, Any],
        profile_id: Optional[str] = None,
        make_default: bool = False,
    ) -> SettingsProfile:
        module = _validate_module(module)
        name = _validate_name(name)
        settings_copy = _safe_settings(settings)
        _validate_settings_module(module, settings_copy)
        if profile_id is not None:
            profile_id = str(uuid.UUID(str(profile_id)))
        for existing in self.list(module):
            if existing.name.casefold() == name.casefold() and existing.profile_id != profile_id:
                raise ValueError("A profile named {!r} already exists in {}".format(name, module))

        now = _utc_now()
        if profile_id is None:
            profile_id = str(uuid.uuid4())
            created_at = now
        else:
            existing = self.load(module, profile_id)
            profile_id = existing.profile_id
            created_at = existing.created_at
        profile = SettingsProfile(profile_id, module, name, settings_copy, created_at, now)
        _atomic_json(self._profile_path(module, profile_id), profile.to_dict())
        if make_default:
            self.set_default(module, profile_id)
        return profile

    def load(self, module: str, profile_id: Optional[str] = None) -> SettingsProfile:
        module = _validate_module(module)
        if profile_id is None:
            profile_id = self.default_id(module)
            if profile_id is None:
                raise LookupError("No default profile is set for {}".format(module))
        path = self._profile_path(module, profile_id)
        if path.is_symlink() or not path.is_file():
            raise LookupError("Settings profile does not exist: {}".format(profile_id))
        profile = SettingsProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if profile.module != module:
            raise ValueError("Settings profile module does not match its storage location")
        return profile

    def set_default(self, module: str, profile_id: Optional[str]) -> None:
        module = _validate_module(module)
        if profile_id is not None:
            profile_id = self.load(module, profile_id).profile_id
        _atomic_json(
            self._module_root(module) / "default.json",
            {"schema_version": PROFILE_SCHEMA_VERSION, "profile_id": profile_id},
        )

    def default_id(self, module: str) -> Optional[str]:
        path = self._module_root(module) / "default.json"
        if path.is_symlink() or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if payload.get("schema_version") != PROFILE_SCHEMA_VERSION or payload.get("profile_id") is None:
            return None
        try:
            return str(uuid.UUID(str(payload["profile_id"])))
        except (TypeError, ValueError):
            return None

    def delete(self, module: str, profile_id: str) -> None:
        module = _validate_module(module)
        profile = self.load(module, profile_id)
        path = self._profile_path(module, profile.profile_id)
        path.unlink()
        if self.default_id(module) == profile.profile_id:
            self.set_default(module, None)

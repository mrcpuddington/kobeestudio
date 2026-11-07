"""Small, versioned application preferences independent of artwork settings."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .data_paths import user_data_root
from .measurement_units import MeasurementUnit


PREFERENCES_SCHEMA_VERSION = 1
APPEARANCE_CHOICES = ("system", "light", "dark")
DEFAULT_FAVOURITE_FONT_NAMES = (
    "FreddySpark-Regular",
    "UbuntuMono-B",
    "mplus-1mn-medium",
)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".preferences-", suffix=".tmp", dir=str(path.parent))
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
class AppPreferences:
    appearance: str = "system"
    measurement_unit: MeasurementUnit = MeasurementUnit.MILLIMETRES
    hidden_symbol_ids: Tuple[str, ...] = ()
    hidden_label_ids: Tuple[str, ...] = ()
    favourite_font_names: Tuple[str, ...] = DEFAULT_FAVOURITE_FONT_NAMES
    # System fonts are intentionally opt-in. A workstation can expose
    # hundreds of faces, so discovery must not flood every typeface picker.
    enabled_system_font_names: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        appearance = str(self.appearance).strip().lower()
        if appearance not in APPEARANCE_CHOICES:
            raise ValueError("Appearance must be system, light, or dark")
        object.__setattr__(self, "appearance", appearance)
        object.__setattr__(self, "measurement_unit", MeasurementUnit.parse(self.measurement_unit))
        for field in (
            "hidden_symbol_ids", "hidden_label_ids", "favourite_font_names",
            "enabled_system_font_names",
        ):
            raw = getattr(self, field)
            if isinstance(raw, str):
                raise ValueError("{} must be a list of ids".format(field))
            try:
                cleaned = tuple(sorted({str(value).strip() for value in raw if str(value).strip()}))
            except TypeError:
                raise ValueError("{} must be a list of ids".format(field))
            object.__setattr__(self, field, cleaned)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": PREFERENCES_SCHEMA_VERSION,
            "appearance": self.appearance,
            "measurement_unit": self.measurement_unit.value,
            "hidden_symbol_ids": list(self.hidden_symbol_ids),
            "hidden_label_ids": list(self.hidden_label_ids),
            "favourite_font_names": list(self.favourite_font_names),
            "enabled_system_font_names": list(self.enabled_system_font_names),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AppPreferences":
        if payload.get("schema_version") != PREFERENCES_SCHEMA_VERSION:
            raise ValueError("Unsupported application preferences schema")
        return cls(
            appearance=str(payload.get("appearance", "system")),
            measurement_unit=MeasurementUnit.parse(payload.get("measurement_unit", "mm")),
            hidden_symbol_ids=tuple(payload.get("hidden_symbol_ids", ())),
            hidden_label_ids=tuple(payload.get("hidden_label_ids", ())),
            favourite_font_names=tuple(
                payload.get("favourite_font_names", DEFAULT_FAVOURITE_FONT_NAMES)
            ),
            enabled_system_font_names=tuple(payload.get("enabled_system_font_names", ())),
        )


class AppPreferencesStore:
    def __init__(self, data_root: Optional[Path] = None) -> None:
        self.root = Path(data_root) if data_root is not None else user_data_root()
        self.path = self.root / "preferences.json"

    def load_strict(self) -> AppPreferences:
        """Load preferences or explain why an existing record is unusable."""
        if self.path.is_symlink():
            raise ValueError("Application preferences must be a regular file, not a symlink")
        if not self.path.exists():
            return AppPreferences()
        if not self.path.is_file():
            raise ValueError("Application preferences path is not a regular file")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Application preferences must be a JSON object")
        return AppPreferences.from_dict(payload)

    def load(self) -> AppPreferences:
        """Keep the app usable, while preserving an unreadable source file."""
        try:
            return self.load_strict()
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return AppPreferences()

    def save(self, preferences: AppPreferences) -> None:
        if not isinstance(preferences, AppPreferences):
            raise TypeError("preferences must be AppPreferences")
        # Do not turn a corrupt external file into a clean default merely by
        # opening Settings and pressing Save.  Data Health can first back it
        # up; removing/recovering it is an explicit user action.
        if self.path.exists() or self.path.is_symlink():
            self.load_strict()
        _atomic_json(self.path, preferences.to_dict())

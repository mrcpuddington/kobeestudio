"""Development feature flags with safe, production-off defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Mapping, Optional


SVG_SYMBOLS = "svg_symbols"
CUSTOM_ASSETS = "custom_assets"
SETTINGS_PROFILES = "settings_profiles"
ALTERNATIVE_UNITS = "alternative_units"

KNOWN_FLAGS = frozenset(
    (SVG_SYMBOLS, CUSTOM_ASSETS, SETTINGS_PROFILES, ALTERNATIVE_UNITS)
)
ENVIRONMENT_VARIABLE = "KOBEE_DEV_FEATURES"


def _normalise_flags(values: Iterable[str]) -> FrozenSet[str]:
    enabled = frozenset(str(value).strip().lower() for value in values if str(value).strip())
    unknown = enabled - KNOWN_FLAGS
    if unknown:
        raise ValueError("Unknown Kobee Studio development feature(s): {}".format(", ".join(sorted(unknown))))
    return enabled


@dataclass(frozen=True)
class FeatureFlags:
    """An explicit flag set suitable for dependency injection and tests."""

    enabled_flags: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled_flags", _normalise_flags(self.enabled_flags))

    def enabled(self, name: str) -> bool:
        if name not in KNOWN_FLAGS:
            raise ValueError("Unknown Kobee Studio development feature: {}".format(name))
        return name in self.enabled_flags

    @classmethod
    def from_environment(cls, environment: Optional[Mapping[str, str]] = None) -> "FeatureFlags":
        source = environment if environment is not None else os.environ
        raw = source.get(ENVIRONMENT_VARIABLE, "")
        return cls(_normalise_flags(raw.split(",")))


def development_feature_enabled(name: str) -> bool:
    """Read the process flags. The default is deliberately always disabled."""
    return FeatureFlags.from_environment().enabled(name)

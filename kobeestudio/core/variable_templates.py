"""Reusable templates for KiCad-native project text variables."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from .data_paths import project_data_root, user_data_root


VARIABLE_TEMPLATE_SCHEMA_VERSION = 1
_VARIABLE = re.compile(r"\$\{([^{}]+)\}")


def _printable(value: str, field_name: str, maximum: int) -> str:
    value = str(value).strip()
    if not value or len(value) > maximum:
        raise ValueError("{} must contain 1 to {} characters".format(field_name, maximum))
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("{} contains unsupported control characters".format(field_name))
    return value


def variable_names(template_text: str) -> Tuple[str, ...]:
    """Return unique ``${NAME}`` contents in first-use order."""
    names = []
    for match in _VARIABLE.finditer(str(template_text)):
        name = match.group(1).strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def validate_variable_template(template_text: str) -> str:
    """Validate replacement syntax without restricting KiCad built-ins."""
    text = str(template_text)
    if not text.strip() or len(text) > 8000:
        raise ValueError("Variable template must contain 1 to 8000 characters")
    if any(ord(character) < 32 and character not in "\n\t" for character in text):
        raise ValueError("Variable template contains unsupported control characters")
    stripped = _VARIABLE.sub("", text)
    if "${" in stripped or "}" in stripped:
        raise ValueError("Variable expressions must use KiCad syntax such as ${REVISION}")
    if any(match.group(1) != match.group(1).strip() for match in _VARIABLE.finditer(text)):
        raise ValueError("Variable names cannot contain leading or trailing spaces")
    if any(not name for name in variable_names(text)):
        raise ValueError("Variable names cannot be empty")
    return text


def expand_variable_template(template_text: str, variables: Mapping[str, Any]) -> str:
    """Expand known variables for offline preview, preserving unknown ones."""
    text = validate_variable_template(template_text)
    values = {str(key): str(value) for key, value in dict(variables).items()}
    return _VARIABLE.sub(
        lambda match: values.get(match.group(1).strip(), match.group(0)),
        text,
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".variable-template-", suffix=".tmp", dir=str(path.parent)
    )
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
class VariableLabelTemplate:
    template_id: str
    name: str
    template_text: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    scope: str = "global"

    def __post_init__(self) -> None:
        if self.scope not in ("global", "project"):
            raise ValueError("Variable-template scope must be global or project")
        if not self.template_id.startswith("custom_"):
            raise ValueError("Variable-template ids must start with custom_")
        _printable(self.name, "Template name", 100)
        validate_variable_template(self.template_text)
        json.dumps(dict(self.settings), allow_nan=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": VARIABLE_TEMPLATE_SCHEMA_VERSION,
            "template_id": self.template_id,
            "name": self.name,
            "template_text": self.template_text,
            "settings": dict(self.settings),
            "scope": self.scope,
        }


class VariableTemplateStore:
    def __init__(self, root: Path, scope: str) -> None:
        if scope not in ("global", "project"):
            raise ValueError("Variable-template scope must be global or project")
        self.root = Path(root) / "variable-templates" / "v1" / "items"
        self.scope = scope

    @classmethod
    def global_store(cls, root: Optional[Path] = None) -> "VariableTemplateStore":
        return cls(Path(root) if root is not None else user_data_root(), "global")

    @classmethod
    def project_store(cls, project: Union[str, Path]) -> "VariableTemplateStore":
        return cls(project_data_root(project), "project")

    def list(self) -> Tuple[VariableLabelTemplate, ...]:
        if not self.root.exists():
            return ()
        templates = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != VARIABLE_TEMPLATE_SCHEMA_VERSION:
                    continue
                if payload.get("scope") != self.scope:
                    continue
                template = VariableLabelTemplate(
                    template_id=str(payload["template_id"]),
                    name=str(payload["name"]),
                    template_text=str(payload["template_text"]),
                    settings=dict(payload.get("settings", {})),
                    scope=self.scope,
                )
                if path.name == template.template_id + ".json":
                    templates.append(template)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(sorted(templates, key=lambda item: (item.name.casefold(), item.template_id)))

    def save(
        self,
        name: str,
        template_text: str,
        settings: Optional[Mapping[str, Any]] = None,
        template_id: Optional[str] = None,
    ) -> VariableLabelTemplate:
        template = VariableLabelTemplate(
            template_id=template_id or "custom_{}".format(uuid.uuid4().hex),
            name=name,
            template_text=template_text,
            settings=dict(settings or {}),
            scope=self.scope,
        )
        _atomic_json(self.root / (template.template_id + ".json"), template.to_dict())
        return template

    def delete(self, template_id: str) -> None:
        path = self.root / (str(template_id) + ".json")
        if path.is_symlink() or not path.is_file():
            raise LookupError("Variable template was not found")
        path.unlink()

"""Reusable multi-reference label templates.

Templates deliberately store their source text separately from rendered label
text.  A saved board item is therefore self-contained while Kobee Studio can
still reopen it and rebind the placeholders to the current board selection.
"""

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


REFERENCE_TEMPLATE_SCHEMA_VERSION = 1
_PLACEHOLDER = re.compile(r"\$(designators|designator(?:[1-9][0-9]*)?)\b", re.IGNORECASE)
_ANY_PLACEHOLDER = re.compile(r"\$([A-Za-z][A-Za-z0-9_]*)")


def _printable(value: str, field_name: str, maximum: int) -> str:
    value = str(value).strip()
    if not value or len(value) > maximum:
        raise ValueError("{} must contain 1 to {} characters".format(field_name, maximum))
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("{} contains unsupported control characters".format(field_name))
    return value


def template_placeholders(template_text: str) -> Tuple[str, ...]:
    """Return unique supported placeholders in first-use order."""
    found = []
    for match in _PLACEHOLDER.finditer(str(template_text)):
        token = "$" + match.group(1).lower()
        if token not in found:
            found.append(token)
    return tuple(found)


def resolve_reference_template(template_text: str, references: Sequence[str]) -> str:
    """Resolve a safe-label template against an ordered reference list.

    ``$designator`` aliases the first selected reference, numbered forms are
    one-based, and ``$designators`` expands every reference on separate lines.
    Repeating a placeholder is supported and always produces the same value.
    """
    template_text = _printable(template_text, "Template", 8000)
    references = tuple(str(reference).strip() for reference in references if str(reference).strip())
    supported = {token.casefold() for token in template_placeholders(template_text)}
    unknown = tuple(
        sorted(
            {
                "$" + match.group(1)
                for match in _ANY_PLACEHOLDER.finditer(template_text)
                if ("$" + match.group(1)).casefold() not in supported
            },
            key=str.casefold,
        )
    )
    if unknown:
        raise ValueError(
            "Unsupported placeholder(s): {}. Use $designator, $designator1, $designator2, … or $designators.".format(
                ", ".join(unknown)
            )
        )

    def replace(match) -> str:
        token = match.group(1).lower()
        if token == "designators":
            if not references:
                raise ValueError("Select at least one footprint to resolve $designators")
            return "\n".join(references)
        suffix = token[len("designator") :]
        index = int(suffix) - 1 if suffix else 0
        if index >= len(references):
            raise ValueError(
                "{} needs selected footprint {}, but only {} footprint(s) are available".format(
                    "$" + token, index + 1, len(references)
                )
            )
        return references[index]

    return _PLACEHOLDER.sub(replace, template_text)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".reference-template-", suffix=".tmp", dir=str(path.parent)
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
class ReferenceLabelTemplate:
    template_id: str
    name: str
    template_text: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    scope: str = "global"

    def __post_init__(self) -> None:
        if self.scope not in ("global", "project"):
            raise ValueError("Reference-template scope must be global or project")
        if not self.template_id.startswith("custom_"):
            raise ValueError("Reference-template ids must start with custom_")
        _printable(self.name, "Template name", 100)
        _printable(self.template_text, "Template", 8000)
        # Validate placeholder spelling now, while allowing templates that do
        # not use a placeholder at all.
        supported = {token.casefold() for token in template_placeholders(self.template_text)}
        unknown = {
            "$" + match.group(1)
            for match in _ANY_PLACEHOLDER.finditer(self.template_text)
            if ("$" + match.group(1)).casefold() not in supported
        }
        if unknown:
            raise ValueError("Unsupported placeholder(s): {}".format(", ".join(sorted(unknown))))
        json.dumps(dict(self.settings), allow_nan=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": REFERENCE_TEMPLATE_SCHEMA_VERSION,
            "template_id": self.template_id,
            "name": self.name,
            "template_text": self.template_text,
            "settings": dict(self.settings),
            "scope": self.scope,
        }


class ReferenceTemplateStore:
    def __init__(self, root: Path, scope: str) -> None:
        if scope not in ("global", "project"):
            raise ValueError("Reference-template scope must be global or project")
        self.root = Path(root) / "reference-templates" / "v1" / "items"
        self.scope = scope

    @classmethod
    def global_store(cls, root: Optional[Path] = None) -> "ReferenceTemplateStore":
        return cls(Path(root) if root is not None else user_data_root(), "global")

    @classmethod
    def project_store(cls, project: Union[str, Path]) -> "ReferenceTemplateStore":
        return cls(project_data_root(project), "project")

    def list(self) -> Tuple[ReferenceLabelTemplate, ...]:
        if not self.root.exists():
            return ()
        templates = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != REFERENCE_TEMPLATE_SCHEMA_VERSION:
                    continue
                if payload.get("scope") != self.scope:
                    continue
                template = ReferenceLabelTemplate(
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
    ) -> ReferenceLabelTemplate:
        template = ReferenceLabelTemplate(
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
            raise LookupError("Reference template was not found")
        path.unlink()

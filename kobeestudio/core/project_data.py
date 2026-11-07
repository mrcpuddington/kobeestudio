"""Project metadata, reusable fields, and immutable revision records.

The JSON records in this module deliberately stay independent from wx and the
KiCad IPC client.  This makes the project file safe to commit and lets the UI
and the IPC bridge share one validation and variable-generation surface.
"""

from __future__ import annotations

import json
import os
import re
import hashlib
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from .data_paths import user_data_root


PROJECT_DATA_SCHEMA_VERSION = 1
CATALOG_SCHEMA_VERSION = 1
PROJECT_DATA_FILENAME = "kobee-project.json"
FIELD_TYPES = ("text", "multiline", "date", "url", "number", "checkbox", "choice")
FIELD_SCOPES = ("global", "project", "revision")
_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class ProjectDataConflictError(RuntimeError):
    """The on-disk record changed after Kobee loaded it."""


class ProjectDataRecoveryError(RuntimeError):
    """The on-disk record cannot safely be interpreted as Project Data."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _string(value: Any, label: str, maximum: int = 4000, *, required: bool = False) -> str:
    value = str(value if value is not None else "").strip()
    if required and not value:
        raise ValueError("{} is required".format(label))
    if len(value) > maximum or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("{} contains unsupported text".format(label))
    return value


def _key(value: Any) -> str:
    value = str(value).strip().upper()
    if not _KEY.fullmatch(value):
        raise ValueError("Field key must use uppercase letters, numbers, and underscores")
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".{}-".format(path.name), suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
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
class FieldDefinition:
    field_id: str
    label: str
    key: str
    scope: str
    field_type: str = "text"
    help_text: str = ""
    choices: Tuple[str, ...] = ()
    default_value: Any = ""
    built_in: bool = False

    def __post_init__(self) -> None:
        if self.scope not in FIELD_SCOPES:
            raise ValueError("Unknown field scope")
        if self.field_type not in FIELD_TYPES:
            raise ValueError("Unknown field type")
        if self.built_in:
            if not self.field_id.startswith("default_"):
                raise ValueError("Built-in field ids must start with default_")
        elif not self.field_id.startswith("custom_"):
            raise ValueError("Custom field ids must start with custom_")
        if self.field_type == "checkbox" and self.default_value == "":
            object.__setattr__(self, "default_value", False)
        _string(self.label, "Field label", 100, required=True)
        _key(self.key)
        _string(self.help_text, "Field help", 400)
        choices = tuple(_string(item, "Choice", 100, required=True) for item in self.choices)
        if len(set(item.casefold() for item in choices)) != len(choices):
            raise ValueError("Field choices must be unique")
        if self.field_type == "choice" and not choices:
            raise ValueError("Choice fields need at least one choice")
        if self.field_type != "choice" and choices:
            raise ValueError("Only choice fields may have choices")
        object.__setattr__(self, "choices", choices)
        self.validate_value(self.default_value)

    def validate_value(self, value: Any) -> Any:
        if self.field_type == "checkbox":
            if not isinstance(value, bool):
                raise ValueError("{} must be a checkbox value".format(self.label))
            return value
        if self.field_type == "number":
            text = _string(value, self.label, 100)
            if text:
                try:
                    float(text)
                except ValueError:
                    raise ValueError("{} must be a number".format(self.label))
            return text
        text = _string(value, self.label, 8000 if self.field_type == "multiline" else 2000)
        if self.field_type == "date" and text:
            try:
                date.fromisoformat(text)
            except ValueError:
                raise ValueError("{} must use YYYY-MM-DD".format(self.label))
        if self.field_type == "url" and text and "://" not in text and not text.startswith("mailto:"):
            raise ValueError("{} must be a URL".format(self.label))
        if self.field_type == "choice" and text and text not in self.choices:
            raise ValueError("{} must be one of its choices".format(self.label))
        return text

    def format_value(self, value: Any) -> str:
        value = self.validate_value(value)
        return "Yes" if self.field_type == "checkbox" and value else "No" if self.field_type == "checkbox" else str(value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_id": self.field_id, "label": self.label, "key": self.key,
            "scope": self.scope, "field_type": self.field_type, "help_text": self.help_text,
            "choices": list(self.choices), "default_value": self.default_value, "built_in": self.built_in,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FieldDefinition":
        return cls(
            field_id=str(payload["field_id"]), label=str(payload["label"]), key=str(payload["key"]),
            scope=str(payload["scope"]), field_type=str(payload.get("field_type", "text")),
            help_text=str(payload.get("help_text", "")), choices=tuple(payload.get("choices", ())),
            default_value=payload.get("default_value", False if payload.get("field_type") == "checkbox" else ""),
            built_in=bool(payload.get("built_in", False)),
        )


GLOBAL_DEFAULT_FIELDS = (
    FieldDefinition("default_global_company_name", "Company name", "COMPANY_NAME", "global", built_in=True),
    FieldDefinition("default_global_company_website", "Company website", "COMPANY_WEBSITE", "global", "url", built_in=True),
)
PROJECT_DEFAULT_FIELDS = (
    FieldDefinition("default_project_name", "Project name", "PROJECT_NAME", "project", built_in=True),
    FieldDefinition("default_board_name", "Board name", "BOARD_NAME", "project", built_in=True),
    FieldDefinition("default_project_number", "Project number", "PROJECT_NUMBER", "project", built_in=True),
    FieldDefinition("default_pcb_part_number", "PCB part number", "PCB_PART_NUMBER", "project", built_in=True),
)
REVISION_DEFAULT_FIELDS = (
    FieldDefinition("default_revision", "Revision", "REVISION", "revision", built_in=True),
    FieldDefinition("default_hardware_version", "Hardware version", "HARDWARE_VERSION", "revision", built_in=True),
    FieldDefinition("default_issue_date", "Issue date", "ISSUE_DATE", "revision", "date", default_value="" , built_in=True),
    FieldDefinition("default_status", "Status", "STATUS", "revision", "choice", choices=("Draft", "Prototype", "Validation", "Pre-production", "Released", "Superseded", "Obsolete"), built_in=True),
    FieldDefinition("default_change_summary", "Change summary", "CHANGE_SUMMARY", "revision", "multiline", built_in=True),
    FieldDefinition("default_issued_by", "Issued by", "ISSUED_BY", "revision", built_in=True),
    FieldDefinition("default_approved_by", "Reviewed / approved by", "APPROVED_BY", "revision", built_in=True),
)
DEFAULT_FIELDS = GLOBAL_DEFAULT_FIELDS + PROJECT_DEFAULT_FIELDS + REVISION_DEFAULT_FIELDS
_CORE_REVISION_VARIABLES = {field.key: "KOBEE_" + field.key for field in REVISION_DEFAULT_FIELDS}


def _fields(payload: Iterable[Mapping[str, Any]], scope: Optional[str] = None) -> Tuple[FieldDefinition, ...]:
    result = tuple(FieldDefinition.from_dict(item) for item in payload)
    if scope and any(field.scope != scope for field in result):
        raise ValueError("Field is stored in the wrong scope")
    keys = [field.key for field in result]
    if len(set(keys)) != len(keys):
        raise ValueError("Field keys must be unique within a scope")
    return result


@dataclass(frozen=True)
class RevisionCheckpoint:
    revision_id: str
    created_at: str
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "revision_id", str(uuid.UUID(str(self.revision_id))))
        if not isinstance(self.values, Mapping):
            raise ValueError("Revision values must be a mapping")
        encoded = json.dumps(dict(self.values), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ValueError("Revision values are too large")

    def to_dict(self) -> Dict[str, Any]:
        return {"revision_id": self.revision_id, "created_at": self.created_at, "values": dict(self.values)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RevisionCheckpoint":
        return cls(str(payload["revision_id"]), str(payload["created_at"]), dict(payload.get("values", {})))


@dataclass(frozen=True)
class ProjectData:
    project_values: Mapping[str, Any] = field(default_factory=dict)
    local_project_fields: Tuple[FieldDefinition, ...] = ()
    local_revision_fields: Tuple[FieldDefinition, ...] = ()
    excluded_reusable_field_ids: Tuple[str, ...] = ()
    revision_draft: Mapping[str, Any] = field(default_factory=dict)
    revisions: Tuple[RevisionCheckpoint, ...] = ()
    active_revision_id: Optional[str] = None
    managed_variable_names: Tuple[str, ...] = ()
    sync_pending: bool = False
    last_synced_at: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_project_fields", tuple(self.local_project_fields))
        object.__setattr__(self, "local_revision_fields", tuple(self.local_revision_fields))
        _fields((field.to_dict() for field in self.local_project_fields), "project")
        _fields((field.to_dict() for field in self.local_revision_fields), "revision")
        excluded = tuple(sorted({str(value) for value in self.excluded_reusable_field_ids if str(value)}))
        object.__setattr__(self, "excluded_reusable_field_ids", excluded)
        revisions = tuple(self.revisions)
        ids = [item.revision_id for item in revisions]
        if len(set(ids)) != len(ids):
            raise ValueError("Revision ids must be unique")
        object.__setattr__(self, "revisions", revisions)
        if self.active_revision_id is not None and self.active_revision_id not in ids:
            raise ValueError("Active revision does not exist")
        managed = tuple(sorted({_string(item, "Variable name", 100, required=True) for item in self.managed_variable_names}))
        object.__setattr__(self, "managed_variable_names", managed)

    @classmethod
    def empty(cls) -> "ProjectData":
        return cls()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProjectData":
        if payload.get("schema_version") != PROJECT_DATA_SCHEMA_VERSION:
            raise ValueError("Unsupported project data schema")
        return cls(
            project_values=dict(payload.get("project_values", {})),
            local_project_fields=_fields(payload.get("local_project_fields", ()), "project"),
            local_revision_fields=_fields(payload.get("local_revision_fields", ()), "revision"),
            excluded_reusable_field_ids=tuple(payload.get("excluded_reusable_field_ids", ())),
            revision_draft=dict(payload.get("revision_draft", {})),
            revisions=tuple(RevisionCheckpoint.from_dict(item) for item in payload.get("revisions", ())),
            active_revision_id=payload.get("active_revision_id"),
            managed_variable_names=tuple(payload.get("managed_variable_names", ())),
            sync_pending=bool(payload.get("sync_pending", False)),
            last_synced_at=payload.get("last_synced_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": PROJECT_DATA_SCHEMA_VERSION, "project_values": dict(self.project_values),
            "local_project_fields": [item.to_dict() for item in self.local_project_fields],
            "local_revision_fields": [item.to_dict() for item in self.local_revision_fields],
            "excluded_reusable_field_ids": list(self.excluded_reusable_field_ids),
            "revision_draft": dict(self.revision_draft),
            "revisions": [item.to_dict() for item in self.revisions],
            "active_revision_id": self.active_revision_id,
            "managed_variable_names": list(self.managed_variable_names),
            "sync_pending": self.sync_pending,
            "last_synced_at": self.last_synced_at,
        }

    def active_revision(self) -> Optional[RevisionCheckpoint]:
        return next((item for item in self.revisions if item.revision_id == self.active_revision_id), None)

    def with_checkpoint(self, values: Mapping[str, Any]) -> "ProjectData":
        revision = _string(values.get("default_revision", ""), "Revision", 100, required=True)
        issue_date = _string(values.get("default_issue_date", ""), "Issue date", 100, required=True)
        status = _string(values.get("default_status", ""), "Status", 100, required=True)
        try:
            date.fromisoformat(issue_date)
        except ValueError:
            raise ValueError("Issue date must use YYYY-MM-DD")
        if any(
            str(item.values.get("default_revision", "")).casefold() == revision.casefold()
            for item in self.revisions
        ):
            raise ValueError("Revision {} already exists; restore it or choose a new revision".format(revision))
        checkpoint = RevisionCheckpoint(str(uuid.uuid4()), _utc_now(), dict(values))
        return self._replace(revisions=self.revisions + (checkpoint,), active_revision_id=checkpoint.revision_id, revision_draft=dict(values))

    def restore_to_draft(self, revision_id: str) -> "ProjectData":
        checkpoint = next((item for item in self.revisions if item.revision_id == revision_id), None)
        if checkpoint is None:
            raise LookupError("Revision checkpoint was not found")
        return self._replace(revision_draft=dict(checkpoint.values))

    def delete_revision(self, revision_id: str) -> "ProjectData":
        revisions = tuple(item for item in self.revisions if item.revision_id != revision_id)
        if len(revisions) == len(self.revisions):
            raise LookupError("Revision checkpoint was not found")
        active = self.active_revision_id if self.active_revision_id != revision_id else (revisions[-1].revision_id if revisions else None)
        return self._replace(revisions=revisions, active_revision_id=active)

    def with_managed_variable_names(self, names: Sequence[str]) -> "ProjectData":
        return self._replace(managed_variable_names=tuple(names))

    def with_sync_state(self, *, pending: bool, synced_at: Optional[str] = None) -> "ProjectData":
        return self._replace(sync_pending=bool(pending), last_synced_at=synced_at)

    def mark_synced(self) -> "ProjectData":
        return self.with_sync_state(pending=False, synced_at=_utc_now())

    def _replace(self, **changes: Any) -> "ProjectData":
        values = {
            "project_values": self.project_values,
            "local_project_fields": self.local_project_fields,
            "local_revision_fields": self.local_revision_fields,
            "excluded_reusable_field_ids": self.excluded_reusable_field_ids,
            "revision_draft": self.revision_draft,
            "revisions": self.revisions,
            "active_revision_id": self.active_revision_id,
            "managed_variable_names": self.managed_variable_names,
            "sync_pending": self.sync_pending,
            "last_synced_at": self.last_synced_at,
        }
        values.update(changes)
        return ProjectData(**values)


@dataclass(frozen=True)
class ProjectDataCatalog:
    global_fields: Tuple[FieldDefinition, ...] = ()
    reusable_fields: Tuple[FieldDefinition, ...] = ()
    global_values: Mapping[str, Any] = field(default_factory=dict)
    hidden_default_field_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        global_fields = tuple(self.global_fields); reusable_fields = tuple(self.reusable_fields)
        _fields((item.to_dict() for item in global_fields), "global")
        if any(item.scope == "global" for item in reusable_fields):
            raise ValueError("Reusable fields must be project or revision scoped")
        identifiers = [item.field_id for item in global_fields + reusable_fields]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Field ids must be unique")
        object.__setattr__(self, "global_fields", global_fields)
        object.__setattr__(self, "reusable_fields", reusable_fields)
        object.__setattr__(self, "hidden_default_field_ids", tuple(sorted(set(self.hidden_default_field_ids))))

    @classmethod
    def empty(cls) -> "ProjectDataCatalog":
        return cls()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProjectDataCatalog":
        if payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
            raise ValueError("Unsupported Project Data catalog schema")
        return cls(
            global_fields=_fields(payload.get("global_fields", ()), "global"),
            reusable_fields=_fields(payload.get("reusable_fields", ())),
            global_values=dict(payload.get("global_values", {})),
            hidden_default_field_ids=tuple(payload.get("hidden_default_field_ids", ())),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "global_fields": [item.to_dict() for item in self.global_fields],
            "reusable_fields": [item.to_dict() for item in self.reusable_fields],
            "global_values": dict(self.global_values),
            "hidden_default_field_ids": list(self.hidden_default_field_ids),
        }


class ProjectDataStore:
    def __init__(self, project: Union[str, Path]) -> None:
        path = Path(project).expanduser()
        self.path = (path.parent if path.suffix.lower() in (".kicad_pro", ".kicad_pcb") else path) / PROJECT_DATA_FILENAME

    def fingerprint(self) -> Optional[str]:
        """Return a content fingerprint, or None when no ordinary record exists."""
        if self.path.is_symlink():
            raise ProjectDataRecoveryError("Project Data record is a symlink; refusing to follow it")
        if not self.path.is_file():
            return None
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def load(self) -> ProjectData:
        return self.read_record(self.path) if self.path.is_file() else self._missing_record()

    @staticmethod
    def read_record(path: Union[str, Path]) -> ProjectData:
        path = Path(path)
        if path.is_symlink():
            raise ProjectDataRecoveryError("Project Data record is a symlink; refusing to follow it")
        if not path.is_file():
            raise ProjectDataRecoveryError("Project Data record does not exist")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("Project Data record must be an object")
            return ProjectData.from_dict(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProjectDataRecoveryError("Could not read {}: {}".format(path.name, error)) from error

    @staticmethod
    def _missing_record() -> ProjectData:
        return ProjectData.empty()

    def backup_corrupt_record(self) -> Path:
        """Copy an unreadable record aside before the user creates a new one."""
        if self.path.is_symlink() or not self.path.is_file():
            raise ProjectDataRecoveryError("There is no regular Project Data record to back up")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = self.path.with_name("kobee-project.corrupt-{}.json".format(stamp))
        suffix = 1
        while destination.exists():
            destination = self.path.with_name("kobee-project.corrupt-{}-{}.json".format(stamp, suffix)); suffix += 1
        shutil.copy2(str(self.path), str(destination))
        return destination

    def remove_corrupt_record_after_backup(self, backup_path: Union[str, Path]) -> None:
        """Remove only the original regular file after a verified backup copy."""
        backup_path = Path(backup_path)
        if not backup_path.is_file() or self.path.is_symlink() or not self.path.is_file():
            raise ProjectDataRecoveryError("Cannot replace the unreadable record safely")
        self.path.unlink()

    def save(self, project_data: ProjectData, *, expected_fingerprint: Optional[str] = None) -> str:
        if not isinstance(project_data, ProjectData):
            raise TypeError("Expected ProjectData")
        actual = self.fingerprint()
        if actual is not None:
            # Never let a caller replace a malformed record merely because it
            # happened to have a matching fingerprint. Recovery must back it
            # up explicitly first.
            self.load()
        if actual != expected_fingerprint:
            raise ProjectDataConflictError(
                "Project Data changed, was deleted, or was replaced outside Kobee. Reload it before saving."
            )
        _atomic_json(self.path, project_data.to_dict())
        return self.fingerprint() or ""


class ProjectDataCatalogStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else user_data_root()
        self.path = self.root / "project-data" / "v1" / "catalog.json"

    def load(self) -> ProjectDataCatalog:
        if self.path.is_symlink():
            raise ProjectDataRecoveryError("Project Data catalog must be a regular file, not a symlink")
        if not self.path.exists():
            return ProjectDataCatalog.empty()
        if not self.path.is_file():
            raise ProjectDataRecoveryError("Project Data catalog path is not a regular file")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("Project Data catalog must be an object")
            return ProjectDataCatalog.from_dict(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProjectDataRecoveryError(
                "Project Data catalog could not be read safely: {}".format(error)
            ) from error

    def save(self, catalog: ProjectDataCatalog) -> None:
        if not isinstance(catalog, ProjectDataCatalog):
            raise TypeError("Expected ProjectDataCatalog")
        # A corrupt catalog is meaningful user data.  Require Data Health to
        # back it up and an explicit repair before it can be replaced.
        if self.path.exists() or self.path.is_symlink():
            self.load()
        _atomic_json(self.path, catalog.to_dict())


def fields_for(scope: str, project_data: ProjectData, catalog: ProjectDataCatalog, *, include_hidden: bool = False) -> Tuple[FieldDefinition, ...]:
    if scope not in FIELD_SCOPES:
        raise ValueError("Unknown field scope")
    result = []
    if scope in ("project", "revision"):
        for field in DEFAULT_FIELDS:
            if field.scope == scope and (include_hidden or field.field_id not in catalog.hidden_default_field_ids):
                result.append(field)
        result.extend(
            item for item in catalog.reusable_fields
            if item.scope == scope and item.field_id not in project_data.excluded_reusable_field_ids
        )
        result.extend(project_data.local_project_fields if scope == "project" else project_data.local_revision_fields)
    else:
        result.extend(
            item for item in GLOBAL_DEFAULT_FIELDS
            if include_hidden or item.field_id not in catalog.hidden_default_field_ids
        )
        result.extend(catalog.global_fields)
    keys = set(); unique = []
    for field in result:
        if field.key not in keys:
            keys.add(field.key); unique.append(field)
    return tuple(unique)


def generated_variables(project_data: ProjectData, catalog: ProjectDataCatalog) -> Dict[str, str]:
    variables: Dict[str, str] = {}
    for field in fields_for("global", project_data, catalog, include_hidden=True):
        value = catalog.global_values.get(field.field_id, field.default_value)
        variables["KOBEE_GLOBAL_" + field.key] = field.format_value(value)
    for field in fields_for("project", project_data, catalog, include_hidden=True):
        value = project_data.project_values.get(field.field_id, field.default_value)
        variables["KOBEE_PROJECT_" + field.key] = field.format_value(value)
    active = project_data.active_revision()
    if active is not None:
        for field in fields_for("revision", project_data, catalog, include_hidden=True):
            value = active.values.get(field.field_id, field.default_value)
            name = _CORE_REVISION_VARIABLES.get(field.key, "KOBEE_REVISION_" + field.key)
            variables[name] = field.format_value(value)
    return variables


def merge_kicad_variables(existing: Mapping[str, Any], generated: Mapping[str, Any], managed_names: Sequence[str]) -> Tuple[Dict[str, str], Tuple[str, ...]]:
    """Merge generated values without changing unowned KiCad text variables."""
    merged = {str(key): str(value) for key, value in dict(existing).items()}
    for name in managed_names:
        merged.pop(str(name), None)
    generated_copy = {str(key): str(value) for key, value in dict(generated).items()}
    merged.update(generated_copy)
    return merged, tuple(sorted(generated_copy))


def adopt_kicad_variables(existing: Mapping[str, Any], catalog: ProjectDataCatalog) -> Tuple[ProjectData, ProjectDataCatalog]:
    """Adopt recognisable legacy ``KOBEE_*`` values without touching KiCad.

    Unknown names deliberately remain external.  This makes first-use adoption
    safe for teams that used the namespace before Project Data existed.
    """
    project_values: Dict[str, Any] = {}
    revision_values: Dict[str, Any] = {}
    local_project = []; local_revision = []; global_fields = list(catalog.global_fields)
    global_values = dict(catalog.global_values); managed = []
    defaults = {field.key: field for field in DEFAULT_FIELDS}
    core_names = {name: key for key, name in _CORE_REVISION_VARIABLES.items()}

    def custom(scope: str, key: str, bucket: list) -> FieldDefinition:
        definition = FieldDefinition("custom_" + uuid.uuid4().hex, key.replace("_", " ").title(), key, scope)
        bucket.append(definition)
        return definition

    for raw_name, raw_value in dict(existing).items():
        name, value = str(raw_name), str(raw_value)
        if name.startswith("KOBEE_GLOBAL_"):
            key = name[len("KOBEE_GLOBAL_"):]
            if not _KEY.fullmatch(key):
                continue
            field = defaults.get(key)
            if field is None or field.scope != "global":
                field = next((item for item in global_fields if item.key == key), None) or custom("global", key, global_fields)
            global_values[field.field_id] = value; managed.append(name)
        elif name.startswith("KOBEE_PROJECT_"):
            key = name[len("KOBEE_PROJECT_"):]
            if not _KEY.fullmatch(key):
                continue
            field = defaults.get(key)
            if field is None or field.scope != "project":
                field = custom("project", key, local_project)
            project_values[field.field_id] = value; managed.append(name)
        elif name in core_names:
            field = defaults[core_names[name]]
            revision_values[field.field_id] = value; managed.append(name)
        elif name.startswith("KOBEE_REVISION_"):
            key = name[len("KOBEE_REVISION_"):]
            if not _KEY.fullmatch(key):
                continue
            field = custom("revision", key, local_revision)
            revision_values[field.field_id] = value; managed.append(name)
    return (
        ProjectData(project_values=project_values, local_project_fields=tuple(local_project), local_revision_fields=tuple(local_revision), revision_draft=revision_values, managed_variable_names=tuple(managed)),
        ProjectDataCatalog(global_fields=tuple(global_fields), reusable_fields=catalog.reusable_fields, global_values=global_values, hidden_default_field_ids=catalog.hidden_default_field_ids),
    )

"""wx controls for Kobee Project Data, kept separate from artwork pages."""

from __future__ import annotations

import re
import uuid
from datetime import date
from dataclasses import replace

import wx

from ..core.project_data import (
    DEFAULT_FIELDS,
    FIELD_TYPES,
    FieldDefinition,
    ProjectData,
    ProjectDataCatalog,
    ProjectDataConflictError,
    ProjectDataRecoveryError,
    adopt_kicad_variables,
    fields_for,
    generated_variables,
    merge_kicad_variables,
)
from .themed_controls import ThemedActionButton, ThemedChoice, ThemedListBox
from .theme import apply_native_theme, is_dark_mode


def _theme_rebuilt_controls(page):
    """Reapply colours after replacing native fields, including on Cocoa."""
    dark = is_dark_mode(wx)
    palette = {
        "surface": wx.Colour(28, 27, 25) if dark else wx.Colour(238, 238, 235),
        "active": wx.Colour(71, 66, 58) if dark else wx.Colour(255, 255, 253),
        "text": wx.Colour(245, 242, 236) if dark else wx.Colour(34, 33, 30),
    }
    page.SetBackgroundColour(palette["surface"])
    page.SetForegroundColour(palette["text"])
    apply_native_theme(page, wx, palette)
    page.Refresh(False)


def _field_value(control, field):
    if field.field_type == "checkbox":
        return control.GetValue()
    return control.GetStringSelection() if field.field_type == "choice" else control.GetValue()


def _control(parent, field, value):
    if field.field_type == "checkbox":
        control = wx.CheckBox(parent, label="Enabled")
        control.SetValue(bool(value))
        return control
    if field.field_type == "choice":
        control = ThemedChoice(parent, choices=field.choices)
        control.SetStringSelection(str(value))
        return control
    style = wx.TE_MULTILINE if field.field_type == "multiline" else wx.TE_PROCESS_ENTER
    control = wx.TextCtrl(parent, value=str(value), style=style)
    if field.field_type == "multiline":
        control.SetMinSize(wx.Size(-1, 70))
    return control


class FieldDefinitionDialog(wx.Dialog):
    """Small shared editor for local, reusable, and global field definitions."""

    def __init__(self, parent, scope, *, reusable=False, title="Add custom field"):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.scope = scope
        self.reusable = reusable
        root = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 8, 10); grid.AddGrowableCol(1)
        root.Add(grid, 1, wx.EXPAND | wx.ALL, 14)
        grid.Add(wx.StaticText(self, label="Label"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.label = wx.TextCtrl(self); grid.Add(self.label, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="KiCad key"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.key = wx.TextCtrl(self); grid.Add(self.key, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Type"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.field_type = wx.Choice(self, choices=FIELD_TYPES); self.field_type.SetStringSelection("text")
        grid.Add(self.field_type, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Choices"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.choices = wx.TextCtrl(self); self.choices.SetHint("Comma-separated; only for choice fields")
        grid.Add(self.choices, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Default value"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.default_value = wx.TextCtrl(self); grid.Add(self.default_value, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Help text"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.help_text = wx.TextCtrl(self); grid.Add(self.help_text, 1, wx.EXPAND)
        note = wx.StaticText(self, label="Reusable fields automatically appear in every project. Values remain local to each project.")
        note.Wrap(420); root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL); root.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(root); self.SetMinSize(wx.Size(440, -1))
        _theme_rebuilt_controls(self)
        self._key_touched = False
        self.label.Bind(wx.EVT_TEXT, self._suggest_key)
        self.key.Bind(wx.EVT_TEXT, self._on_key_changed)

    def _on_key_changed(self, event):
        self._key_touched = True
        event.Skip()

    def _suggest_key(self, event):
        if not self._key_touched:
            self.key.ChangeValue(re.sub(r"[^A-Z0-9]+", "_", self.label.GetValue().upper()).strip("_")[:64])
        event.Skip()

    def definition(self):
        field_type = self.field_type.GetStringSelection()
        choices = tuple(part.strip() for part in self.choices.GetValue().split(",") if part.strip())
        default_value = self.default_value.GetValue()
        if field_type == "checkbox":
            default_value = default_value.strip().casefold() in ("1", "true", "yes", "on")
        return FieldDefinition(
            "custom_" + uuid.uuid4().hex, self.label.GetValue(), self.key.GetValue(), self.scope,
            field_type, self.help_text.GetValue(), choices, default_value, False,
        )


class ProjectDataPage(wx.ScrolledWindow):
    """A non-artwork main page backed by the Project Data core model."""

    family = "project_data"

    def __init__(self, parent, editor):
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL | wx.BORDER_NONE)
        self.editor = editor
        self.SetScrollRate(0, 12)
        self.root = wx.BoxSizer(wx.VERTICAL); self.SetSizer(self.root)
        self.project_data = ProjectData.empty(); self.catalog = ProjectDataCatalog.empty()
        self.controls = {}; self.history = None; self.status = None; self._adoption_checked = False; self._dirty = False
        self.reload(editor.project_data, editor.project_data_catalog)

    def set_measurement_unit(self, unit):
        return None

    def _schedule_layout(self, **kwargs):
        self.FitInside(); self.Layout()

    def reload(self, project_data, catalog):
        self.project_data, self.catalog = project_data, catalog
        self.root.Clear(True); self.controls = {}
        self._dirty = False
        heading = wx.StaticText(self, label="Project Data")
        font = heading.GetFont().Bold(); font.SetPointSize(font.GetPointSize() + 4); heading.SetFont(font)
        self.root.Add(heading, 0, wx.ALL, 14)
        detail = wx.StaticText(self, label="Store project metadata and revision checkpoints, then explicitly sync their ${KOBEE_*} values to KiCad.")
        detail.Wrap(700); self.root.Add(detail, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        if self.editor.project_path is None:
            warning = wx.StaticText(self, label="Save the active board as a KiCad project before using Project Data.")
            self.root.Add(warning, 0, wx.ALL, 14); self._finish_rebuild(); return
        if self.editor.project_data_recovery_error:
            warning = wx.StaticText(
                self,
                label="Kobee could not safely read {}. No data will be overwritten until you explicitly back it up and start a new record.\n\n{}".format(
                    self.editor.project_data_store.path, self.editor.project_data_recovery_error,
                ),
            )
            warning.Wrap(720); self.root.Add(warning, 0, wx.ALL, 14)
            self.root.Add(ThemedActionButton(self, "Back up unreadable record and start new…", self._recover_bad_record, primary=True), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
            self._finish_rebuild(); return
        record = "Record: {}".format(self.editor.project_data_store.path)
        if self.project_data.sync_pending:
            record += "  •  KiCad sync pending — retry Sync to KiCad"
        elif self.project_data.last_synced_at:
            record += "  •  Last synced {}".format(self.project_data.last_synced_at)
        else:
            record += "  •  Not yet synced to KiCad"
        self.record_status = wx.StaticText(self, label=record)
        self.root.Add(self.record_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.root.Add(ThemedActionButton(self, "How Project Data works", self._show_help), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        if not self.editor.project_data_record_exists:
            self.root.Add(ThemedActionButton(self, "Import an existing Project Data record…", self._import_record), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self._field_section("Project details", "project", self.project_data.project_values)
        self._field_section("Revision draft", "revision", self.project_data.revision_draft)
        self._history_section()
        self._variables_section()
        self.status = wx.StaticText(self, label="Changes are saved only when you choose Save or Sync.")
        self.root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self._finish_rebuild()

    def _finish_rebuild(self):
        _theme_rebuilt_controls(self)
        self.FitInside()

    def maybe_offer_adoption(self):
        if not self or not self.editor.accepts_background_results():
            return
        if self._adoption_checked or self.editor.project_data_record_exists or self.editor.project_path is None:
            return
        self._adoption_checked = True
        variables = self.editor._file_text_variables()
        if not any(str(name).startswith("KOBEE_") for name in variables):
            return
        if wx.MessageBox(
            "This project has existing KOBEE_* KiCad variables but no kobee-project.json. Import recognised values into Project Data?",
            "Adopt existing Kobee variables", wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        try:
            project_data, catalog = adopt_kicad_variables(variables, self.catalog)
            self.editor.project_data_catalog_store.save(catalog)
            self.editor.project_data_catalog = catalog
            self.editor.save_project_data(project_data)
            self.editor.project_data_record_exists = True
            self.reload(project_data, catalog)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, TypeError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not adopt variables", wx.OK | wx.ICON_ERROR, self)

    def _field_section(self, title, scope, values):
        box = wx.StaticBoxSizer(wx.StaticBox(self, label=title), wx.VERTICAL)
        parent = box.GetStaticBox()
        grid = wx.FlexGridSizer(0, 2, 7, 10); grid.AddGrowableCol(1)
        for field in fields_for(scope, self.project_data, self.catalog):
            grid.Add(wx.StaticText(parent, label=field.label), 0, wx.ALIGN_CENTER_VERTICAL)
            value = values.get(field.field_id, field.default_value)
            if scope == "revision" and field.field_id == "default_issue_date" and not value:
                value = date.today().isoformat()
            control = _control(parent, field, value)
            if field.help_text: control.SetToolTip(field.help_text)
            for event_type in (wx.EVT_TEXT, wx.EVT_CHOICE, wx.EVT_CHECKBOX):
                try:
                    control.Bind(event_type, self._mark_dirty)
                except Exception:
                    pass
            grid.Add(control, 1, wx.EXPAND); self.controls[(scope, field.field_id)] = (field, control)
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(ThemedActionButton(parent, "Add custom field…", lambda scope=scope: self._add_custom(scope)), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Save local field as reusable…", lambda scope=scope: self._save_reusable(scope)), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Remove reusable field…", lambda scope=scope: self._remove_reusable(scope)), 0)
        box.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.root.Add(box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

    def _history_section(self):
        box = wx.StaticBoxSizer(wx.StaticBox(self, label="Revision history"), wx.VERTICAL)
        parent = box.GetStaticBox()
        entries = []
        for checkpoint in self.project_data.revisions:
            revision = checkpoint.values.get("default_revision", "Untitled revision")
            status = checkpoint.values.get("default_status", "")
            marker = "  • active" if checkpoint.revision_id == self.project_data.active_revision_id else ""
            entries.append("{}  —  {} {}{}".format(checkpoint.created_at, revision, status, marker))
        self.history = ThemedListBox(parent, choices=entries); self.history.SetMinSize(wx.Size(-1, 100))
        box.Add(self.history, 1, wx.EXPAND | wx.ALL, 10)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(ThemedActionButton(parent, "View selected details", self._view_selected), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Restore selected to draft", self._restore_selected), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Delete selected…", self._delete_selected), 0)
        box.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.root.Add(box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

    def _variables_section(self):
        box = wx.StaticBoxSizer(wx.StaticBox(self, label="KiCad variables"), wx.VERTICAL)
        parent = box.GetStaticBox()
        variables = generated_variables(self.project_data, self.catalog)
        self.variable_list = ThemedListBox(parent, choices=tuple("${%s}  →  %s" % item for item in sorted(variables.items())))
        self.variable_list.SetMinSize(wx.Size(-1, 110)); box.Add(self.variable_list, 1, wx.EXPAND | wx.ALL, 10)
        note = wx.StaticText(parent, label="Only these names are updated by Sync. Other KiCad text variables and native title-block fields are preserved.")
        note.Wrap(700); box.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(ThemedActionButton(parent, "Copy selected token", self._copy_token), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Preview KiCad changes", self._preview_sync), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Save project details", self._save), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Sync to KiCad", lambda: self.editor.sync_project_data(False), primary=True), 0, wx.RIGHT, 7)
        actions.Add(ThemedActionButton(parent, "Create checkpoint & sync", lambda: self.editor.sync_project_data(True), primary=True), 0)
        box.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.root.Add(box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

    def collect(self, checkpoint=False):
        project_values = dict(self.project_data.project_values); revision_draft = dict(self.project_data.revision_draft)
        for (scope, field_id), (field, control) in self.controls.items():
            target = project_values if scope == "project" else revision_draft
            target[field_id] = field.validate_value(_field_value(control, field))
        result = ProjectData(
            project_values=project_values, local_project_fields=self.project_data.local_project_fields,
            local_revision_fields=self.project_data.local_revision_fields,
            excluded_reusable_field_ids=self.project_data.excluded_reusable_field_ids,
            revision_draft=revision_draft, revisions=self.project_data.revisions,
            active_revision_id=self.project_data.active_revision_id,
            managed_variable_names=self.project_data.managed_variable_names,
            sync_pending=self.project_data.sync_pending,
            last_synced_at=self.project_data.last_synced_at,
        )
        return result.with_checkpoint(revision_draft) if checkpoint else result

    def _save(self, event=None):
        try:
            self.editor.save_project_data(self.collect())
            self.reload(self.editor.project_data, self.catalog)
            self.status.SetLabel("Project details saved. Sync to KiCad to update ${KOBEE_*} values.")
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not save Project Data", wx.OK | wx.ICON_ERROR, self)

    def _add_custom(self, scope):
        dialog = FieldDefinitionDialog(self, scope)
        try:
            if dialog.ShowModal() != wx.ID_OK: return
            definition = dialog.definition()
            current = self.collect()
            fields = current.local_project_fields if scope == "project" else current.local_revision_fields
            if any(item.key == definition.key for item in fields_for(scope, current, self.catalog, include_hidden=True)):
                raise ValueError("A {} field already uses {}".format(scope, definition.key))
            if scope == "project":
                current = ProjectData(**{**current.__dict__, "local_project_fields": fields + (definition,)})
            else:
                current = ProjectData(**{**current.__dict__, "local_revision_fields": fields + (definition,)})
            self.editor.save_project_data(current); self.reload(current, self.catalog)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (ValueError, OSError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not add field", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _remove_reusable(self, scope):
        choices = [item for item in self.catalog.reusable_fields if item.scope == scope and item.field_id not in self.project_data.excluded_reusable_field_ids]
        if not choices: return
        picker = wx.SingleChoiceDialog(self, "Select a reusable field to remove from this project", "Remove reusable field", [item.label for item in choices])
        try:
            if picker.ShowModal() != wx.ID_OK: return
            selected = choices[picker.GetSelection()]
            current = ProjectData(**{**self.collect().__dict__, "excluded_reusable_field_ids": self.project_data.excluded_reusable_field_ids + (selected.field_id,)})
            self.editor.save_project_data(current); self.reload(current, self.catalog)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not remove reusable field", wx.OK | wx.ICON_ERROR, self)
        finally:
            picker.Destroy()

    def _save_reusable(self, scope):
        local = self.project_data.local_project_fields if scope == "project" else self.project_data.local_revision_fields
        if not local:
            wx.MessageBox("Add a local custom field first.", "Reusable field", wx.OK | wx.ICON_INFORMATION, self)
            return
        picker = wx.SingleChoiceDialog(self, "Select a local field to reuse in every project", "Save reusable field", [item.label for item in local])
        try:
            if picker.ShowModal() != wx.ID_OK: return
            field = local[picker.GetSelection()]
            if any(item.key == field.key and item.scope == field.scope for item in self.catalog.reusable_fields):
                raise ValueError("A reusable {} field already uses {}".format(scope, field.key))
            catalog = ProjectDataCatalog(
                global_fields=self.catalog.global_fields,
                reusable_fields=self.catalog.reusable_fields + (field,),
                global_values=self.catalog.global_values,
                hidden_default_field_ids=self.catalog.hidden_default_field_ids,
            )
            current = self.collect()
            if scope == "project":
                current = ProjectData(**{**current.__dict__, "local_project_fields": tuple(item for item in local if item.field_id != field.field_id)})
            else:
                current = ProjectData(**{**current.__dict__, "local_revision_fields": tuple(item for item in local if item.field_id != field.field_id)})
            self.editor.project_data_catalog_store.save(catalog)
            self.editor.project_data_catalog = catalog
            self.editor.save_project_data(current)
            self.reload(current, catalog)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not save reusable field", wx.OK | wx.ICON_ERROR, self)
        finally:
            picker.Destroy()

    def _selected_checkpoint(self):
        index = self.history.GetSelection()
        return self.project_data.revisions[index] if 0 <= index < len(self.project_data.revisions) else None

    def _restore_selected(self, event=None):
        checkpoint = self._selected_checkpoint()
        if checkpoint is None: return
        current = self.project_data.restore_to_draft(checkpoint.revision_id)
        try:
            self.editor.save_project_data(current); self.reload(current, self.catalog)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not restore revision", wx.OK | wx.ICON_ERROR, self)

    def _view_selected(self, event=None):
        checkpoint = self._selected_checkpoint()
        if checkpoint is None:
            return
        fields = {field.field_id: field for field in fields_for("revision", self.project_data, self.catalog, include_hidden=True)}
        lines = ["Created: {}".format(checkpoint.created_at), ""]
        for field_id, value in checkpoint.values.items():
            field = fields.get(field_id)
            label = field.label if field is not None else field_id
            display = field.format_value(value) if field is not None else str(value)
            lines.append("{}: {}".format(label, display))
        wx.MessageBox("\n".join(lines), "Revision checkpoint details", wx.OK | wx.ICON_INFORMATION, self)

    def _delete_selected(self, event=None):
        checkpoint = self._selected_checkpoint()
        if checkpoint is None: return
        if wx.MessageBox("Delete this immutable revision checkpoint? This cannot be undone.", "Delete revision", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES:
            return
        try:
            current = self.project_data.delete_revision(checkpoint.revision_id)
            self.editor.save_project_data(current); self.reload(current, self.catalog)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not delete revision", wx.OK | wx.ICON_ERROR, self)

    def _copy_token(self, event=None):
        selection = self.variable_list.GetStringSelection()
        if not selection: return
        token = selection.split("  →", 1)[0]
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(token)); wx.TheClipboard.Close()

    def _preview_sync(self, event=None):
        try:
            project_data = self.collect()
            existing = self.editor._file_text_variables()
            generated = generated_variables(project_data, self.catalog)
            merged, _ = merge_kicad_variables(existing, generated, project_data.managed_variable_names)
            changes = []
            for name in sorted(set(existing) | set(merged)):
                before, after = existing.get(name), merged.get(name)
                if before == after:
                    continue
                if after is None:
                    changes.append("Remove ${}".format(name))
                elif before is None:
                    changes.append("Set ${{{}}} = {}".format(name, after))
                else:
                    changes.append("Update ${{{}}}: {} → {}".format(name, before, after))
            text = "No KiCad project-variable changes are pending." if not changes else "\n".join(changes)
            wx.MessageBox(text, "KiCad sync preview", wx.OK | wx.ICON_INFORMATION, self)
        except (ValueError, TypeError) as error:
            wx.MessageBox(str(error), "Could not preview KiCad changes", wx.OK | wx.ICON_ERROR, self)

    def _mark_dirty(self, event):
        self._dirty = True
        if self.status is not None:
            self.status.SetLabel("Unsaved changes. Save project details, or create a checkpoint and sync to KiCad.")
        event.Skip()

    def _show_help(self, event=None):
        wx.MessageBox(
            "Global fields are configured in Settings and export as ${KOBEE_GLOBAL_*}.\n\n"
            "Project fields describe this PCB and export as ${KOBEE_PROJECT_*}.\n\n"
            "A revision checkpoint permanently records the revision draft and exports ${KOBEE_REVISION}, ${KOBEE_HARDWARE_VERSION}, and related release values. Restore copies an older checkpoint into a new draft; it never changes history.\n\n"
            "Use the Variables list to copy tokens into a Kobee variable label, PCB text, schematic text, or drawing sheet.",
            "How Project Data works", wx.OK | wx.ICON_INFORMATION, self,
        )

    def _recover_bad_record(self, event=None):
        if wx.MessageBox(
            "Kobee will copy the unreadable record beside the project, then create a new empty kobee-project.json. Continue?",
            "Recover Project Data", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self,
        ) != wx.YES:
            return
        try:
            backup = self.editor.recover_project_data()
            self.reload(self.editor.project_data, self.editor.project_data_catalog)
            wx.MessageBox("The unreadable record was copied to:\n{}".format(backup), "Project Data recovered", wx.OK | wx.ICON_INFORMATION, self)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not recover Project Data", wx.OK | wx.ICON_ERROR, self)

    def _import_record(self, event=None):
        chooser = wx.FileDialog(
            self, "Import Project Data record", wildcard="Project Data JSON (kobee-project.json)|kobee-project.json|JSON files (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if chooser.ShowModal() != wx.ID_OK:
                return
            imported = self.editor.import_project_data_record(chooser.GetPath())
            self.reload(imported, self.editor.project_data_catalog)
            wx.MessageBox("Project Data was imported. Sync to KiCad when you are ready to apply its variables.", "Project Data imported", wx.OK | wx.ICON_INFORMATION, self)
        except ProjectDataConflictError:
            self.editor.resolve_project_data_conflict(self)
        except (OSError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not import Project Data", wx.OK | wx.ICON_ERROR, self)
        finally:
            chooser.Destroy()


class ProjectDataSettingsPage(wx.ScrolledWindow):
    """Global catalog and visibility controls embedded in Settings."""

    def __init__(self, parent, catalog_store):
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL | wx.BORDER_NONE)
        self.catalog_store = catalog_store
        self.catalog_error = None
        try:
            self.catalog = catalog_store.load()
        except (OSError, TypeError, ValueError, ProjectDataRecoveryError) as error:
            self.catalog = ProjectDataCatalog.empty()
            self.catalog_error = str(error)
        self.SetScrollRate(0, 12); self.root = wx.BoxSizer(wx.VERTICAL); self.SetSizer(self.root)
        self.visibility_controls = {}; self.global_controls = {}
        self._build()

    def _build(self):
        self.root.Clear(True); self.visibility_controls = {}; self.global_controls = {}
        heading = wx.StaticText(self, label="Project Data")
        font = heading.GetFont().Bold(); font.SetPointSize(font.GetPointSize() + 2); heading.SetFont(font)
        self.root.Add(heading, 0, wx.ALL, 14)
        note = wx.StaticText(self, label="Define values shared by all projects, reusable project/revision fields, and which default fields appear in Project Data.")
        note.Wrap(650); self.root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        if self.catalog_error:
            warning = wx.StaticText(
                self,
                label="The global Project Data catalog could not be read safely. It has not been changed. Use Settings → Data & backup → Data health to make a recovery copy, then repair or remove the unreadable file before editing this page.\n\n{}".format(self.catalog_error),
            )
            warning.Wrap(650)
            self.root.Add(warning, 0, wx.ALL, 14)
            _theme_rebuilt_controls(self)
            self.FitInside()
            return
        defaults = wx.StaticBoxSizer(wx.StaticBox(self, label="Default field visibility"), wx.VERTICAL)
        for field in DEFAULT_FIELDS:
            control = wx.CheckBox(defaults.GetStaticBox(), label=field.label)
            control.SetValue(field.field_id not in self.catalog.hidden_default_field_ids)
            defaults.Add(control, 0, wx.ALL, 3); self.visibility_controls[field.field_id] = control
        self.root.Add(defaults, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self._catalog_fields("Global values", "global")
        self._catalog_fields("Reusable fields", "reusable")
        _theme_rebuilt_controls(self)
        self.FitInside()

    def _catalog_fields(self, title, kind):
        box = wx.StaticBoxSizer(wx.StaticBox(self, label=title), wx.VERTICAL)
        parent = box.GetStaticBox()
        fields = fields_for("global", ProjectData.empty(), self.catalog, include_hidden=True) if kind == "global" else self.catalog.reusable_fields
        if kind == "global":
            grid = wx.FlexGridSizer(0, 2, 7, 10); grid.AddGrowableCol(1)
            for field in fields:
                grid.Add(wx.StaticText(parent, label=field.label), 0, wx.ALIGN_CENTER_VERTICAL)
                control = _control(parent, field, self.catalog.global_values.get(field.field_id, field.default_value))
                grid.Add(control, 1, wx.EXPAND); self.global_controls[field.field_id] = (field, control)
            box.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        else:
            lines = ["{} · {} · ${}".format(field.label, field.scope, field.key) for field in fields]
            self.reusable_list = ThemedListBox(parent, choices=lines); self.reusable_list.SetMinSize(wx.Size(-1, 110))
            box.Add(self.reusable_list, 1, wx.EXPAND | wx.ALL, 10)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(ThemedActionButton(parent, "Add {} field…".format("global" if kind == "global" else "reusable"), lambda kind=kind: self._add_field(kind)), 0, wx.RIGHT, 7)
        if kind == "reusable":
            actions.Add(ThemedActionButton(parent, "Delete selected…", self._delete_reusable), 0)
        box.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.root.Add(box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

    def _add_field(self, kind):
        scope = "global"
        if kind == "reusable":
            picker = wx.SingleChoiceDialog(self, "Where should this reusable field appear?", "Reusable field scope", ("Project details", "Revision draft"))
            try:
                if picker.ShowModal() != wx.ID_OK: return
                scope = "project" if picker.GetSelection() == 0 else "revision"
            finally:
                picker.Destroy()
        dialog = FieldDefinitionDialog(self, scope, reusable=kind == "reusable", title="Add {} field".format(kind))
        try:
            if dialog.ShowModal() != wx.ID_OK: return
            definition = dialog.definition()
            existing = tuple(DEFAULT_FIELDS) + self.catalog.global_fields + self.catalog.reusable_fields
            if any(field.key == definition.key and field.scope == definition.scope for field in existing):
                raise ValueError("This scope already has a field using {}".format(definition.key))
            if kind == "global":
                self.catalog = ProjectDataCatalog(
                    global_fields=self.catalog.global_fields + (definition,), reusable_fields=self.catalog.reusable_fields,
                    global_values=self.catalog.global_values, hidden_default_field_ids=self.catalog.hidden_default_field_ids,
                )
            else:
                self.catalog = ProjectDataCatalog(
                    global_fields=self.catalog.global_fields, reusable_fields=self.catalog.reusable_fields + (definition,),
                    global_values=self.catalog.global_values, hidden_default_field_ids=self.catalog.hidden_default_field_ids,
                )
            self._build()
        except ValueError as error:
            wx.MessageBox(str(error), "Could not add field", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _delete_reusable(self, event=None):
        index = self.reusable_list.GetSelection()
        if not 0 <= index < len(self.catalog.reusable_fields): return
        if wx.MessageBox("Remove this reusable field from the global catalog? Existing project data is preserved.", "Remove reusable field", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES:
            return
        fields = list(self.catalog.reusable_fields); del fields[index]
        self.catalog = ProjectDataCatalog(
            global_fields=self.catalog.global_fields, reusable_fields=tuple(fields), global_values=self.catalog.global_values,
            hidden_default_field_ids=self.catalog.hidden_default_field_ids,
        ); self._build()

    def save(self):
        if self.catalog_error:
            return
        global_values = dict(self.catalog.global_values)
        for field_id, (field, control) in self.global_controls.items():
            global_values[field_id] = field.validate_value(_field_value(control, field))
        hidden = tuple(field_id for field_id, control in self.visibility_controls.items() if not control.GetValue())
        self.catalog = ProjectDataCatalog(
            global_fields=self.catalog.global_fields, reusable_fields=self.catalog.reusable_fields,
            global_values=global_values, hidden_default_field_ids=hidden,
        )
        self.catalog_store.save(self.catalog)
        return self.catalog

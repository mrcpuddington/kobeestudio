"""Application settings, profile/default, and SVG upload management UI."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional
import zipfile

import wx

from ..core.app_preferences import AppPreferences, AppPreferencesStore
from ..core.measurement_units import MeasurementUnit
from ..core.quick_labels import QuickLabelStore
from ..core.settings_profiles import SettingsProfileStore
from ..core.svg_symbols import SvgAssetStore
from ..core.library_archive import export_library, reset_library, restore_library
from ..version import __version__
from .theme import apply_native_theme, is_dark_mode
from .themed_controls import ThemedActionButton, ThemedChoice, ThemedListBox


MODULE_LABELS = {
    "labels": "Labels",
    "pin_headers": "Header overlays",
    "component_callouts": "Component callouts",
    "component_arrays": "Component arrays",
    "machine_codes": "QR codes and barcodes",
}
MODULE_BY_LABEL = {label: module for module, label in MODULE_LABELS.items()}
SYMBOL_CATEGORIES = ("Custom", "Controls", "Direction", "Electrical", "PCB", "Safety")
SYMBOL_VARIANTS = ("default", "rounded")


class SymbolUploadDetailsDialog(wx.Dialog):
    """Collect friendly symbol metadata; filenames are never user-facing IDs."""

    def __init__(self, parent, *, title, name, category="Custom", variant="default", existing_family=False):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        root = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 10, 10)
        grid.AddGrowableCol(1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 14)
        grid.Add(wx.StaticText(self, label="Display name"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.name_ctrl = wx.TextCtrl(self, value=name)
        self.name_ctrl.Enable(not existing_family)
        grid.Add(self.name_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Category"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.category_ctrl = wx.ComboBox(self, value=category, choices=SYMBOL_CATEGORIES, style=wx.CB_DROPDOWN)
        self.category_ctrl.Enable(not existing_family)
        grid.Add(self.category_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Variant"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.variant_ctrl = wx.ComboBox(self, value=variant, choices=SYMBOL_VARIANTS, style=wx.CB_READONLY)
        grid.Add(self.variant_ctrl, 1, wx.EXPAND)
        note = wx.StaticText(
            self,
            label="Use default for the primary symbol. Add the rounded variant to the same family when it has a meaningful rounded design.",
        )
        note.Wrap(420)
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        root.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self.SetSizerAndFit(root)
        self.SetMinSize(wx.Size(440, -1))

    def values(self):
        return self.name_ctrl.GetValue(), self.category_ctrl.GetValue(), self.variant_ctrl.GetValue()


class QuickLabelDetailsDialog(wx.Dialog):
    """Create or edit a user quick label without exposing implementation IDs."""

    def __init__(self, parent, catalog, *, label=None):
        super().__init__(parent, title="Edit quick label" if label else "Add quick label", style=wx.DEFAULT_DIALOG_STYLE)
        root = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 10, 10)
        grid.AddGrowableCol(1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 14)
        grid.Add(wx.StaticText(self, label="Label text"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.text_ctrl = wx.TextCtrl(self, value=label.text if label else "")
        grid.Add(self.text_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Category"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.category_ctrl = wx.TextCtrl(self, value=label.category if label else "Custom")
        grid.Add(self.category_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Linked symbol"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._symbol_refs = [""] + ["{}@@{}".format(item.asset_id, item.variant) for item in catalog.symbols]
        symbol_choices = ["No symbol"] + [
            "{}{}".format(item.name, " — " + item.variant.replace("_", " ").title() if item.variant != "default" else "")
            for item in catalog.symbols
        ]
        self.symbol_choice = wx.Choice(self, choices=symbol_choices)
        existing_ref = "{}@@{}".format(label.symbol_id, label.symbol_variant) if label and label.symbol_id else ""
        self.symbol_choice.SetSelection(self._symbol_refs.index(existing_ref) if existing_ref in self._symbol_refs else 0)
        grid.Add(self.symbol_choice, 1, wx.EXPAND)
        note = wx.StaticText(self, label="Labels can be project-only or stored in your portable library. Bundled labels remain read-only.")
        note.Wrap(440)
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        root.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self.SetSizerAndFit(root)
        self.SetMinSize(wx.Size(460, -1))

    def values(self):
        reference = self._symbol_refs[max(0, self.symbol_choice.GetSelection())]
        if not reference:
            return self.text_ctrl.GetValue(), self.category_ctrl.GetValue(), "", "default"
        symbol_id, variant = reference.split("@@", 1)
        return self.text_ctrl.GetValue(), self.category_ctrl.GetValue(), symbol_id, variant


class SettingsDialog(wx.Dialog):
    """Manage preferences and user data without coupling it to editor layout."""

    def __init__(
        self,
        parent,
        *,
        preferences_store: AppPreferencesStore,
        profile_store: SettingsProfileStore,
        global_asset_store: SvgAssetStore,
        project_asset_store: Optional[SvgAssetStore],
        global_label_store: QuickLabelStore,
        project_label_store: Optional[QuickLabelStore],
        symbol_catalog,
        hidden_symbol_ids=(),
        hidden_label_ids=(),
        current_module: str,
        capture_settings: Callable[[], Dict],
        apply_profile: Callable[[Dict], None],
        preferences_changed: Callable[[AppPreferences], None],
    ):
        super().__init__(
            parent,
            title="Kobee Studio Settings",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=wx.Size(720, 560),
        )
        self.preferences_store = preferences_store
        self.profile_store = profile_store
        self.global_asset_store = global_asset_store
        self.project_asset_store = project_asset_store
        self.global_label_store = global_label_store
        self.project_label_store = project_label_store
        self.symbol_catalog = symbol_catalog
        self._hidden_symbol_ids = set(hidden_symbol_ids)
        self._hidden_label_ids = set(hidden_label_ids)
        self.current_module = current_module
        self.capture_settings = capture_settings
        self.apply_profile = apply_profile
        self.preferences_changed = preferences_changed
        self._profiles = ()
        self._upload_items = ()
        self._quick_labels = ()

        root = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Simplebook(self)
        self.general_page = wx.Panel(self.notebook)
        self.profile_page = wx.Panel(self.notebook)
        self.assets_page = wx.Panel(self.notebook)
        self.asset_book = wx.Simplebook(self.assets_page)
        self.upload_page = wx.Panel(self.asset_book)
        self.quick_labels_page = wx.Panel(self.asset_book)
        self.library_page = wx.Panel(self.notebook)
        self.library_book = wx.Simplebook(self.library_page)
        self.library_backup_page = wx.Panel(self.library_book)
        self.library_visibility_page = wx.Panel(self.library_book)
        self.info_page = wx.Panel(self.notebook)
        self.asset_book.AddPage(self.upload_page, "")
        self.asset_book.AddPage(self.quick_labels_page, "")
        asset_root = wx.BoxSizer(wx.VERTICAL)
        asset_tabs = wx.BoxSizer(wx.HORIZONTAL)
        self._asset_page_buttons = []
        for index, label in enumerate(("Symbols", "Quick labels")):
            button = ThemedActionButton(self.assets_page, label, lambda page=index: self._select_asset_page(page), primary=index == 0)
            self._asset_page_buttons.append(button)
            asset_tabs.Add(button, 0, wx.RIGHT, 6)
        asset_root.Add(asset_tabs, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        asset_root.Add(self.asset_book, 1, wx.EXPAND | wx.TOP, 4)
        self.assets_page.SetSizer(asset_root)
        for page in (self.library_backup_page, self.library_visibility_page):
            self.library_book.AddPage(page, "")
        library_root = wx.BoxSizer(wx.VERTICAL)
        library_tabs = wx.BoxSizer(wx.HORIZONTAL)
        self._library_page_buttons = []
        for index, label in enumerate(("Backup & reset", "Bundled visibility")):
            button = ThemedActionButton(self.library_page, label, lambda page=index: self._select_library_page(page), primary=index == 0)
            self._library_page_buttons.append(button)
            library_tabs.Add(button, 0, wx.RIGHT, 6)
        library_root.Add(library_tabs, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        library_root.Add(self.library_book, 1, wx.EXPAND | wx.TOP, 4)
        self.library_page.SetSizer(library_root)
        for page in (self.general_page, self.profile_page, self.assets_page, self.library_page, self.info_page):
            self.notebook.AddPage(page, "")
        self._page_buttons = []
        page_tabs = wx.BoxSizer(wx.HORIZONTAL)
        for index, label in enumerate(("General", "Profiles and defaults", "Uploads", "Library", "About & help")):
            button = ThemedActionButton(self, label, lambda page=index: self._select_page(page), primary=index == 0)
            self._page_buttons.append(button)
            page_tabs.Add(button, 0, wx.RIGHT, 6)
        root.Add(page_tabs, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        root.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 10)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer(1)
        buttons.Add(ThemedActionButton(self, "Cancel", lambda: self.EndModal(wx.ID_CANCEL)), 0, wx.RIGHT, 8)
        buttons.Add(ThemedActionButton(self, "Save settings", self._on_ok, primary=True), 0)
        root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(620, 460))

        self._build_general_page()
        self._build_profile_page()
        self._build_upload_page()
        self._build_quick_labels_page()
        self._build_library_page()
        self._apply_theme()
        self._select_page(0)
        self._select_asset_page(0)
        self._select_library_page(0)

    def _select_page(self, index):
        self.notebook.ChangeSelection(index)
        for button_index, button in enumerate(self._page_buttons):
            button.primary = button_index == index
            button.Refresh(False)

    def _select_asset_page(self, index):
        self.asset_book.ChangeSelection(index)
        for button_index, button in enumerate(self._asset_page_buttons):
            button.primary = button_index == index
            button.Refresh(False)

    def _select_library_page(self, index):
        self.library_book.ChangeSelection(index)
        for button_index, button in enumerate(self._library_page_buttons):
            button.primary = button_index == index
            button.Refresh(False)

    def _apply_theme(self):
        dark = is_dark_mode(wx)
        palette = {
            "window": wx.Colour(27, 26, 24) if dark else wx.Colour(239, 239, 237),
            "surface": wx.Colour(39, 37, 34) if dark else wx.Colour(248, 248, 246),
            "active": wx.Colour(71, 66, 58) if dark else wx.Colour(255, 255, 253),
            "text": wx.Colour(245, 242, 236) if dark else wx.Colour(34, 33, 30),
            "muted": wx.Colour(181, 175, 165) if dark else wx.Colour(113, 108, 100),
        }
        self.SetBackgroundColour(palette["window"])
        self.notebook.SetBackgroundColour(palette["surface"])
        for page in (self.general_page, self.profile_page, self.assets_page, self.upload_page, self.quick_labels_page, self.library_page, self.library_backup_page, self.library_visibility_page, self.info_page):
            page.SetBackgroundColour(palette["surface"])
        apply_native_theme(self, wx, palette)
        for control in (getattr(self, "profile_list", None), getattr(self, "upload_list", None), getattr(self, "quick_label_list", None), getattr(self, "visibility_list", None)):
            if control is None:
                continue
            try:
                control.SetOwnBackgroundColour(palette["active"])
                control.SetBackgroundColour(palette["active"])
                control.SetOwnForegroundColour(palette["text"])
                control.SetForegroundColour(palette["text"])
            except AttributeError:
                pass

    @staticmethod
    def _heading(parent, text):
        heading = wx.StaticText(parent, label=text)
        font = heading.GetFont().Bold()
        font.SetPointSize(font.GetPointSize() + 2)
        heading.SetFont(font)
        return heading

    def _build_general_page(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.general_page.SetSizer(root)
        root.Add(self._heading(self.general_page, "Application preferences"), 0, wx.ALL, 14)
        helper = wx.StaticText(
            self.general_page,
            label="Appearance applies when the editor is next opened. Dimensions remain stored in millimetres.",
        )
        helper.Wrap(580)
        root.Add(helper, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        grid = wx.FlexGridSizer(0, 2, 10, 12)
        grid.AddGrowableCol(1)
        root.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)

        preferences = self.preferences_store.load()
        grid.Add(wx.StaticText(self.general_page, label="Appearance"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.appearance_choice = ThemedChoice(
            self.general_page,
            choices=("Follow system", "Light", "Dark"),
        )
        self.appearance_choice.SetStringSelection(
            {"system": "Follow system", "light": "Light", "dark": "Dark"}[preferences.appearance]
        )
        grid.Add(self.appearance_choice, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self.general_page, label="Measurement display"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.unit_choice = ThemedChoice(self.general_page, choices=("Millimetres (mm)", "Mils (mil)"))
        self.unit_choice.SetStringSelection(
            "Mils (mil)" if preferences.measurement_unit is MeasurementUnit.MILS else "Millimetres (mm)"
        )
        grid.Add(self.unit_choice, 1, wx.EXPAND)

    def _build_profile_page(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.profile_page.SetSizer(root)
        root.Add(self._heading(self.profile_page, "Module profiles"), 0, wx.ALL, 14)
        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(wx.StaticText(self.profile_page, label="Module"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.module_choice = ThemedChoice(self.profile_page, choices=tuple(MODULE_BY_LABEL))
        self.module_choice.SetStringSelection(MODULE_LABELS.get(self.current_module, "Labels"))
        self.module_choice.Bind(wx.EVT_CHOICE, self._on_profile_module_changed)
        top.Add(self.module_choice, 1)
        root.Add(top, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        self.profile_list = ThemedListBox(self.profile_page)
        root.Add(self.profile_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
            ("Save current as…", self._save_profile),
            ("Update selected", self._update_profile),
            ("Apply", self._apply_selected_profile),
            ("Set default", self._set_default_profile),
            ("Clear default", self._clear_default_profile),
            ("Delete", self._delete_profile),
        ):
            button = ThemedActionButton(self.profile_page, label, lambda handler=handler: handler(None))
            actions.Add(button, 0, wx.RIGHT, 6)
        root.Add(actions, 0, wx.ALL, 14)
        note = wx.StaticText(
            self.profile_page,
            label="Defaults apply to new artwork only. Settings embedded in existing artwork always win.",
        )
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self._refresh_profiles()

    def _profile_module(self) -> str:
        return MODULE_BY_LABEL[self.module_choice.GetStringSelection()]

    def _selected_profile(self):
        selection = self.profile_list.GetSelection()
        return self._profiles[selection] if 0 <= selection < len(self._profiles) else None

    def _refresh_profiles(self, select_id=None):
        if not hasattr(self, "profile_list"):
            return
        module = self._profile_module()
        default_id = self.profile_store.default_id(module)
        self._profiles = self.profile_store.list(module)
        self.profile_list.Set(
            tuple(
                "{}{}".format(profile.name, "  [default]" if profile.profile_id == default_id else "")
                for profile in self._profiles
            )
        )
        for index, profile in enumerate(self._profiles):
            if profile.profile_id == select_id:
                self.profile_list.SetSelection(index)
                break

    def _on_profile_module_changed(self, event):
        self._refresh_profiles()
        event.Skip()

    def _save_profile(self, event):
        module = self._profile_module()
        if module != self.current_module:
            wx.MessageBox(
                "Switch the editor to {} before saving its current settings.".format(MODULE_LABELS[module]),
                "Kobee Studio Profiles",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        prompt = wx.TextEntryDialog(self, "Profile name", "Save current settings as a profile")
        try:
            if prompt.ShowModal() != wx.ID_OK:
                return
            profile = self.profile_store.save(module, prompt.GetValue(), self.capture_settings())
            self._refresh_profiles(profile.profile_id)
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not save profile", wx.OK | wx.ICON_ERROR, self)
        finally:
            prompt.Destroy()

    def _update_profile(self, event):
        profile = self._selected_profile()
        if profile is None:
            return
        if profile.module != self.current_module:
            wx.MessageBox("The selected profile is for a different editor module.", "Kobee Studio Profiles", wx.OK | wx.ICON_INFORMATION, self)
            return
        try:
            updated = self.profile_store.save(
                profile.module,
                profile.name,
                self.capture_settings(),
                profile_id=profile.profile_id,
            )
            self._refresh_profiles(updated.profile_id)
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not update profile", wx.OK | wx.ICON_ERROR, self)

    def _apply_selected_profile(self, event):
        profile = self._selected_profile()
        if profile is not None:
            self.apply_profile(dict(profile.settings))
            self.current_module = profile.module

    def _set_default_profile(self, event):
        profile = self._selected_profile()
        if profile is None:
            return
        try:
            self.profile_store.set_default(profile.module, profile.profile_id)
            self._refresh_profiles(profile.profile_id)
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not set default", wx.OK | wx.ICON_ERROR, self)

    def _clear_default_profile(self, event):
        try:
            self.profile_store.set_default(self._profile_module(), None)
            self._refresh_profiles()
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not clear default", wx.OK | wx.ICON_ERROR, self)

    def _delete_profile(self, event):
        profile = self._selected_profile()
        if profile is None:
            return
        answer = wx.MessageBox(
            "Delete the profile “{}”?".format(profile.name),
            "Delete profile",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            self,
        )
        if answer != wx.YES:
            return
        try:
            self.profile_store.delete(profile.module, profile.profile_id)
            self._refresh_profiles()
        except (OSError, ValueError, LookupError) as error:
            wx.MessageBox(str(error), "Could not delete profile", wx.OK | wx.ICON_ERROR, self)

    def _build_upload_page(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.upload_page.SetSizer(root)
        root.Add(self._heading(self.upload_page, "Custom SVG assets"), 0, wx.ALL, 14)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        filters.Add(wx.StaticText(self.upload_page, label="Scope"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        scopes = ["My library"]
        if self.project_asset_store is not None:
            scopes.append("This project")
        self.scope_choice = ThemedChoice(self.upload_page, choices=scopes)
        self.scope_choice.SetMinSize(wx.Size(142, 30))
        self.scope_choice.SetSelection(0)
        self.scope_choice.Bind(wx.EVT_CHOICE, self._on_upload_filter_changed)
        filters.Add(self.scope_choice, 0, wx.RIGHT, 14)
        filters.Add(wx.StaticText(self.upload_page, label="Type"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        namespace_choices = ("Symbols", "Graphics")
        self.namespace_choice = ThemedChoice(self.upload_page, choices=namespace_choices)
        self.namespace_choice.SetSelection(0)
        self.namespace_choice.Bind(wx.EVT_CHOICE, self._on_upload_filter_changed)
        filters.Add(self.namespace_choice, 0)
        root.Add(filters, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        self.upload_list = ThemedListBox(self.upload_page)
        root.Add(self.upload_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        upload = ThemedActionButton(self.upload_page, "Upload SVG…", lambda: self._upload_svg(None))
        self.add_variant_button = ThemedActionButton(self.upload_page, "Add variant…", lambda: self._upload_variant(None))
        delete = ThemedActionButton(self.upload_page, "Delete selected", lambda: self._delete_upload(None))
        actions.Add(upload, 0, wx.RIGHT, 6)
        actions.Add(self.add_variant_button, 0, wx.RIGHT, 6)
        actions.Add(delete, 0)
        root.Add(actions, 0, wx.ALL, 14)
        if self.project_asset_store is None:
            root.Add(
                wx.StaticText(self.upload_page, label="Save the KiCad board to enable project-only uploads."),
                0,
                wx.LEFT | wx.RIGHT | wx.BOTTOM,
                14,
            )
        self._refresh_uploads()

    def _build_quick_labels_page(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.quick_labels_page.SetSizer(root)
        root.Add(self._heading(self.quick_labels_page, "Quick labels"), 0, wx.ALL, 14)
        helper = wx.StaticText(self.quick_labels_page, label="Create personal or project labels here. Bundled labels are protected, so app updates never overwrite your changes.")
        helper.Wrap(630)
        root.Add(helper, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        scope_row = wx.BoxSizer(wx.HORIZONTAL)
        scope_row.Add(wx.StaticText(self.quick_labels_page, label="Save in"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        scopes = ["My library"] + (["This project"] if self.project_label_store is not None else [])
        self.label_scope_choice = ThemedChoice(self.quick_labels_page, choices=scopes)
        self.label_scope_choice.Bind(wx.EVT_CHOICE, lambda event: self._refresh_quick_labels())
        scope_row.Add(self.label_scope_choice, 0)
        root.Add(scope_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.quick_label_list = ThemedListBox(self.quick_labels_page)
        root.Add(self.quick_label_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for title, handler in (("Add quick label…", self._add_quick_label), ("Edit selected…", self._edit_quick_label), ("Delete selected", self._delete_quick_label)):
            button = ThemedActionButton(self.quick_labels_page, title, lambda handler=handler: handler(None))
            actions.Add(button, 0, wx.RIGHT, 6)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.TOP, 14)
        self._refresh_quick_labels()

    def _label_store(self) -> QuickLabelStore:
        if self.label_scope_choice.GetStringSelection() == "This project" and self.project_label_store is not None:
            return self.project_label_store
        return self.global_label_store

    def _refresh_quick_labels(self, select_id=None):
        if not hasattr(self, "quick_label_list"):
            return
        self._quick_labels = self._label_store().list()
        self.quick_label_list.Set(
            tuple("{}  ·  {}{}".format(label.text, label.category, "  ·  " + label.symbol_id if label.symbol_id else "") for label in self._quick_labels)
        )
        for row, label in enumerate(self._quick_labels):
            if label.preset_id == select_id:
                self.quick_label_list.SetSelection(row)

    def _selected_quick_label(self):
        selection = self.quick_label_list.GetSelection()
        return self._quick_labels[selection] if 0 <= selection < len(self._quick_labels) else None

    def _edit_label_dialog(self, label=None):
        dialog = QuickLabelDetailsDialog(self, self.symbol_catalog, label=label)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            text, category, symbol_id, variant = dialog.values()
            saved = self._label_store().save(text, category, symbol_id, variant, label.preset_id if label else None)
            self._refresh_quick_labels(saved.preset_id)
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not save quick label", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _add_quick_label(self, event):
        self._edit_label_dialog()

    def _edit_quick_label(self, event):
        label = self._selected_quick_label()
        if label is not None:
            self._edit_label_dialog(label)

    def _delete_quick_label(self, event):
        label = self._selected_quick_label()
        if label is None:
            return
        if wx.MessageBox("Delete quick label “{}”?".format(label.text), "Delete quick label", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES:
            return
        try:
            self._label_store().delete(label.preset_id)
            self._refresh_quick_labels()
        except (OSError, LookupError) as error:
            wx.MessageBox(str(error), "Could not delete quick label", wx.OK | wx.ICON_ERROR, self)

    def _visibility_entries(self):
        if self.visibility_kind.GetStringSelection() == "Symbols":
            return tuple((item.asset_id, "{}  ·  {}{}".format(item.category, item.name, " — " + item.variant.replace("_", " ").title() if item.variant != "default" else "")) for item in self.symbol_catalog.symbols if item.source == "bundle")
        return tuple((item.preset_id, item.text) for item in self.symbol_catalog.labels if item.source == "bundle")

    def _refresh_visibility(self):
        if not hasattr(self, "visibility_list"):
            return
        self._visibility_entries_current = self._visibility_entries()
        hidden = self._hidden_symbol_ids if self.visibility_kind.GetStringSelection() == "Symbols" else self._hidden_label_ids
        self.visibility_list.SetVisibilityRows(
            tuple(label for _identifier, label in self._visibility_entries_current),
            tuple(identifier not in hidden for identifier, _label in self._visibility_entries_current),
        )

    def _set_visibility(self, visible):
        index = self.visibility_list.GetSelection()
        if not 0 <= index < len(self._visibility_entries_current):
            return
        identifier, _label = self._visibility_entries_current[index]
        hidden = self._hidden_symbol_ids if self.visibility_kind.GetStringSelection() == "Symbols" else self._hidden_label_ids
        if visible:
            hidden.discard(identifier)
        else:
            hidden.add(identifier)
        self._refresh_visibility()

    def _build_library_page(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.library_backup_page.SetSizer(root)
        root.Add(self._heading(self.library_backup_page, "Portable data library"), 0, wx.ALL, 14)
        info = wx.StaticText(self.library_backup_page, label="Your personal SVGs, quick labels, profiles, and preferences are kept outside the installed package at:\n{}".format(self.preferences_store.root))
        info.Wrap(620)
        root.Add(info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        note = wx.StaticText(self.library_backup_page, label="Export this library to move it to another machine. Import replaces the current library after a clear confirmation, making it suitable for restoring an exact backup.")
        note.Wrap(620)
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        export = ThemedActionButton(self.library_backup_page, "Export library…", lambda: self._export_library(None))
        imported = ThemedActionButton(self.library_backup_page, "Import library…", lambda: self._import_library(None))
        actions.Add(export, 0, wx.RIGHT, 6)
        actions.Add(imported, 0)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT, 14)
        root.AddStretchSpacer(1)
        root.Add(wx.StaticLine(self.library_backup_page), 0, wx.EXPAND | wx.ALL, 14)
        warning = wx.StaticText(self.library_backup_page, label="Reset to shipped defaults removes every custom SVG, quick label, profile, and preference in this library. This cannot be undone.")
        warning.Wrap(620)
        root.Add(warning, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(ThemedActionButton(self.library_backup_page, "Reset library to shipped defaults…", lambda: self._reset_library(None)), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        visibility_root = wx.BoxSizer(wx.VERTICAL)
        self.library_visibility_page.SetSizer(visibility_root)
        visibility_root.Add(self._heading(self.library_visibility_page, "Bundled library visibility"), 0, wx.ALL, 14)
        message = wx.StaticText(self.library_visibility_page, label="Hide only the shipped item you select. Linked quick labels remain available unless you explicitly hide those too.")
        message.Wrap(620)
        visibility_root.Add(message, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        visibility_row = wx.BoxSizer(wx.HORIZONTAL)
        visibility_row.Add(wx.StaticText(self.library_visibility_page, label="Manage"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.visibility_kind = ThemedChoice(self.library_visibility_page, choices=("Symbols", "Quick labels"))
        self.visibility_kind.Bind(wx.EVT_CHOICE, lambda event: self._refresh_visibility())
        visibility_row.Add(self.visibility_kind, 0)
        visibility_root.Add(visibility_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        visibility_actions = wx.BoxSizer(wx.HORIZONTAL)
        visibility_actions.Add(ThemedActionButton(self.library_visibility_page, "Hide selected", lambda: self._set_visibility(False)), 0, wx.RIGHT, 6)
        visibility_actions.Add(ThemedActionButton(self.library_visibility_page, "Show selected", lambda: self._set_visibility(True)), 0)
        visibility_root.Add(visibility_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.visibility_list = ThemedListBox(self.library_visibility_page)
        visibility_root.Add(self.visibility_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self._refresh_visibility()

        info_root = wx.BoxSizer(wx.VERTICAL)
        self.info_page.SetSizer(info_root)
        info_root.Add(self._heading(self.info_page, "Kobee Studio"), 0, wx.ALL, 14)
        build = wx.StaticText(self.info_page, label="Version {}\nTesting stream".format(__version__))
        info_root.Add(build, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        help_text = wx.StaticText(self.info_page, label="Help and guides\nhttps://www.coreybusuttil.com/kobeestudio/docs/\n\nReport an issue or contribute\nhttps://github.com/mrcpuddington/kobeestudio")
        help_text.Wrap(620)
        info_root.Add(help_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

    def _export_library(self, event):
        dialog = wx.FileDialog(self, "Export Kobee Studio library", wildcard="Kobee Studio library (*.zip)|*.zip", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            count = export_library(self.preferences_store.root, Path(dialog.GetPath()))
            wx.MessageBox("Exported {} file(s).".format(count), "Library exported", wx.OK | wx.ICON_INFORMATION, self)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            wx.MessageBox(str(error), "Could not export library", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _import_library(self, event):
        dialog = wx.FileDialog(self, "Import Kobee Studio library", wildcard="Kobee Studio library (*.zip)|*.zip", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            if wx.MessageBox(
                "Restore this library and replace all current preferences, custom SVGs, quick labels, and profiles? This cannot be undone from Kobo Studio.",
                "Replace current library",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                self,
            ) != wx.YES:
                return
            count = restore_library(Path(dialog.GetPath()), self.preferences_store.root)
            wx.MessageBox("Restored {} file(s). Reopen Kobo Studio to load the restored preferences and library.".format(count), "Library restored", wx.OK | wx.ICON_INFORMATION, self)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            wx.MessageBox(str(error), "Could not import library", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _reset_library(self, event):
        if wx.MessageBox(
            "This removes all custom SVGs, quick labels, profiles, display preferences, and hidden-item choices. Bundled defaults remain. Continue?",
            "Reset library to shipped defaults",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            self,
        ) != wx.YES:
            return
        confirm = wx.TextEntryDialog(
            self,
            "Type RESET to permanently remove this library's custom data.",
            "Confirm reset to shipped defaults",
        )
        try:
            if confirm.ShowModal() != wx.ID_OK or confirm.GetValue().strip() != "RESET":
                return
            reset_library(self.preferences_store.root)
            preferences = AppPreferences()
            self.preferences_store.save(preferences)
            self.preferences_changed(preferences)
            self._hidden_symbol_ids.clear()
            self._hidden_label_ids.clear()
            self.appearance_choice.SetStringSelection("Follow system")
            self.unit_choice.SetStringSelection("Millimetres (mm)")
            self._refresh_uploads()
            self._refresh_quick_labels()
            self._refresh_visibility()
            wx.MessageBox("The library has been reset to shipped defaults.", "Library reset", wx.OK | wx.ICON_INFORMATION, self)
        except OSError as error:
            wx.MessageBox(str(error), "Could not reset library", wx.OK | wx.ICON_ERROR, self)
        finally:
            confirm.Destroy()

    def _asset_store(self) -> SvgAssetStore:
        if self.scope_choice.GetStringSelection() == "This project" and self.project_asset_store is not None:
            return self.project_asset_store
        return self.global_asset_store

    def _asset_namespace(self) -> str:
        return "symbols" if self.namespace_choice.GetStringSelection() == "Symbols" else "graphics"

    def _on_upload_filter_changed(self, event):
        self._refresh_uploads()
        event.Skip()

    def _refresh_uploads(self):
        if not hasattr(self, "upload_list"):
            return
        self._upload_items = self._asset_store().list(self._asset_namespace())
        self.upload_list.Set(
            tuple("{} — {} · {}".format(item.name, item.variant, item.scope) for item in self._upload_items)
        )
        if hasattr(self, "add_variant_button"):
            self.add_variant_button.Enable(self._asset_namespace() == "symbols")

    def _upload_svg(self, event):
        picker = wx.FileDialog(
            self,
            "Upload an SVG",
            wildcard="SVG files (*.svg)|*.svg",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if picker.ShowModal() != wx.ID_OK:
                return
            source = Path(picker.GetPath())
        finally:
            picker.Destroy()
        if self._asset_namespace() == "symbols":
            details = SymbolUploadDetailsDialog(
                self,
                title="Upload a symbol",
                name=source.stem.replace("_", " ").title(),
            )
            try:
                if details.ShowModal() != wx.ID_OK:
                    return
                name, category, variant = details.values()
                self._asset_store().upload(source, "symbols", name, category=category, variant=variant)
                self._refresh_uploads()
            except (OSError, ValueError) as error:
                wx.MessageBox(str(error), "Could not upload SVG", wx.OK | wx.ICON_ERROR, self)
            finally:
                details.Destroy()
            return
        name_prompt = wx.TextEntryDialog(self, "Display name", "Upload SVG", source.stem.replace("_", " ").title())
        try:
            if name_prompt.ShowModal() != wx.ID_OK:
                return
            self._asset_store().upload(source, self._asset_namespace(), name_prompt.GetValue())
            self._refresh_uploads()
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not upload SVG", wx.OK | wx.ICON_ERROR, self)
        finally:
            name_prompt.Destroy()

    def _upload_variant(self, event):
        selection = self.upload_list.GetSelection()
        if self._asset_namespace() != "symbols" or selection < 0 or selection >= len(self._upload_items):
            wx.MessageBox(
                "Select an existing symbol family before adding a variant.",
                "Add symbol variant",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        family = self._upload_items[selection]
        picker = wx.FileDialog(
            self,
            "Upload a symbol variant",
            wildcard="SVG files (*.svg)|*.svg",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if picker.ShowModal() != wx.ID_OK:
                return
            source = Path(picker.GetPath())
        finally:
            picker.Destroy()
        details = SymbolUploadDetailsDialog(
            self,
            title="Add a symbol variant",
            name=family.name,
            category=family.category,
            variant="rounded",
            existing_family=True,
        )
        try:
            if details.ShowModal() != wx.ID_OK:
                return
            _name, _category, variant = details.values()
            self._asset_store().upload(
                source,
                "symbols",
                family.name,
                category=family.category,
                slug=family.slug,
                variant=variant,
                asset_id=family.asset_id,
            )
            self._refresh_uploads()
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not add symbol variant", wx.OK | wx.ICON_ERROR, self)
        finally:
            details.Destroy()

    def _delete_upload(self, event):
        selection = self.upload_list.GetSelection()
        if selection < 0 or selection >= len(self._upload_items):
            return
        item = self._upload_items[selection]
        answer = wx.MessageBox(
            "Delete “{}” ({})? Existing placed artwork will remain, but it cannot be regenerated after this asset is removed.".format(item.name, item.variant),
            "Delete uploaded SVG",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            self,
        )
        if answer != wx.YES:
            return
        try:
            self._asset_store().delete(self._asset_namespace(), item.asset_id, item.variant)
            self._refresh_uploads()
        except OSError as error:
            wx.MessageBox(str(error), "Could not delete SVG", wx.OK | wx.ICON_ERROR, self)

    def _on_ok(self, event=None):
        appearance = {
            "Follow system": "system",
            "Light": "light",
            "Dark": "dark",
        }[self.appearance_choice.GetStringSelection()]
        unit = MeasurementUnit.MILS if self.unit_choice.GetStringSelection() == "Mils (mil)" else MeasurementUnit.MILLIMETRES
        preferences = AppPreferences(
            appearance=appearance,
            measurement_unit=unit,
            hidden_symbol_ids=tuple(self._hidden_symbol_ids),
            hidden_label_ids=tuple(self._hidden_label_ids),
        )
        try:
            self.preferences_store.save(preferences)
            self.preferences_changed(preferences)
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not save settings", wx.OK | wx.ICON_ERROR, self)
            return
        self.EndModal(wx.ID_OK)

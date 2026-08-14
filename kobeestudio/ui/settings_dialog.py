"""Application settings, profile/default, and SVG upload management UI."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional
import io
import zipfile
import threading

import wx

from ..core.app_preferences import AppPreferences, AppPreferencesStore
from ..core.measurement_units import MeasurementUnit
from ..core.quick_labels import QuickLabelStore
from ..core.settings_profiles import SettingsProfileStore
from ..core.svg_symbols import SvgAssetStore
from ..core.library_archive import export_library, reset_library, restore_library
from ..core.font_library import FontLibraryStore
from ..core.component_presets import ComponentPresetStore
from ..core.raster_trace import RasterTraceSettings, trace_png_file
from ..version import __version__
from .theme import apply_native_theme, is_dark_mode
from .themed_controls import (
    ThemedActionButton,
    ThemedChoice,
    ThemedListBox,
    ThemedSpinCtrl,
    ThemedSpinCtrlDouble,
)


MODULE_LABELS = {
    "labels": "Labels",
    "pin_headers": "Header overlays",
    "component_callouts": "Component callouts",
    "component_arrays": "Component arrays",
    "machine_codes": "QR codes and barcodes",
    "graphics": "Imported graphics",
    "board_tools": "Board tools",
}
MODULE_BY_LABEL = {label: module for module, label in MODULE_LABELS.items()}
SYMBOL_CATEGORIES = ("Custom", "Controls", "Direction", "Electrical", "PCB", "Safety")
SYMBOL_VARIANTS = ("default", "rounded")


class FontPreviewPanel(wx.Panel):
    """Small cached-polygon canvas used by the on-demand font browser."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetMinSize(wx.Size(-1, 145))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._filled = ()
        self._strokes = ()
        self._message = "Select a font family to preview it"
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(False), event.Skip()))

    def set_message(self, message):
        self._filled = (); self._strokes = (); self._message = str(message)
        self.Refresh(False)

    def set_artwork(self, artwork):
        self._filled = tuple(artwork.filled_polygons)
        self._strokes = tuple(artwork.strokes)
        self._message = ""
        self.Refresh(False)

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dark = is_dark_mode(wx)
        background = wx.Colour(39, 37, 34) if dark else wx.Colour(255, 255, 253)
        foreground = wx.Colour(245, 242, 236) if dark else wx.Colour(34, 33, 30)
        dc.SetBackground(wx.Brush(background)); dc.Clear()
        rect = self.GetClientRect().Deflate(14)
        polygons = self._filled + tuple(stroke.points for stroke in self._strokes)
        points = tuple(point for polygon in polygons for point in polygon)
        if not points:
            dc.SetTextForeground(wx.Colour(181, 175, 165) if dark else wx.Colour(113, 108, 100))
            dc.DrawLabel(self._message, rect, wx.ALIGN_CENTER)
            return
        min_x = min(point.x for point in points); max_x = max(point.x for point in points)
        min_y = min(point.y for point in points); max_y = max(point.y for point in points)
        width = max(0.001, max_x - min_x); height = max(0.001, max_y - min_y)
        scale = min(rect.width / width, rect.height / height) * 0.88
        centre_x = (min_x + max_x) / 2.0; centre_y = (min_y + max_y) / 2.0

        def device(point):
            return wx.Point(
                round(rect.GetX() + rect.width / 2.0 + (point.x - centre_x) * scale),
                round(rect.GetY() + rect.height / 2.0 + (point.y - centre_y) * scale),
            )

        dc.SetPen(wx.Pen(foreground, 1)); dc.SetBrush(wx.Brush(foreground))
        for polygon in self._filled:
            if len(polygon) >= 3:
                dc.DrawPolygon(tuple(device(point) for point in polygon))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        for stroke in self._strokes:
            if len(stroke.points) >= 2:
                dc.SetPen(wx.Pen(foreground, max(1, round(stroke.width_mm * scale))))
                dc.DrawLines(tuple(device(point) for point in stroke.points))


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


class ComponentPresetDetailsDialog(wx.Dialog):
    def __init__(self, parent, preset=None):
        super().__init__(parent, title="Edit component preset" if preset else "Add component preset")
        root = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 9, 10); grid.AddGrowableCol(1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 14)
        values = {
            "name": preset.name if preset else "Custom component",
            "width": preset.width_mm if preset else 5.0,
            "height": preset.height_mm if preset else 5.0,
            "radius": preset.cutout_radius_mm if preset else 0.2,
        }
        self.name = wx.TextCtrl(self, value=values["name"])
        self.width = ThemedSpinCtrlDouble(self, min=0.1, max=1000, initial=values["width"], inc=0.1)
        self.height = ThemedSpinCtrlDouble(self, min=0.1, max=1000, initial=values["height"], inc=0.1)
        self.shape = ThemedChoice(self, choices=("Rectangle", "Rounded rectangle", "Pill", "Tactile switch"))
        shape_id = preset.cutout_shape if preset else "rounded_rectangle"
        self.shape.SetStringSelection({"rectangle":"Rectangle", "rounded_rectangle":"Rounded rectangle", "pill":"Pill", "tactile_switch":"Tactile switch"}[shape_id])
        self.radius = ThemedSpinCtrlDouble(self, min=0, max=1000, initial=values["radius"], inc=0.05)
        for label, control in (("Name", self.name), ("Width (mm)", self.width), ("Height (mm)", self.height), ("Cutout", self.shape), ("Radius (mm)", self.radius)):
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL); grid.Add(control, 1, wx.EXPAND)
        root.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self.SetSizerAndFit(root); self.SetMinSize(wx.Size(460, -1))

    def values(self):
        shape = {"Rectangle":"rectangle", "Rounded rectangle":"rounded_rectangle", "Pill":"pill", "Tactile switch":"tactile_switch"}[self.shape.GetStringSelection()]
        return self.name.GetValue(), self.width.GetValue(), self.height.GetValue(), shape, self.radius.GetValue()


class PngTraceDialog(wx.Dialog):
    """Interactive, bounded PNG trace controls with a live monochrome preview."""
    def __init__(self, parent, source: Path, settings: RasterTraceSettings = None):
        super().__init__(parent, title="Convert PNG to PCB graphic", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.source = Path(source); self.result = None; settings = settings or RasterTraceSettings()
        root = wx.BoxSizer(wx.HORIZONTAL); controls = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 8, 9); grid.AddGrowableCol(1); controls.Add(grid, 0, wx.EXPAND)
        self.threshold = wx.Slider(self, minValue=0, maxValue=255, value=settings.threshold)
        self.alpha = wx.Slider(self, minValue=0, maxValue=255, value=settings.alpha_cutoff)
        self.smoothing = ThemedSpinCtrl(self, min=0, max=3, initial=settings.smoothing)
        self.despeckle = ThemedSpinCtrl(self, min=0, max=10000, initial=settings.despeckle_pixels)
        self.width = ThemedSpinCtrlDouble(self, min=0.1, max=1000, initial=settings.width_mm, inc=0.1)
        self.invert = wx.CheckBox(self, label="Invert black and white")
        self.invert.SetValue(settings.invert)
        self.crop = wx.CheckBox(self, label="Crop transparent/empty edges"); self.crop.SetValue(settings.auto_crop)
        for label, control in (("Threshold",self.threshold),("Alpha cutoff",self.alpha),("Smoothing",self.smoothing),("Despeckle pixels",self.despeckle),("Output width (mm)",self.width)):
            grid.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL); grid.Add(control,1,wx.EXPAND)
        controls.Add(self.invert,0,wx.TOP,10); controls.Add(self.crop,0,wx.TOP,7)
        self.status = wx.StaticText(self,label=""); controls.Add(self.status,0,wx.EXPAND|wx.TOP,10)
        controls.AddStretchSpacer(1); controls.Add(self.CreateStdDialogButtonSizer(wx.OK|wx.CANCEL),0,wx.EXPAND|wx.TOP,10)
        self.preview = wx.StaticBitmap(self); self.preview.SetMinSize(wx.Size(380,380))
        root.Add(controls,0,wx.EXPAND|wx.ALL,14); root.Add(self.preview,1,wx.EXPAND|wx.TOP|wx.RIGHT|wx.BOTTOM,14)
        self.SetSizer(root); self.SetMinSize(wx.Size(760,470)); self.SetSize(wx.Size(840,540))
        self._preview_generation = 0; self._preview_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._start_preview, self._preview_timer)
        for control in (self.threshold,self.alpha,self.smoothing,self.despeckle,self.width,self.invert,self.crop):
            event_types = (
                (wx.EVT_SLIDER,) if isinstance(control, wx.Slider)
                else (wx.EVT_CHECKBOX,) if isinstance(control, wx.CheckBox)
                else (wx.EVT_TEXT, wx.EVT_SPINCTRL, wx.EVT_SPINCTRLDOUBLE)
            )
            for event_type in event_types:
                control.Bind(event_type, self._changed)
        self._queue_preview()

    def settings(self):
        return RasterTraceSettings(self.threshold.GetValue(), self.invert.GetValue(), self.alpha.GetValue(), self.crop.GetValue(), self.smoothing.GetValue(), self.despeckle.GetValue(), self.width.GetValue())

    def _changed(self,event): self._queue_preview(); event.Skip()
    def _queue_preview(self):
        self._preview_generation += 1; self.result = None
        button = self.FindWindow(wx.ID_OK)
        if button is not None: button.Disable()
        self.status.SetLabel("Tracing preview…")
        self._preview_timer.StartOnce(120)

    def _start_preview(self, event=None):
        generation=self._preview_generation; settings=self.settings(); source=self.source
        def worker():
            try: result,error=trace_png_file(source,settings),None
            except Exception as caught: result,error=None,caught
            wx.CallAfter(self._finish_preview,generation,result,error)
        threading.Thread(target=worker,daemon=True).start()

    def _finish_preview(self, generation, result, error):
        if generation != self._preview_generation or self.IsBeingDeleted(): return
        button = self.FindWindow(wx.ID_OK)
        if error is not None:
            self.result=None; self.status.SetLabel(str(error))
            if button is not None: button.Disable()
            return
        self.result=result
        try:
            image = wx.Image(io.BytesIO(self.result.preview_png), wx.BITMAP_TYPE_PNG)
            target = self.preview.GetClientSize(); scale=min(max(1,target.width)/image.GetWidth(),max(1,target.height)/image.GetHeight())
            image=image.Scale(max(1,int(image.GetWidth()*scale)),max(1,int(image.GetHeight()*scale)),wx.IMAGE_QUALITY_HIGH)
            self.preview.SetBitmap(wx.Bitmap(image)); self.status.SetLabel("{} × {} traced pixels".format(*self.result.pixel_size))
            if button is not None: button.Enable()
        except Exception as caught:
            self.result=None; self.status.SetLabel(str(caught))
            if button is not None: button.Disable()


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
        preferences_changed: Callable[[AppPreferences], None],
        font_store: Optional[FontLibraryStore] = None,
        global_component_store: Optional[ComponentPresetStore] = None,
        project_component_store: Optional[ComponentPresetStore] = None,
        font_preview_renderer: Optional[Callable] = None,
        initial_page: int = 0,
    ):
        super().__init__(
            parent,
            title="Kobee Studio Settings",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=wx.Size(980, 620),
        )
        self.preferences_store = preferences_store
        self.profile_store = profile_store
        self.global_asset_store = global_asset_store
        self.project_asset_store = project_asset_store
        self.global_label_store = global_label_store
        self.project_label_store = project_label_store
        self.font_store = font_store or FontLibraryStore(preferences_store.root)
        self.global_component_store = global_component_store or ComponentPresetStore.global_store(preferences_store.root)
        self.project_component_store = project_component_store
        self.font_preview_renderer = font_preview_renderer
        self.symbol_catalog = symbol_catalog
        self._hidden_symbol_ids = set(hidden_symbol_ids)
        self._hidden_label_ids = set(hidden_label_ids)
        self.current_module = current_module
        self.preferences_changed = preferences_changed
        self._saved_preferences = self.preferences_store.load()
        self._profiles = ()
        self._upload_items = ()
        self._quick_labels = ()
        self.restart_editor = False
        self._font_preview_generation = 0
        self._font_preview_loading = False
        self._font_preview_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_font_preview_timer, self._font_preview_timer)

        root = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Simplebook(self)
        self.general_page = wx.Panel(self.notebook)
        self.profile_page = wx.Panel(self.notebook)
        self.fonts_page = wx.Panel(self.notebook)
        self.assets_page = wx.Panel(self.notebook)
        self.components_page = wx.Panel(self.notebook)
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
        for index, label in enumerate(("Icons & graphics", "Quick labels")):
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
        for page in (self.general_page, self.profile_page, self.fonts_page, self.assets_page, self.components_page, self.library_page, self.info_page):
            self.notebook.AddPage(page, "")
        self._page_buttons = []
        page_tabs = wx.WrapSizer(wx.HORIZONTAL)
        for index, label in enumerate(("General", "Profiles", "Fonts", "Asset library", "Component presets", "Data & backup", "About")):
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
        self._build_fonts_page()
        self._build_upload_page()
        self._build_quick_labels_page()
        self._build_components_page()
        self._build_library_page()
        self._apply_theme()
        self._select_page(max(0, min(int(initial_page), len(self._page_buttons) - 1)))
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
        for page in (self.general_page, self.profile_page, self.fonts_page, self.assets_page, self.upload_page, self.quick_labels_page, self.components_page, self.library_page, self.library_backup_page, self.library_visibility_page, self.info_page):
            page.SetBackgroundColour(palette["surface"])
        apply_native_theme(self, wx, palette)
        for control in (getattr(self, "profile_list", None), getattr(self, "font_catalog_list", None), getattr(self, "installed_font_list", None), getattr(self, "component_list", None), getattr(self, "upload_list", None), getattr(self, "quick_label_list", None), getattr(self, "visibility_list", None)):
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
        root.Add(self._heading(self.profile_page, "Saved profiles"), 0, wx.ALL, 14)
        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(wx.StaticText(self.profile_page, label="Module"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.module_choice = ThemedChoice(self.profile_page, choices=tuple(MODULE_BY_LABEL))
        self.module_choice.SetStringSelection(MODULE_LABELS.get(self.current_module, "Labels"))
        self.module_choice.Bind(wx.EVT_CHOICE, self._on_profile_module_changed)
        top.Add(self.module_choice, 1)
        root.Add(top, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        self.profile_list = ThemedListBox(self.profile_page)
        root.Add(self.profile_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        actions = wx.WrapSizer(wx.HORIZONTAL)
        for label, handler in (
            ("Set default", self._set_default_profile),
            ("Clear default", self._clear_default_profile),
            ("Delete", self._delete_profile),
        ):
            button = ThemedActionButton(self.profile_page, label, lambda handler=handler: handler(None))
            actions.Add(button, 0, wx.RIGHT, 6)
        root.Add(actions, 0, wx.ALL, 14)
        note = wx.StaticText(
            self.profile_page,
            label="Save and recall profiles from each editor tool. Set one default here to use it for new artwork; without one, the app’s standard defaults are used.",
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

    def _build_fonts_page(self):
        root = wx.BoxSizer(wx.VERTICAL); self.fonts_page.SetSizer(root)
        root.Add(self._heading(self.fonts_page, "Google Fonts library"), 0, wx.ALL, 14)
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.font_search = wx.SearchCtrl(self.fonts_page, style=wx.TE_PROCESS_ENTER)
        self.font_search.SetDescriptiveText("Search Google Fonts")
        self.font_search.Bind(wx.EVT_TEXT, lambda event: self._refresh_font_catalog())
        search_row.Add(self.font_search, 1, wx.RIGHT, 8)
        search_row.Add(ThemedActionButton(self.fonts_page, "Refresh catalog", self._refresh_font_catalog_online), 0)
        root.Add(search_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        columns = wx.BoxSizer(wx.HORIZONTAL)
        catalog_col = wx.BoxSizer(wx.VERTICAL); installed_col = wx.BoxSizer(wx.VERTICAL)
        catalog_col.Add(wx.StaticText(self.fonts_page, label="Available families"), 0, wx.BOTTOM, 5)
        self.font_catalog_list = ThemedListBox(self.fonts_page); catalog_col.Add(self.font_catalog_list, 1, wx.EXPAND)
        self.install_font_button = ThemedActionButton(self.fonts_page, "Choose faces and install…", self._install_font_faces)
        catalog_col.Add(self.install_font_button, 0, wx.TOP, 8)
        installed_col.Add(wx.StaticText(self.fonts_page, label="My installed faces"), 0, wx.BOTTOM, 5)
        self.installed_font_list = ThemedListBox(self.fonts_page); installed_col.Add(self.installed_font_list, 1, wx.EXPAND)
        font_actions = wx.BoxSizer(wx.HORIZONTAL)
        self.repair_font_button = ThemedActionButton(self.fonts_page, "Redownload missing", self._repair_font_face)
        font_actions.Add(self.repair_font_button, 0, wx.RIGHT, 6)
        font_actions.Add(ThemedActionButton(self.fonts_page, "Remove selected", self._remove_font_face), 0)
        installed_col.Add(font_actions, 0, wx.TOP, 8)
        self.installed_font_list.Bind(wx.EVT_LISTBOX, self._on_font_selection)
        self.font_catalog_list.Bind(wx.EVT_LISTBOX, self._on_font_catalog_selection)
        columns.Add(catalog_col, 1, wx.EXPAND | wx.RIGHT, 8); columns.Add(installed_col, 1, wx.EXPAND | wx.LEFT, 8)
        root.Add(columns, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        preview_box = wx.StaticBoxSizer(wx.VERTICAL, self.fonts_page, "Selected font preview")
        preview_controls = wx.BoxSizer(wx.HORIZONTAL)
        preview_controls.Add(wx.StaticText(self.fonts_page, label="Face"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.font_face_choice = ThemedChoice(self.fonts_page, choices=("400 Regular",))
        self.font_face_choice.SetMinSize(wx.Size(150, 30))
        self.font_face_choice.Bind(wx.EVT_CHOICE, self._on_font_preview_changed)
        preview_controls.Add(self.font_face_choice, 0, wx.RIGHT, 10)
        preview_controls.Add(wx.StaticText(self.fonts_page, label="Sample"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.font_preview_text = wx.TextCtrl(self.fonts_page, value="R1  10kΩ  INPUT")
        self.font_preview_text.SetMaxLength(80)
        self.font_preview_text.Bind(wx.EVT_TEXT, self._on_font_preview_changed)
        preview_controls.Add(self.font_preview_text, 1)
        preview_box.Add(preview_controls, 0, wx.EXPAND | wx.ALL, 8)
        self.font_preview = FontPreviewPanel(self.fonts_page)
        preview_box.Add(self.font_preview, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(preview_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 14)
        self.font_status = wx.StaticText(self.fonts_page, label="Installed fonts remain available offline.")
        root.Add(self.font_status, 0, wx.ALL, 14)
        self._font_catalog = self.font_store.load_catalog(); self._visible_font_catalog = ()
        self._refresh_font_catalog(); self._refresh_installed_fonts()

    def _refresh_font_catalog(self):
        query = self.font_search.GetValue().strip().casefold() if hasattr(self, "font_search") else ""
        self._visible_font_catalog = tuple(item for item in self._font_catalog if query in str(item.get("family", "")).casefold())
        self.font_catalog_list.Set(tuple("{}  ·  {}".format(item.get("family", "Unnamed"), item.get("category", "Google Fonts")) for item in self._visible_font_catalog))

    @staticmethod
    def _font_face_keys(family):
        return tuple(str(key) for key in (family.get("fonts") or {"400": {}}))

    @staticmethod
    def _font_face_label(key):
        return "{} {}".format(key.rstrip("i"), "Italic" if key.endswith("i") else "Regular")

    def _on_font_catalog_selection(self, event):
        selection = self.font_catalog_list.GetSelection()
        if not 0 <= selection < len(self._visible_font_catalog):
            return
        keys = self._font_face_keys(self._visible_font_catalog[selection])
        self.font_face_choice.SetItems(tuple(self._font_face_label(key) for key in keys))
        preferred = keys.index("400") if "400" in keys else 0
        self.font_face_choice.SetSelection(preferred)
        self._start_font_preview()
        event.Skip()

    def _on_font_preview_changed(self, event):
        # Text editing uses the already-renderable cached face and does not
        # initiate a catalog-wide operation.  A generation token coalesces the
        # rapid events emitted while typing or changing a face.
        self._font_preview_timer.StartOnce(240)
        event.Skip()

    def _on_font_preview_timer(self, event):
        self._start_font_preview()

    def _selected_preview_face(self):
        selection = self.font_catalog_list.GetSelection()
        if not 0 <= selection < len(self._visible_font_catalog):
            return None
        family = self._visible_font_catalog[selection]
        keys = self._font_face_keys(family)
        index = self.font_face_choice.GetSelection()
        if not 0 <= index < len(keys):
            return None
        key = keys[index]
        return str(family.get("family", "")), int(key.rstrip("i")), "italic" if key.endswith("i") else "normal"

    def _start_font_preview(self):
        selected = self._selected_preview_face()
        if selected is None:
            self.font_preview.set_message("Select a font family to preview it")
            return
        family, weight, style = selected
        sample = self.font_preview_text.GetValue().strip() or "R1  10kΩ  INPUT"
        self._font_preview_generation += 1
        generation = self._font_preview_generation
        self.font_preview.set_message("Loading {}…".format(family))
        self.font_status.SetLabel("Loading one selected face for preview…")

        installed = next((
            face for face in self.font_store.list()
            if face.family == family and face.weight == weight and face.style == style
        ), None)
        if installed is not None:
            self._font_preview_ready(
                generation, family, weight, style, sample,
                (installed.path, installed.source_url, True), None, False,
            )
            return
        if self._font_preview_loading:
            # The completion callback will restart using the newest selected
            # face/sample.  Never fan out network work while someone browses
            # rapidly through the 1,900-family catalog.
            return
        self._font_preview_loading = True

        def worker():
            try:
                result, error = self.font_store.preview_face(family, weight, style), None
            except Exception as caught:
                result, error = None, caught
            wx.CallAfter(self._font_preview_ready, generation, family, weight, style, sample, result, error, True)
        threading.Thread(target=worker, daemon=True).start()

    def _font_preview_ready(self, generation, family, weight, style, sample, result, error, from_worker=True):
        if from_worker:
            self._font_preview_loading = False
        if not self or self.IsBeingDeleted():
            return
        if generation != self._font_preview_generation:
            self._start_font_preview()
            return
        if error is not None:
            self.font_preview.set_message("Preview unavailable")
            self.font_status.SetLabel("Could not preview {}: {}".format(family, error))
            return
        if self.font_preview_renderer is None:
            self.font_preview.set_message("Preview renderer is unavailable in this session")
            return
        path, _source_url, cached = result
        renderer_name = "__kobee_preview_{}".format(self.font_store._preview_key(family, weight, style)[:16])
        try:
            artwork = self.font_preview_renderer(path, renderer_name, sample)
            self.font_preview.set_artwork(artwork)
            self.font_status.SetLabel("Previewing {} {} {}{}.".format(
                family, weight, style.title(), " from the offline cache" if cached else ""
            ))
        except Exception as caught:
            self.font_preview.set_message("Preview unavailable")
            self.font_status.SetLabel("Could not render {}: {}".format(family, caught))

    def _refresh_installed_fonts(self):
        self._installed_fonts = self.font_store.records()
        self.installed_font_list.Set(tuple("{}{}".format(item.display_name, " — Missing file" if item.missing else "") for item in self._installed_fonts))
        self._update_font_actions()

    def _on_font_selection(self, event):
        self._update_font_actions(); event.Skip()

    def _update_font_actions(self):
        if not hasattr(self, "repair_font_button"): return
        selection = self.installed_font_list.GetSelection()
        self.repair_font_button.Enable(0 <= selection < len(self._installed_fonts) and self._installed_fonts[selection].missing)

    def _repair_font_face(self, event):
        selection = self.installed_font_list.GetSelection()
        if not 0 <= selection < len(self._installed_fonts) or not self._installed_fonts[selection].missing: return
        face = self._installed_fonts[selection]
        self.repair_font_button.Disable(); self.font_status.SetLabel("Redownloading {}…".format(face.display_name))
        def worker():
            try: repaired, error = self.font_store.repair(face.face_id), None
            except Exception as caught: repaired, error = None, caught
            wx.CallAfter(self._font_repair_finished, repaired, error)
        threading.Thread(target=worker, daemon=True).start()

    def _font_repair_finished(self, repaired, error):
        self._refresh_installed_fonts()
        if error is not None:
            self.font_status.SetLabel("Could not redownload font: {}".format(error)); return
        self.restart_editor = True
        self.font_status.SetLabel("Restored {} and retained its saved font identity.".format(repaired.display_name))

    def _refresh_font_catalog_online(self, event):
        self.font_status.SetLabel("Refreshing Google Fonts catalog…")
        def worker():
            try: result, error = self.font_store.refresh_catalog(), None
            except Exception as caught: result, error = (), caught
            wx.CallAfter(self._font_catalog_finished, result, error)
        threading.Thread(target=worker, daemon=True).start()

    def _font_catalog_finished(self, result, error):
        if error is not None:
            self.font_status.SetLabel("Could not refresh; using the offline catalog: {}".format(error)); return
        self._font_catalog = result; self._refresh_font_catalog()
        self.font_status.SetLabel("Catalog refreshed: {} families.".format(len(result)))

    def _install_font_faces(self, event):
        selection = self.font_catalog_list.GetSelection()
        if not 0 <= selection < len(self._visible_font_catalog): return
        family = self._visible_font_catalog[selection]
        face_keys = self._font_face_keys(family)
        choices = tuple(self._font_face_label(key) for key in face_keys)
        chooser = wx.MultiChoiceDialog(self, "Choose one or more faces to install", str(family.get("family", "Google Font")), choices)
        try:
            if chooser.ShowModal() != wx.ID_OK or not chooser.GetSelections(): return
            selected = tuple(face_keys[index] for index in chooser.GetSelections())
        finally: chooser.Destroy()
        self.install_font_button.Disable(); self.font_status.SetLabel("Downloading selected font faces…")
        def worker():
            installed, failures = [], []
            for key in selected:
                try: installed.append(self.font_store.download_google_face(str(family["family"]), int(key.rstrip("i")), "italic" if key.endswith("i") else "normal"))
                except Exception as error: failures.append("{}: {}".format(key, error))
            wx.CallAfter(self._font_install_finished, installed, failures)
        threading.Thread(target=worker, daemon=True).start()

    def _font_install_finished(self, installed, failures):
        self.install_font_button.Enable(); self._refresh_installed_fonts()
        self.restart_editor = self.restart_editor or bool(installed)
        self.font_status.SetLabel("Installed {} face(s).{}".format(len(installed), " " + "; ".join(failures) if failures else ""))

    def _remove_font_face(self, event):
        selection = self.installed_font_list.GetSelection()
        if not 0 <= selection < len(self._installed_fonts): return
        face = self._installed_fonts[selection]
        if wx.MessageBox("Remove {} from your font library?".format(face.display_name), "Remove font", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES: return
        try:
            self.font_store.delete(face.face_id); self.restart_editor = True; self._refresh_installed_fonts()
        except (OSError, LookupError, ValueError) as error:
            wx.MessageBox(str(error), "Could not remove font", wx.OK | wx.ICON_ERROR, self)

    def _build_components_page(self):
        root = wx.BoxSizer(wx.VERTICAL); self.components_page.SetSizer(root)
        root.Add(self._heading(self.components_page, "Custom component dimensions"), 0, wx.ALL, 14)
        row = wx.BoxSizer(wx.HORIZONTAL); row.Add(wx.StaticText(self.components_page, label="Scope"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 7)
        scopes = ["My library"] + (["This project"] if self.project_component_store is not None else [])
        self.component_scope = ThemedChoice(self.components_page, choices=scopes); self.component_scope.SetSelection(0)
        self.component_scope.Bind(wx.EVT_CHOICE, lambda event: self._refresh_components())
        row.Add(self.component_scope, 0); root.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self.component_list = ThemedListBox(self.components_page); root.Add(self.component_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for title, handler in (("Add preset…", self._add_component), ("Edit selected…", self._edit_component), ("Delete selected", self._delete_component)):
            actions.Add(ThemedActionButton(self.components_page, title, handler), 0, wx.RIGHT, 6)
        root.Add(actions, 0, wx.ALL, 14); self._refresh_components()

    def _component_store(self):
        return self.project_component_store if self.component_scope.GetStringSelection() == "This project" and self.project_component_store is not None else self.global_component_store

    def _refresh_components(self):
        self._components = self._component_store().list()
        self.component_list.Set(tuple("{}  ·  {:.2f} × {:.2f} mm  ·  {}".format(item.name, item.width_mm, item.height_mm, item.scope) for item in self._components))

    def _component_dialog(self, preset=None):
        dialog = ComponentPresetDetailsDialog(self, preset)
        try:
            if dialog.ShowModal() != wx.ID_OK: return
            saved = self._component_store().save(*dialog.values(), preset_id=preset.preset_id if preset else None)
            self.restart_editor = True; self._refresh_components()
            for index, item in enumerate(self._components):
                if item.preset_id == saved.preset_id: self.component_list.SetSelection(index)
        except (OSError, ValueError) as error: wx.MessageBox(str(error), "Could not save component preset", wx.OK | wx.ICON_ERROR, self)
        finally: dialog.Destroy()

    def _add_component(self, event): self._component_dialog()
    def _edit_component(self, event):
        index = self.component_list.GetSelection()
        if 0 <= index < len(self._components): self._component_dialog(self._components[index])
    def _delete_component(self, event):
        index = self.component_list.GetSelection()
        if not 0 <= index < len(self._components): return
        item = self._components[index]
        if wx.MessageBox("Delete component preset “{}”?".format(item.name), "Delete preset", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES: return
        try: self._component_store().delete(item.preset_id); self.restart_editor = True; self._refresh_components()
        except (OSError, LookupError, ValueError) as error: wx.MessageBox(str(error), "Could not delete preset", wx.OK | wx.ICON_ERROR, self)

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
        namespace_choices = ("Icons", "Graphics")
        self.namespace_choice = ThemedChoice(self.upload_page, choices=namespace_choices)
        self.namespace_choice.SetSelection(0)
        self.namespace_choice.Bind(wx.EVT_CHOICE, self._on_upload_filter_changed)
        filters.Add(self.namespace_choice, 0)
        root.Add(filters, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        self.upload_list = ThemedListBox(self.upload_page)
        self.upload_list.Bind(wx.EVT_LISTBOX, self._on_upload_selection)
        root.Add(self.upload_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        actions = wx.WrapSizer(wx.HORIZONTAL)
        upload = ThemedActionButton(self.upload_page, "Upload SVG…", lambda: self._upload_svg(None))
        self.upload_png_button = ThemedActionButton(self.upload_page, "Convert PNG…", lambda: self._upload_png(None))
        self.edit_png_button = ThemedActionButton(self.upload_page, "Edit PNG trace…", lambda: self._edit_png_trace(None))
        self.add_variant_button = ThemedActionButton(self.upload_page, "Add variant…", lambda: self._upload_variant(None))
        delete = ThemedActionButton(self.upload_page, "Delete selected", lambda: self._delete_upload(None))
        actions.Add(upload, 0, wx.RIGHT, 6)
        actions.Add(self.upload_png_button, 0, wx.RIGHT, 6)
        actions.Add(self.edit_png_button, 0, wx.RIGHT, 6)
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
        if self._visibility_kind == "Symbols":
            return tuple((item.asset_id, "{}  ·  {}{}".format(item.category, item.name, " — " + item.variant.replace("_", " ").title() if item.variant != "default" else "")) for item in self.symbol_catalog.symbols if item.source == "bundle")
        return tuple((item.preset_id, item.text) for item in self.symbol_catalog.labels if item.source == "bundle")

    def _select_visibility_kind(self, kind):
        self._visibility_kind = kind
        for button, button_kind in (
            (self.visibility_symbol_button, "Symbols"),
            (self.visibility_label_button, "Quick labels"),
        ):
            button.primary = button_kind == kind
            button.Refresh(False)
        self._refresh_visibility()

    def _on_visibility_selection(self, event):
        self._update_visibility_actions()
        event.Skip()

    def _update_visibility_actions(self):
        if not hasattr(self, "hide_visibility_button"):
            return
        index = self.visibility_list.GetSelection()
        if not 0 <= index < len(self._visibility_entries_current):
            self.hide_visibility_button.Enable(False)
            self.show_visibility_button.Enable(False)
            return
        identifier, _label = self._visibility_entries_current[index]
        hidden = self._hidden_symbol_ids if self._visibility_kind == "Symbols" else self._hidden_label_ids
        self.hide_visibility_button.Enable(identifier not in hidden)
        self.show_visibility_button.Enable(identifier in hidden)

    def _refresh_visibility(self):
        if not hasattr(self, "visibility_list"):
            return
        self._visibility_entries_current = self._visibility_entries()
        hidden = self._hidden_symbol_ids if self._visibility_kind == "Symbols" else self._hidden_label_ids
        self.visibility_list.SetVisibilityRows(
            tuple(label for _identifier, label in self._visibility_entries_current),
            tuple(identifier not in hidden for identifier, _label in self._visibility_entries_current),
        )
        self._update_visibility_actions()

    def _set_visibility(self, visible):
        index = self.visibility_list.GetSelection()
        if not 0 <= index < len(self._visibility_entries_current):
            return
        identifier, _label = self._visibility_entries_current[index]
        hidden = self._hidden_symbol_ids if self._visibility_kind == "Symbols" else self._hidden_label_ids
        if visible:
            hidden.discard(identifier)
        else:
            hidden.add(identifier)
        self._refresh_visibility()

    def _build_library_page(self):
        root = wx.BoxSizer(wx.VERTICAL)
        self.library_backup_page.SetSizer(root)
        root.Add(self._heading(self.library_backup_page, "Kobee Studio data"), 0, wx.ALL, 14)
        info = wx.StaticText(self.library_backup_page, label="Your fonts, SVGs, component presets, quick labels, profiles, preferences, and hidden-item choices are stored outside the installed package at:\n{}".format(self.preferences_store.root))
        info.Wrap(620)
        root.Add(info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        note = wx.StaticText(self.library_backup_page, label="Create a data backup to move your complete setup to another machine. Restoring a backup replaces the current Kobee Studio data after confirmation, so it is an exact restore rather than a merge.")
        note.Wrap(620)
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        export = ThemedActionButton(self.library_backup_page, "Create data backup…", lambda: self._export_library(None))
        imported = ThemedActionButton(self.library_backup_page, "Restore data backup…", lambda: self._import_library(None))
        actions.Add(export, 0, wx.RIGHT, 6)
        actions.Add(imported, 0)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT, 14)
        root.AddStretchSpacer(1)
        root.Add(wx.StaticLine(self.library_backup_page), 0, wx.EXPAND | wx.ALL, 14)
        warning = wx.StaticText(self.library_backup_page, label="Resetting removes every installed font, custom SVG, component preset, quick label, profile, preference, and hidden-item choice. Shipped defaults remain. This cannot be undone.")
        warning.Wrap(620)
        root.Add(warning, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(ThemedActionButton(self.library_backup_page, "Reset data to shipped defaults…", lambda: self._reset_library(None)), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        visibility_root = wx.BoxSizer(wx.VERTICAL)
        self.library_visibility_page.SetSizer(visibility_root)
        visibility_root.Add(self._heading(self.library_visibility_page, "Bundled library visibility"), 0, wx.ALL, 14)
        message = wx.StaticText(self.library_visibility_page, label="Hide only the shipped item you select. Linked quick labels remain available unless you explicitly hide those too.")
        message.Wrap(620)
        visibility_root.Add(message, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        visibility_tabs = wx.BoxSizer(wx.HORIZONTAL)
        self._visibility_kind = "Symbols"
        self.visibility_symbol_button = ThemedActionButton(
            self.library_visibility_page, "Symbols", lambda: self._select_visibility_kind("Symbols"), primary=True
        )
        self.visibility_label_button = ThemedActionButton(
            self.library_visibility_page, "Quick labels", lambda: self._select_visibility_kind("Quick labels")
        )
        visibility_tabs.Add(self.visibility_symbol_button, 0, wx.RIGHT, 6)
        visibility_tabs.Add(self.visibility_label_button, 0)
        visibility_root.Add(visibility_tabs, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        visibility_actions = wx.BoxSizer(wx.HORIZONTAL)
        self.hide_visibility_button = ThemedActionButton(self.library_visibility_page, "Hide selected", lambda: self._set_visibility(False))
        self.show_visibility_button = ThemedActionButton(self.library_visibility_page, "Show selected", lambda: self._set_visibility(True))
        visibility_actions.Add(self.hide_visibility_button, 0, wx.RIGHT, 6)
        visibility_actions.Add(self.show_visibility_button, 0)
        visibility_root.Add(visibility_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.visibility_list = ThemedListBox(self.library_visibility_page)
        self.visibility_list.Bind(wx.EVT_LISTBOX, self._on_visibility_selection)
        visibility_root.Add(self.visibility_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        self._refresh_visibility()

        info_root = wx.BoxSizer(wx.VERTICAL)
        self.info_page.SetSizer(info_root)
        info_root.Add(self._heading(self.info_page, "Kobee Studio"), 0, wx.ALL, 14)
        build = wx.StaticText(self.info_page, label="Version {}\nStable release".format(__version__))
        info_root.Add(build, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        help_text = wx.StaticText(self.info_page, label="Help and guides\nhttps://kobee.com.au/tutorials/kobee-studio-docs\n\nReport an issue or contribute\nhttps://github.com/mrcpuddington/kobeestudio")
        help_text.Wrap(620)
        info_root.Add(help_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

    def _export_library(self, event):
        if self._preferences_from_controls() != self._saved_preferences:
            choice = wx.MessageDialog(
                self,
                "You have unsaved application settings. Save them before creating the backup?",
                "Include unsaved settings",
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
            )
            try:
                choice.SetYesNoLabels("Save and back up", "Back up saved data")
                result = choice.ShowModal()
            finally:
                choice.Destroy()
            if result == wx.ID_CANCEL:
                return
            if result == wx.ID_YES and not self._save_preferences():
                return
        dialog = wx.FileDialog(
            self,
            "Create Kobee Studio data backup",
            defaultFile="kobee-studio-data-backup.zip",
            wildcard="Kobee Studio data backup (*.zip)|*.zip",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            count = export_library(self.preferences_store.root, Path(dialog.GetPath()))
            wx.MessageBox("Created a backup with {} data file(s).".format(count), "Data backup created", wx.OK | wx.ICON_INFORMATION, self)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            wx.MessageBox(str(error), "Could not create data backup", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _import_library(self, event):
        dialog = wx.FileDialog(self, "Restore Kobee Studio data backup", wildcard="Kobee Studio data backup (*.zip)|*.zip", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            if wx.MessageBox(
                "Restore this backup? It replaces your current Kobee Studio data, including fonts, preferences, custom SVGs, component presets, quick labels, profiles, and hidden-item choices. This cannot be undone.",
                "Replace Kobee Studio data",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                self,
            ) != wx.YES:
                return
            count = restore_library(Path(dialog.GetPath()), self.preferences_store.root)
            self.restart_editor = True
            wx.MessageBox("Restored {} data file(s). Kobee Studio will now restart to load the restored data.".format(count), "Data restored", wx.OK | wx.ICON_INFORMATION, self)
            self.EndModal(wx.ID_OK)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            wx.MessageBox(str(error), "Could not restore data backup", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _reset_library(self, event):
        if wx.MessageBox(
            "This removes all custom SVGs, quick labels, profiles, display preferences, and hidden-item choices. Bundled defaults remain. Continue?",
            "Reset Kobee Studio data",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            self,
        ) != wx.YES:
            return
        confirm = wx.TextEntryDialog(
            self,
            "Type RESET to permanently remove your custom Kobee Studio data.",
            "Confirm reset to shipped defaults",
        )
        try:
            if confirm.ShowModal() != wx.ID_OK or confirm.GetValue().strip() != "RESET":
                return
            reset_library(self.preferences_store.root)
            preferences = AppPreferences()
            self.preferences_store.save(preferences)
            self.preferences_changed(preferences)
            self.restart_editor = True
            wx.MessageBox("Kobee Studio data has been reset to shipped defaults. Kobee Studio will now restart.", "Data reset", wx.OK | wx.ICON_INFORMATION, self)
            self.EndModal(wx.ID_OK)
        except OSError as error:
            wx.MessageBox(str(error), "Could not reset Kobee Studio data", wx.OK | wx.ICON_ERROR, self)
        finally:
            confirm.Destroy()

    def _asset_store(self) -> SvgAssetStore:
        if self.scope_choice.GetStringSelection() == "This project" and self.project_asset_store is not None:
            return self.project_asset_store
        return self.global_asset_store

    def _asset_namespace(self) -> str:
        return "symbols" if self.namespace_choice.GetStringSelection() == "Icons" else "graphics"

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
        if hasattr(self, "upload_png_button"):
            self.upload_png_button.Enable(self._asset_namespace() == "graphics")
        self._update_upload_actions()

    def _on_upload_selection(self, event):
        self._update_upload_actions()
        event.Skip()

    def _update_upload_actions(self):
        if not hasattr(self, "edit_png_button"):
            return
        index = self.upload_list.GetSelection()
        asset = self._upload_items[index] if 0 <= index < len(self._upload_items) else None
        self.edit_png_button.Enable(
            asset is not None and self._asset_namespace() == "graphics"
            and self._asset_store().traced_png_details(asset) is not None
        )

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

    def _upload_png(self, event):
        picker = wx.FileDialog(self, "Choose a PNG to convert", wildcard="PNG files (*.png)|*.png", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        try:
            if picker.ShowModal() != wx.ID_OK: return
            source = Path(picker.GetPath())
        finally: picker.Destroy()
        converter = PngTraceDialog(self, source)
        try:
            if converter.ShowModal() != wx.ID_OK or converter.result is None: return
            result = converter.result
        finally: converter.Destroy()
        name_prompt = wx.TextEntryDialog(self, "Display name", "Save converted graphic", source.stem.replace("_", " ").title())
        try:
            if name_prompt.ShowModal() != wx.ID_OK: return
            from dataclasses import asdict
            self._asset_store().upload_traced_png(source, result.svg, name_prompt.GetValue(), asdict(result.settings))
            self._refresh_uploads(); self.restart_editor = True
        except (OSError, RuntimeError, ValueError) as error:
            wx.MessageBox(str(error), "Could not convert PNG", wx.OK | wx.ICON_ERROR, self)
        finally: name_prompt.Destroy()

    def _edit_png_trace(self, event):
        index = self.upload_list.GetSelection()
        if not 0 <= index < len(self._upload_items):
            return
        asset = self._upload_items[index]
        details = self._asset_store().traced_png_details(asset)
        if details is None:
            wx.MessageBox("The selected graphic was not created from a retained PNG.", "PNG trace", wx.OK | wx.ICON_INFORMATION, self)
            return
        source, raw_settings = details
        try:
            settings = RasterTraceSettings(**dict(raw_settings))
        except (TypeError, ValueError) as error:
            wx.MessageBox(str(error), "Could not reopen PNG trace", wx.OK | wx.ICON_ERROR, self)
            return
        converter = PngTraceDialog(self, source, settings)
        try:
            if converter.ShowModal() != wx.ID_OK or converter.result is None:
                return
            from dataclasses import asdict
            self._asset_store().update_traced_png(asset, converter.result.svg, asdict(converter.result.settings))
            self._refresh_uploads()
            for row, item in enumerate(self._upload_items):
                if item.asset_id == asset.asset_id:
                    self.upload_list.SetSelection(row)
                    break
            self.restart_editor = True
            self._update_upload_actions()
        except (OSError, RuntimeError, ValueError) as error:
            wx.MessageBox(str(error), "Could not update PNG trace", wx.OK | wx.ICON_ERROR, self)
        finally:
            converter.Destroy()

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

    def _preferences_from_controls(self):
        appearance = {
            "Follow system": "system",
            "Light": "light",
            "Dark": "dark",
        }[self.appearance_choice.GetStringSelection()]
        unit = MeasurementUnit.MILS if self.unit_choice.GetStringSelection() == "Mils (mil)" else MeasurementUnit.MILLIMETRES
        return AppPreferences(
            appearance=appearance,
            measurement_unit=unit,
            hidden_symbol_ids=tuple(self._hidden_symbol_ids),
            hidden_label_ids=tuple(self._hidden_label_ids),
        )

    def _save_preferences(self):
        preferences = self._preferences_from_controls()
        try:
            self.preferences_store.save(preferences)
            self.preferences_changed(preferences)
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not save settings", wx.OK | wx.ICON_ERROR, self)
            return False
        self._saved_preferences = preferences
        return True

    def _on_ok(self, event=None):
        if not self._save_preferences():
            return
        self.EndModal(wx.ID_OK)

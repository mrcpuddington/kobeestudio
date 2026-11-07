"""Kobee Studio 2.0 editor shell.

This editor intentionally does not inherit or rearrange the retained
wxFormBuilder/KiBuzzard dialog.  Every window is created under its final parent
and attached to one sizer for its entire lifetime, which keeps the UI stable on
Windows while giving each artwork tool a focused page.
"""

from __future__ import annotations

import base64
import json
import math
import re
import traceback
import threading
from pathlib import Path

import wx

from ..core.app_preferences import AppPreferences, AppPreferencesStore
from ..core.composition import DocumentStyle, GraphicObject, Padding, Point, ShapeStyle, Size, TypographyStyle
from ..core.component_callout import ComponentCalloutSpec
from ..core.component_presets import ComponentPresetStore
from ..core.font_library import FontLibraryStore
from ..core.icon_catalog import render_symbol
from ..core.machine_codes import (
    CODE128_DEFAULT_HEIGHT_MM,
    CODE128_DEFAULT_MODULE_MM,
    CODE128_MIN_HEIGHT_MM,
    CODE128_MIN_MODULE_MM,
    QR_MIN_MODULE_MM,
)
from ..core.measurement_units import MeasurementUnit, from_millimetres, to_millimetres
from ..core.pin_header import HEADER_PITCH_CHOICES, PinHeaderSpec, maximum_pin_label_height
from ..core.project_data import (
    ProjectData,
    ProjectDataCatalog,
    ProjectDataCatalogStore,
    ProjectDataConflictError,
    ProjectDataRecoveryError,
    ProjectDataStore,
    generated_variables,
    merge_kicad_variables,
)
from ..core.settings_profiles import SettingsProfileStore, profile_module_for_mode
from ..core.studio_artwork import (
    PLACEMENT_ANCHORS,
    TextVectorizer,
    render_component_callout_artwork,
    render_header_artwork,
    render_graphic_artwork,
    render_label_artwork,
    render_multipart_label_artwork,
    render_machine_code_artwork,
    with_placement_anchor,
)
from ..core.svg_symbols import (
    SvgAssetStore,
    format_symbol_reference,
    parse_symbol_reference,
    render_svg,
    svg_import_repair_advice,
    symbol_catalog_for_context,
)
from ..core.quick_labels import QuickLabelStore
from ..core.variable_templates import (
    VariableTemplateStore,
    expand_variable_template,
    multipart_sections,
    validate_variable_template,
    variable_names,
)
from ..core.legacy_adapter import build_footprint_payload
from ..core.transforms import (
    BOTTOM_COPPER,
    BOTTOM_MASK,
    BOTTOM_SILKSCREEN,
    FRONT_COPPER,
    FRONT_MASK,
    FRONT_SILKSCREEN,
    fit_preview_polygons,
    is_bottom,
    preview_polygons,
)
from ..version import __version__
from .asset_picker import AssetPickerDialog, icon_picker_items, label_picker_items
from .async_dialog import AsyncDialog
from .settings_dialog import PngTraceDialog, SettingsDialog
from .project_data_ui import ProjectDataPage
from ..integration.ipc_artwork import IpcArtworkPlacement, METADATA_FIELD_NAME, decode_metadata
from .theme import apply_native_theme, is_dark_mode, set_appearance_preference
from .themed_controls import (
    ThemedCheckBox,
    ThemedChoice,
    ThemedListBox,
    ThemedSpinCtrl,
    ThemedSpinCtrlDouble,
    ThemedTextButton,
)
from .main_dialog import (
    CAP_LABELS,
    cap_style_id,
    COMPONENT_ARRAY_ORIENTATION_LABELS,
    COMPONENT_CUTOUT_ID_TO_LABEL,
    COMPONENT_CUTOUT_LABELS,
    COMPONENT_POSITION_LABELS,
    COMPONENT_PRESET_BY_LABEL,
    COMPONENT_PRESET_LABELS,
    COMPONENT_SHAPE_LABELS,
    CONTINUOUS_CUTOUT_CHOICES,
    CONTENT_LAYOUT_LABELS,
    DEFAULT_LABEL_DIMENSIONS,
    HEADER_CAP_LABELS,
    HEADER_CUTOUT_SHAPES,
    HEADER_SHAPE_LABELS,
    ICON_ID_TO_LABEL,
    ICON_LABELS,
    ICON_POSITION_LABELS,
    INDIVIDUAL_CUTOUT_CHOICES,
    LABEL_SHAPE_LABELS,
    LAYER_LABELS,
    LAYER_ORDER,
    MATCH_MAIN_TYPEFACE,
    MODE_DEFAULTS,
    OPENING_LABELS,
    PIN_SIDE_TO_LABEL_SIDE,
    PRESET_BY_ID,
    PRESET_ID_TO_LABEL,
    QR_PRESENTATION_LABELS,
    STUDIO_DEFAULTS,
    STUDIO_DEFAULTS_VERSION,
    STUDIO_DIMENSIONS_VERSION,
    VARIANT_LABELS,
    _subtitle_font_name,
    mode_defaults,
)


KOBEE_STUDIO_DOCS_URL = "https://kobee.com.au/tutorials/kobee-studio-docs"
ACCENT = wx.Colour(235, 177, 20)
ACCENT_TEXT = wx.Colour(48, 36, 4)
PREVIEW_LAYER_LABELS = {
    "F.SilkS": "Front silk",
    "B.SilkS": "Back silk",
    "F.Mask": "Front mask",
    "B.Mask": "Back mask",
    "F.Cu": "Front copper",
    "B.Cu": "Back copper",
}
TARGET_LAYER_LABELS = {
    FRONT_SILKSCREEN: "Front silk",
    BOTTOM_SILKSCREEN: "Back silk",
    FRONT_COPPER: "Front copper",
    BOTTOM_COPPER: "Back copper",
    FRONT_MASK: "Front mask",
    BOTTOM_MASK: "Back mask",
}
MODULE_LABELS_FOR_PROFILE = {
    "labels": "Label",
    "pin_headers": "Header overlay",
    "component_callouts": "Component callout",
    "component_arrays": "Component array",
    "machine_codes": "QR code or barcode",
    "graphics": "Imported graphic",
    "board_tools": "Board tools",
}

TOOL_DEFINITIONS = (
    ("labels", "Standard", "Label"),
    ("labels", "Connector Overlay", "2.54 mm Pin Header"),
    ("labels", "Component Callout", "Component Callout"),
    ("labels", "Component Array", "Component Array"),
    # Variable templates are intentionally the final Labels tab.
    ("labels", "Variables", "Label"),
    ("codes", "QR Code", "QR / Barcode"),
    ("codes", "Barcode", "QR / Barcode"),
    ("graphics", "Imported Graphic", "Imported Graphic"),
    ("board_tools", "Cleanup", "Board Tools"),
    # Designators use the standard label renderer while remaining in the
    # Board Tools family.  This lets the main window own the complete style
    # form and exact live preview without a second modal editor.
    ("board_tools", "Designators", "Label"),
    ("project_data", "Project Data", "Project Data"),
)

MEASUREMENT_SETTING_KEYS = frozenset(
    (
        "BorderThicknessCtrl", "ComponentArrayPitchCtrl", "ComponentClearanceCtrl",
        "ComponentCutoutRadiusCtrl", "ComponentHeightCtrl", "ComponentMinHeightCtrl",
        "ComponentMinWidthCtrl", "ComponentTextGapCtrl", "ComponentWidthCtrl",
        "CornerRadiusCtrl", "FeatureSizeCtrl", "HeaderCrossSizeCtrl",
        "HeaderLabelOuterPaddingCtrl", "HeaderLabelPaddingCtrl", "HeaderLeadingPaddingCtrl",
        "HeaderOpeningEndPaddingCtrl", "HeaderPadClearanceCtrl", "HeaderPinOuterPaddingCtrl",
        "HeaderPinToLabelGapCtrl", "HeaderTrailingPaddingCtrl", "HeaderCutoutRadiusCtrl", "HeightCtrl", "IconGapCtrl",
        "IconHeightCtrl", "MachineCodeBarHeightCtrl", "MachineCodeCaptionHeightCtrl",
        "MachineCodeContentGapCtrl", "MachineCodeContentHeightCtrl", "MachineCodeFramePaddingCtrl",
        "MachineCodeModuleSizeCtrl", "PaddingBottomCtrl", "PaddingLeftCtrl", "PaddingRightCtrl",
        "PaddingTopCtrl", "SubtitleGapCtrl", "SubtitleHeightCtrl", "UnderlineGapCtrl",
        "UnderlineThicknessCtrl", "WidthCtrl",
        "GraphicWidthCtrl", "GraphicHeightCtrl", "GraphicOffsetXCtrl", "GraphicOffsetYCtrl",
        "HeaderCustomPitchCtrl",
        "NativeTextWidthCtrl", "NativeStrokeWidthCtrl",
        "MultiPartGapCtrl", "MultiPartSeparatorDepthCtrl",
        "MultiPartStartLeftPaddingCtrl", "MultiPartStartRightPaddingCtrl",
        "MultiPartMiddleLeftPaddingCtrl", "MultiPartMiddleRightPaddingCtrl",
        "MultiPartEndLeftPaddingCtrl", "MultiPartEndRightPaddingCtrl",
        "OverlineGapCtrl", "OverlineThicknessCtrl",
    )
)


def _palette():
    dark = is_dark_mode(wx)
    values = {
        "window": (25, 24, 23) if dark else (239, 239, 237),
        "title": (33, 31, 28) if dark else (246, 246, 244),
        "subnav": (41, 39, 36) if dark else (231, 231, 228),
        "controls": (28, 27, 25) if dark else (238, 238, 235),
        "card": (38, 36, 33) if dark else (248, 248, 246),
        # The preview panel deliberately shares the workspace background.  The
        # rounded dotted canvas is the only preview surface, not a card inside
        # another competing card.
        "preview": (28, 27, 25) if dark else (238, 238, 235),
        "canvas": (31, 38, 35) if dark else (234, 231, 222),
        "border": (61, 57, 51) if dark else (221, 221, 218),
        "text": (245, 242, 236) if dark else (34, 33, 30),
        "muted": (179, 173, 163) if dark else (113, 108, 100),
        "active": (71, 66, 58) if dark else (255, 255, 253),
    }
    return {key: wx.Colour(*value) for key, value in values.items()}


def _active_board_path(editor_session=None):
    """Resolve the saved board path in IPC and retained SWIG runtimes."""
    try:
        if editor_session is not None:
            name = getattr(getattr(editor_session, "board", None), "name", "")
        else:
            import pcbnew

            board = pcbnew.GetBoard()
            name = board.GetFileName() if board is not None else ""
        path = Path(str(name)).expanduser() if name else None
        if (
            path is None
            or not path.is_absolute()
            or path.suffix.lower() not in (".kicad_pcb", ".brd")
        ):
            return None
        return path
    except Exception:
        # Project-only storage is optional; a transient board-name API failure
        # must not prevent the editor or global settings from opening.
        return None


def _active_project_path(editor_session=None):
    """Resolve the active saved ``.kicad_pro`` without guessing from UI state.

    KiCad's IPC board wrapper does not reliably expose a board filename, but
    it does expose the owning Project. Prefer that authoritative document;
    fall back to a neighbouring project file for the legacy PCB API.
    """
    def as_project_file(value, project_name=""):
        if not value:
            return None
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            return None
        if path.suffix.lower() == ".kicad_pro":
            return path if path.is_file() else None
        # kicad-python may return the project directory while exposing the
        # short project name separately.
        if not path.suffix and project_name:
            name = Path(str(project_name)).name
            if name:
                candidate = path / (name if name.lower().endswith(".kicad_pro") else name + ".kicad_pro")
                return candidate if candidate.is_file() else None
        return None

    try:
        if editor_session is not None:
            board = getattr(editor_session, "board", None)
            get_project = getattr(board, "get_project", None)
            if callable(get_project):
                project = get_project()
                path = as_project_file(
                    getattr(project, "path", ""), getattr(project, "name", ""),
                )
                if path is not None:
                    return path
        else:
            import pcbnew

            board = pcbnew.GetBoard()
            get_project = getattr(board, "GetProject", None) if board is not None else None
            if callable(get_project):
                project = get_project()
                for method_name in ("GetProjectFullName", "GetProjectFileName"):
                    method = getattr(project, method_name, None)
                    if callable(method):
                        path = as_project_file(method())
                        if path is not None:
                            return path
        board_path = _active_board_path(editor_session)
        if board_path is not None:
            candidate = board_path.with_suffix(".kicad_pro")
            if candidate.is_file():
                return candidate
    except Exception:
        # Falling back to the disabled Project Data page is safer than
        # associating metadata with an unknown project after an IPC failure.
        return None
    return None


class BrandedHeader(wx.Panel):
    """A quiet brand wash that keeps the editor chrome feeling lightweight."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(_palette()["title"])
        self.SetMinSize(wx.Size(-1, 56))
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, event):
        palette = _palette()
        dc = wx.AutoBufferedPaintDC(self)
        rect = self.GetClientRect()
        dark = is_dark_mode(wx)
        warm = wx.Colour(48, 42, 28) if dark else wx.Colour(247, 243, 232)
        dc.GradientFillLinear(rect, palette["title"], warm, wx.EAST)
        dc.SetPen(wx.Pen(ACCENT, 2))
        dc.DrawLine(0, rect.height - 1, rect.width, rect.height - 1)


class KobeeTab(wx.Control):
    """Compact, consistently painted navigation tab for macOS and Windows."""

    def __init__(self, parent, label, callback, kind="sub", icon=None):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetLabel(label)
        self.callback = callback
        self.kind = kind
        self.icon = icon
        self.active = False
        self.hovered = False
        width, height = parent.GetTextExtent(label)
        if kind == "side":
            self._best_size = wx.Size(112, 38)
        else:
            icon_width = 20 if icon else 0
            self._best_size = wx.Size(
                width + icon_width + (28 if kind == "family" else 24), 38
            )
        self.SetInitialSize(self._best_size)
        self.SetMinSize(self._best_size)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._activate)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    def DoGetBestSize(self):
        return self._best_size

    def set_active(self, active):
        self.active = bool(active)
        self.Refresh(False)

    def _activate(self, event):
        self.callback()

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN):
            self.callback()
        else:
            event.Skip()

    def _on_enter(self, event):
        self.hovered = True
        self.Refresh(False)

    def _on_leave(self, event):
        self.hovered = False
        self.Refresh(False)

    def _on_paint(self, event):
        palette = _palette()
        dc = wx.AutoBufferedPaintDC(self)
        background = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        rect = self.GetClientRect()
        if self.kind in ("sub", "side") and (self.active or self.hovered):
            colour = palette["active"] if self.active else palette["card"]
            dc.SetPen(wx.Pen(palette["border"]))
            dc.SetBrush(wx.Brush(colour))
            dc.DrawRoundedRectangle(rect.Deflate(1), 8)
        dc.SetFont(self.GetFont().Bold())
        dc.SetTextForeground(palette["text"] if self.active else palette["muted"])
        alignment = wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL if self.kind == "side" or self.icon else wx.ALIGN_CENTER
        if self.kind == "side":
            label_rect = wx.Rect(rect.x + 12, rect.y, rect.width - 16, rect.height)
        elif self.icon:
            text_width, _ = dc.GetTextExtent(self.GetLabel())
            group_width = text_width + 20
            group_x = rect.x + max(6, (rect.width - group_width) // 2)
            self._draw_icon(dc, group_x, rect.y + (rect.height - 14) // 2)
            label_rect = wx.Rect(group_x + 20, rect.y, text_width + 2, rect.height)
        else:
            label_rect = rect
        dc.DrawLabel(self.GetLabel(), label_rect, alignment)
        if self.active:
            dc.SetPen(wx.Pen(ACCENT, 3))
            if self.kind == "side":
                dc.DrawLine(3, 8, 3, rect.height - 8)
            else:
                y = rect.height - (3 if self.kind == "family" else 4)
                inset = 10 if self.kind == "sub" else 6
                dc.DrawLine(inset, y, rect.width - inset, y)

    def _draw_icon(self, dc, x, y):
        palette = _palette()
        dc.SetPen(wx.Pen(palette["text"] if self.active else palette["muted"], 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        if self.icon == "labels":
            dc.DrawRoundedRectangle(x, y + 1, 15, 11, 3)
            dc.DrawLine(x + 4, y + 5, x + 11, y + 5)
            dc.DrawLine(x + 4, y + 8, x + 9, y + 8)
        elif self.icon == "codes":
            for row in range(2):
                for column in range(2):
                    dc.DrawRectangle(x + column * 7, y + row * 7, 5, 5)


class KobeeAction(wx.Control):
    """Painted action button so the primary colour is stable across themes."""

    def __init__(self, parent, label, callback, primary=False):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetLabel(label)
        self.callback = callback
        self.primary = primary
        self.hovered = False
        self.SetInitialSize(self._best_size)
        self.SetMinSize(self._best_size)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_SET_FOCUS, lambda event: (self.Refresh(False), event.Skip()))
        self.Bind(wx.EVT_KILL_FOCUS, lambda event: (self.Refresh(False), event.Skip()))
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    def DoGetBestSize(self):
        return self._best_size

    def SetLabel(self, label):
        super().SetLabel(str(label))
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont().Bold())
        width, _height = dc.GetTextExtent(str(label))
        self._best_size = wx.Size(width + 30, 36)
        self.SetMinSize(self._best_size)
        self.InvalidateBestSize()
        if self.GetParent().GetSizer():
            self.GetParent().Layout()
        self.Refresh(False)

    def _on_click(self, event):
        if self.IsEnabled():
            self.SetFocus()
            self.callback()

    def Enable(self, enable=True):
        result = super().Enable(enable)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND if enable else wx.CURSOR_ARROW))
        self.Refresh(False)
        return result

    def _on_key(self, event):
        if self.IsEnabled() and event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN):
            self.callback()
        else:
            event.Skip()

    def _on_enter(self, event):
        self.hovered = True
        self.Refresh(False)

    def _on_leave(self, event):
        self.hovered = False
        self.Refresh(False)

    def _on_paint(self, event):
        palette = _palette()
        dc = wx.AutoBufferedPaintDC(self)
        background = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        rect = self.GetClientRect().Deflate(1)
        fill = ACCENT if self.primary else palette["active"]
        if not self.IsEnabled():
            fill = palette["subnav"]
        elif self.hovered and self.primary:
            fill = wx.Colour(246, 189, 32)
        dc.SetPen(wx.Pen(wx.Colour(204, 146, 0) if self.primary else palette["border"]))
        dc.SetBrush(wx.Brush(fill))
        dc.DrawRoundedRectangle(rect, 9)
        dc.SetFont(self.GetFont().Bold())
        dc.SetTextForeground(palette["muted"] if not self.IsEnabled() else ACCENT_TEXT if self.primary else palette["text"])
        dc.DrawLabel(self.GetLabel(), self.GetClientRect(), wx.ALIGN_CENTER)
        if self.HasFocus():
            dc.SetPen(wx.Pen(palette["text"], 1, wx.PENSTYLE_SHORT_DASH))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRoundedRectangle(self.GetClientRect().Deflate(4), 6)


class SettingsCard(wx.Panel):
    """Soft neutral settings card matching the approved mockup."""

    def __init__(self, parent, title):
        super().__init__(parent, style=wx.BORDER_NONE | wx.CLIP_CHILDREN)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        palette = _palette()
        self.SetBackgroundColour(palette["card"])
        self.Bind(wx.EVT_PAINT, self._on_paint)
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)
        # Ampersands are mnemonic markers in wx on Windows, so spell them out
        # in headings instead of letting e.g. "OPENING & SPACING" lose a word.
        heading = wx.StaticText(self, label=title.replace("&", "and").upper())
        # Windows can otherwise blend a transparent StaticText label into a
        # custom-painted card while resizing.  Give the heading a concrete,
        # high-contrast surface of its own.
        heading.SetBackgroundColour(palette["card"])
        heading.SetForegroundColour(palette["text"])
        font = heading.GetFont().Bold()
        font.SetPointSize(max(8, font.GetPointSize() - 1))
        heading.SetFont(font)
        root.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 11)
        self.body = wx.BoxSizer(wx.VERTICAL)
        root.Add(self.body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 11)

    def _on_paint(self, event):
        palette = _palette()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        dc.SetPen(wx.Pen(palette["border"]))
        dc.SetBrush(wx.Brush(palette["card"]))
        dc.DrawRoundedRectangle(self.GetClientRect().Deflate(1), 11)


class RoundedTextField(wx.Panel):
    """Rounded field chrome around a native wx text editor."""

    def __init__(self, parent, value="", multiline=False):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._multiline = multiline
        style = wx.BORDER_NONE
        if multiline:
            # Header and array editors can contain dozens of rows. A native
            # vertical scrollbar keeps the caret visible beyond the fixed
            # six-line viewport on Windows.
            style |= wx.TE_MULTILINE | wx.VSCROLL
        self.editor = wx.TextCtrl(self, value=value, style=style)
        self.editor.SetOwnBackgroundColour(_palette()["active"])
        self.editor.SetBackgroundColour(_palette()["active"])
        self.editor.SetOwnForegroundColour(_palette()["text"])
        self.editor.SetForegroundColour(_palette()["text"])
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)
        root.Add(self.editor, 1, wx.EXPAND | wx.ALL, 7)
        self.SetMinSize(wx.Size(104, 66 if multiline else 32))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.editor.Bind(wx.EVT_TEXT, self._relay_text)

    def GetValue(self):
        return self.editor.GetValue()

    def SetValue(self, value):
        self.editor.SetValue(str(value))

    def ChangeValue(self, value):
        self.editor.ChangeValue(str(value))

    def WriteText(self, value):
        self.editor.WriteText(str(value))

    def SetMaxLength(self, length):
        self.editor.SetMaxLength(int(length))

    def SetHint(self, value):
        """Expose wx.TextCtrl's placeholder API through the rounded wrapper."""
        setter = getattr(self.editor, "SetHint", None)
        if callable(setter):
            setter(str(value))

    def ShowEnd(self):
        self.editor.ShowPosition(self.editor.GetLastPosition())

    def SetFocus(self):
        return self.editor.SetFocus()

    def _relay_text(self, event):
        command = wx.CommandEvent(wx.EVT_TEXT.typeId, self.GetId())
        command.SetEventObject(self)
        # Do not recurse through the wrapper's handlers from a native Windows
        # text callback. Queue one command event for the normal wx event loop.
        wx.PostEvent(self, command)
        # Do not swallow the original native event. Some Cocoa text-edit
        # paths dispatch it before the queued wrapper event, which otherwise
        # makes live previews appear to update only after another control is
        # used.
        event.Skip()

    def _on_paint(self, event):
        palette = _palette()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        dc.SetPen(wx.Pen(palette["border"]))
        dc.SetBrush(wx.Brush(palette["active"]))
        dc.DrawRoundedRectangle(self.GetClientRect().Deflate(1), 8)


class SegmentedChoice(wx.Control):
    """Small painted choice used for short visual options."""

    def __init__(self, parent, choices, value, rows=1):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.choices = tuple(choices)
        self.rows = 2 if rows == 2 and len(self.choices) == 3 else 1
        self.selection = max(0, self.choices.index(value) if value in self.choices else 0)
        minimum_width = 150 if self.rows == 2 else max(124, len(self.choices) * 60)
        self.SetMinSize(wx.Size(minimum_width, 64 if self.rows == 2 else 32))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def GetStringSelection(self):
        return self.choices[self.selection]

    def SetStringSelection(self, value):
        if value not in self.choices:
            return False
        self.selection = self.choices.index(value)
        self.Refresh(False)
        return True

    def _select(self, index):
        index = max(0, min(len(self.choices) - 1, index))
        if index == self.selection:
            return
        self.selection = index
        self.Refresh(False)
        command = wx.CommandEvent(wx.EVT_CHOICE.typeId, self.GetId())
        command.SetEventObject(self)
        wx.PostEvent(self, command)

    def _on_click(self, event):
        point = event.GetPosition()
        for index, rect in enumerate(self._segment_rects(self.GetClientSize())):
            if rect.Contains(point):
                self._select(index)
                break

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_LEFT, wx.WXK_UP):
            self._select(self.selection - 1)
        elif event.GetKeyCode() in (wx.WXK_RIGHT, wx.WXK_DOWN):
            self._select(self.selection + 1)
        else:
            event.Skip()

    def _on_paint(self, event):
        palette = _palette()
        dc = wx.AutoBufferedPaintDC(self)
        background = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        size = self.GetClientSize()
        for index, (label, rect) in enumerate(
            zip(self.choices, self._segment_rects(size))
        ):
            rect = wx.Rect(rect).Deflate(1)
            selected = index == self.selection
            dc.SetPen(wx.Pen(wx.Colour(204, 146, 0) if selected else palette["border"]))
            dc.SetBrush(wx.Brush(ACCENT if selected else palette["card"]))
            dc.DrawRoundedRectangle(rect, 7)
            dc.SetTextForeground(ACCENT_TEXT if selected else palette["text"])
            dc.DrawLabel(label.replace(" fill", ""), rect, wx.ALIGN_CENTER)

    def _segment_rects(self, size):
        if self.rows == 2:
            top_height = size.height // 2
            half_width = size.width // 2
            return (
                wx.Rect(0, 0, half_width, top_height),
                wx.Rect(half_width, 0, size.width - half_width, top_height),
                wx.Rect(0, top_height, size.width, size.height - top_height),
            )
        segment_width = size.width / max(1, len(self.choices))
        return tuple(
            wx.Rect(
                int(round(index * segment_width)),
                0,
                max(
                    1,
                    int(round((index + 1) * segment_width))
                    - int(round(index * segment_width)),
                ),
                size.height,
            )
            for index in range(len(self.choices))
        )


def _control_value(control):
    if isinstance(control, (wx.Choice, ThemedChoice, PickerButton, SegmentedChoice)):
        return control.GetStringSelection()
    return control.GetValue()


def _set_control_value(control, value):
    if isinstance(control, (wx.Choice, ThemedChoice, PickerButton, SegmentedChoice)):
        if not control.SetStringSelection(str(value)) and hasattr(control, "GetCount"):
            if control.GetCount():
                control.SetSelection(0)
    elif isinstance(control, (wx.CheckBox, ThemedCheckBox)):
        control.SetValue(bool(value))
    elif isinstance(control, (wx.SpinCtrlDouble, ThemedSpinCtrlDouble)):
        control.SetValue(float(value))
    elif isinstance(control, (wx.SpinCtrl, ThemedSpinCtrl)):
        control.SetValue(int(float(value)))
    else:
        control.SetValue(str(value))


class PickerButton(wx.Control):
    """A compact library tile: it is an action, never a fake dropdown."""

    def __init__(self, parent, empty_label, value="", kind="label", callback=None, symbol_catalog=None):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.empty_label = empty_label
        self.value = value
        self.kind = kind
        self.callback = callback
        self.symbol_catalog = symbol_catalog
        self.symbol_reference = ""
        self.hovered = False
        self._pressed = False
        self.SetMinSize(wx.Size(104, 32))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self._refresh_label()

    def _refresh_label(self):
        label = str(self.value or self.empty_label)
        if self.kind == "symbol" and label == "No icon":
            label = self.empty_label
        if self.kind == "preset" and label == "Custom label":
            label = self.empty_label
        if len(label) > 28:
            label = label[:27].rstrip() + "…"
        self.SetLabel(label)
        self.Refresh(False)

    def _emit_button(self, event=None):
        if self.callback is not None:
            # On Cocoa, entering a modal dialog directly from a painted
            # control's mouse-up event can be discarded. Deferring until the
            # click finishes keeps both library pickers dependable.
            wx.CallAfter(self.callback, None)

    def _on_left_down(self, event):
        self._pressed = True
        if not self.HasCapture():
            self.CaptureMouse()
        self.Refresh(False)
        event.Skip()

    def _on_left_up(self, event):
        clicked = self._pressed and self.GetClientRect().Contains(event.GetPosition())
        self._pressed = False
        if self.HasCapture():
            self.ReleaseMouse()
        self.Refresh(False)
        if clicked:
            self._emit_button(event)
        event.Skip()

    def _on_capture_lost(self, event):
        self._pressed = False
        self.Refresh(False)
        event.Skip()

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN):
            self._emit_button()
        else:
            event.Skip()

    def _on_enter(self, event):
        self.hovered = True
        self.Refresh(False)

    def _on_leave(self, event):
        self.hovered = False
        self.Refresh(False)

    def _on_paint(self, event):
        palette = _palette()
        dc = wx.AutoBufferedPaintDC(self)
        background = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        rect = self.GetClientRect().Deflate(1)
        dc.SetPen(wx.Pen(ACCENT if self.hovered else palette["border"]))
        dc.SetBrush(wx.Brush(palette["active"]))
        dc.DrawRoundedRectangle(rect, 8)
        label_left = rect.x + 10
        if self.kind == "symbol":
            asset_id = self.symbol_reference or ICON_LABELS.get(self.value, "")
            icon_box = wx.Rect(rect.x + 8, rect.y + 7, 18, 18)
            if asset_id:
                AssetPickerDialog._draw_icon(
                    dc,
                    asset_id,
                    (icon_box.x, icon_box.y, icon_box.width, icon_box.height),
                    palette["text"],
                    self.symbol_catalog,
                )
            else:
                dc.SetPen(wx.Pen(palette["muted"], 1))
                dc.SetBrush(wx.TRANSPARENT_BRUSH)
                dc.DrawRoundedRectangle(icon_box, 4)
                dc.DrawLine(icon_box.x + 5, icon_box.y + 9, icon_box.x + 13, icon_box.y + 9)
                dc.DrawLine(icon_box.x + 9, icon_box.y + 5, icon_box.x + 9, icon_box.y + 13)
            label_left = icon_box.GetRight() + 8
        dc.SetTextForeground(palette["text"])
        label_rect = wx.Rect(label_left, rect.y, max(0, rect.width - (label_left - rect.x) - 52), rect.height)
        dc.DrawLabel(self.GetLabel(), label_rect, wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL)
        dc.SetTextForeground(ACCENT if self.hovered else palette["muted"])
        dc.DrawLabel(
            "Open",
            wx.Rect(rect.x + rect.width - 40, rect.y, 33, rect.height),
            wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL,
        )

    def GetStringSelection(self):
        return self.value

    def SetStringSelection(self, value):
        self.value = str(value)
        self._refresh_label()
        return True


class ProfileRecallDialog(wx.Dialog):
    """Small chooser with an explicit apply step for tool profiles."""

    def __init__(self, parent, module_label, profiles, selected_id=None):
        super().__init__(parent, title="Load {} profile".format(module_label), style=wx.DEFAULT_DIALOG_STYLE)
        self._profiles = tuple(profiles)
        self.selected_profile_id = ""
        palette = _palette()
        self.SetBackgroundColour(palette["window"])
        root = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label="Load a {} profile".format(module_label))
        heading.SetFont(heading.GetFont().Bold())
        heading.SetForegroundColour(palette["text"])
        root.Add(heading, 0, wx.ALL, 14)
        helper = wx.StaticText(self, label="Choose a saved profile, then apply it to this tool. None keeps the current settings without an active profile.")
        helper.SetForegroundColour(palette["muted"])
        helper.Wrap(440)
        root.Add(helper, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="Profile"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._profile_ids = ("",) + tuple(profile.profile_id for profile in self._profiles)
        self.choice = ThemedChoice(
            self,
            choices=("None",) + tuple(profile.name for profile in self._profiles),
        )
        self.choice.SetMinSize(wx.Size(300, 30))
        if selected_id in self._profile_ids:
            self.choice.SetSelection(self._profile_ids.index(selected_id))
        row.Add(self.choice, 1, wx.EXPAND)
        root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer(1)
        buttons.Add(KobeeAction(self, "Cancel", lambda: self.EndModal(wx.ID_CANCEL)), 0, wx.RIGHT, 7)
        buttons.Add(KobeeAction(self, "Apply", self._apply, primary=True), 0)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 14)
        self.SetSizer(root)
        # A 210 px outer height leaves only 171 px of client space on Windows,
        # which squeezes this final action row down to a thin, unusable strip.
        self.Fit()
        best_size = self.GetSize()
        self.SetMinSize(wx.Size(max(470, best_size.width), best_size.height))
        self.SetSize(wx.Size(max(500, best_size.width), best_size.height))

    def _apply(self):
        index = self.choice.GetSelection()
        self.selected_profile_id = self._profile_ids[index] if 0 <= index < len(self._profile_ids) else ""
        self.EndModal(wx.ID_OK)


class PreviewCanvas(wx.Panel):
    """Buffered, zoomable preview that paints only cached device geometry."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundColour(_palette()["controls"])
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._filled = ()
        self._strokes = ()
        self._guides = ()
        self._layer = FRONT_SILKSCREEN
        self._error = None
        self._zoom = 1.0
        self._pan = wx.Point(0, 0)
        self._drag_anchor = None
        self._transform_handler = None
        self._transform_graphic = None
        self._transform_mode = None
        self._transform_start = None
        self._transform_bounds = None
        self._transform_corners = ()
        self._rotation_handle = None
        self._preview_scale = 1.0
        self._preview_centre = (0.0, 0.0)
        self._anchor = None
        self._cache = ((), (), ())
        self._size_timer = wx.Timer(self)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_TIMER, self._on_size_timer, self._size_timer)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_left_up)

    def set_artwork(self, filled, strokes, guides, layer, error=None):
        self._size_timer.Stop()
        self._filled = tuple(tuple(poly) for poly in filled)
        self._strokes = tuple(tuple(stroke.points) for stroke in strokes)
        self._guides = tuple(tuple(poly) for poly in guides)
        self._layer = layer
        self._error = error
        self._anchor = None
        self._rebuild_cache()
        self.Refresh(False)

    def set_transform_handler(self, graphic=None, callback=None):
        self._transform_graphic = graphic
        self._transform_handler = callback
        if callback is None:
            self._transform_mode = None
            self._transform_start = None
        self._update_transform_geometry()
        self.Refresh(False)

    def _world_to_device(self, point):
        x = -point.x if is_bottom(self._layer) else point.x
        centre_x, centre_y = self._preview_centre
        return wx.Point2D((x - centre_x) * self._preview_scale, (point.y - centre_y) * self._preview_scale)

    def _update_transform_geometry(self):
        graphic = self._transform_graphic
        if graphic is None or self._transform_handler is None:
            self._transform_corners = (); self._rotation_handle = None; return
        half_width, half_height = graphic.size.width / 2.0, graphic.size.height / 2.0
        angle = math.radians(graphic.rotation_deg); cosine, sine = math.cos(angle), math.sin(angle)
        corners = []
        for x, y in ((-half_width,-half_height),(half_width,-half_height),(half_width,half_height),(-half_width,half_height)):
            corners.append(self._world_to_device(Point(x*cosine-y*sine+graphic.position.x, x*sine+y*cosine+graphic.position.y)))
        self._transform_corners = tuple(corners)
        top_x = (corners[0].x + corners[1].x) / 2.0; top_y = (corners[0].y + corners[1].y) / 2.0
        centre = self._world_to_device(graphic.position)
        dx, dy = top_x-centre.x, top_y-centre.y; length=max(0.001,math.hypot(dx,dy))
        self._rotation_handle = wx.Point2D(top_x+dx/length*24, top_y+dy/length*24)

    def _local_mouse(self, position):
        size = self.GetClientSize()
        return wx.Point2D((position.x - size.width / 2 - self._pan.x) / self._zoom,
                          (position.y - size.height / 2 - self._pan.y) / self._zoom)

    def fit(self):
        self._zoom = 1.0
        self._pan = wx.Point(0, 0)
        self.Refresh(False)

    def zoom(self, factor):
        self._zoom = max(0.4, min(4.0, self._zoom * float(factor)))
        self.Refresh(False)

    def _on_size(self, event):
        # Windows emits a stream of size events while the dialog settles or is
        # dragged. Re-fitting a dense QR/header preview for every event can
        # monopolise the UI thread, so rebuild once after the burst.
        self._size_timer.StartOnce(80)
        event.Skip()

    def _on_size_timer(self, event):
        self._rebuild_cache()
        self.Refresh(False)

    def _on_wheel(self, event):
        self.zoom(1.12 if event.GetWheelRotation() > 0 else 1.0 / 1.12)

    def _on_left_down(self, event):
        if self._transform_handler is not None and self._transform_corners:
            point = self._local_mouse(event.GetPosition())
            rotate = self._rotation_handle
            if rotate is not None and math.hypot(point.x-rotate.x, point.y-rotate.y) <= 10:
                self._transform_mode = "rotate"
            else:
                corner = next((index for index, value in enumerate(self._transform_corners) if math.hypot(point.x-value.x,point.y-value.y) <= 12), None)
                if corner is not None:
                    self._transform_mode = ("resize", corner)
            if self._transform_mode is None and self._point_in_transform(point):
                self._transform_mode = "move"
            if self._transform_mode:
                self._transform_start = point
                if not self.HasCapture(): self.CaptureMouse()
                return
        self._drag_anchor = event.GetPosition() - self._pan
        if not self.HasCapture():
            self.CaptureMouse()

    def _on_left_up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        self._drag_anchor = None
        self._transform_mode = None
        self._transform_start = None
        if event is not None:
            event.Skip()

    def _on_motion(self, event):
        if self._transform_mode and self._transform_start is not None and event.Dragging() and event.LeftIsDown():
            current = self._local_mouse(event.GetPosition()); graphic = self._transform_graphic
            dx, dy = current.x-self._transform_start.x, current.y-self._transform_start.y
            board_dx = dx/max(0.000001,self._preview_scale) * (-1 if is_bottom(self._layer) else 1)
            board_dy = dy/max(0.000001,self._preview_scale)
            if self._transform_mode == "move":
                self._transform_handler("move", board_dx, board_dy)
                self._transform_start = current
            elif isinstance(self._transform_mode, tuple):
                corner = self._transform_mode[1]; sign_x = -1 if corner in (0,3) else 1; sign_y = -1 if corner in (0,1) else 1
                angle=math.radians(graphic.rotation_deg); local_dx=board_dx*math.cos(angle)+board_dy*math.sin(angle); local_dy=-board_dx*math.sin(angle)+board_dy*math.cos(angle)
                self._transform_handler("resize", max(0.1,graphic.size.width+sign_x*2*local_dx), max(0.1,graphic.size.height+sign_y*2*local_dy))
                self._transform_start = current
            else:
                centre = self._world_to_device(graphic.position)
                screen_angle = math.degrees(math.atan2(current.y-centre.y,current.x-centre.x))+90
                self._transform_handler("rotate", -screen_angle if is_bottom(self._layer) else screen_angle, 0)
            return
        if self._drag_anchor is None or not event.Dragging() or not event.LeftIsDown():
            return
        self._pan = event.GetPosition() - self._drag_anchor
        self.Refresh(False)

    def _point_in_transform(self, point):
        inside = False; corners = self._transform_corners
        for index, first in enumerate(corners):
            second = corners[(index + 1) % len(corners)]
            if (first.y > point.y) == (second.y > point.y): continue
            crossing = first.x + (point.y-first.y)*(second.x-first.x)/(second.y-first.y)
            if crossing > point.x: inside = not inside
        return inside

    @staticmethod
    def _device_points(polygons):
        result = []
        for polygon in polygons:
            points = [
                wx.Point(
                    int(round(x)),
                    int(round(y)),
                )
                for x, y in polygon
            ]
            if points:
                result.append(points)
        return tuple(result)

    def _rebuild_cache(self):
        try:
            width, height = self.GetClientSize()
            sources = self._filled + self._strokes + self._guides
            converted = preview_polygons(sources, self._layer)
            raw_points = [point for polygon in converted for point in polygon]
            if raw_points:
                min_x=min(point[0] for point in raw_points); max_x=max(point[0] for point in raw_points)
                min_y=min(point[1] for point in raw_points); max_y=max(point[1] for point in raw_points)
                geometry_width=max_x-min_x; geometry_height=max_y-min_y
                usable_width=width*0.76; usable_height=height*0.76
                self._preview_scale=min(usable_width/max(0.000001,geometry_width),usable_height/max(0.000001,geometry_height))
                self._preview_centre=((min_x+max_x)/2.0,(min_y+max_y)/2.0)
            fitted = fit_preview_polygons(converted, width, height, margin=0.12)
            device = self._device_points(fitted)
            filled_end = len(self._filled)
            stroke_end = filled_end + len(self._strokes)
            self._cache = (
                device[:filled_end],
                device[filled_end:stroke_end],
                device[stroke_end:],
            )
            artwork_points = [point for polygon in device[:stroke_end] for point in polygon]
            if artwork_points:
                minimum_x=min(point.x for point in artwork_points); maximum_x=max(point.x for point in artwork_points)
                minimum_y=min(point.y for point in artwork_points); maximum_y=max(point.y for point in artwork_points)
                self._transform_bounds=wx.Rect2D(minimum_x,minimum_y,max(1,maximum_x-minimum_x),max(1,maximum_y-minimum_y))
            else: self._transform_bounds=None
            self._update_transform_geometry()
        except Exception:
            # Resize and mouse events are native wx callbacks. Keep malformed
            # or temporarily incomplete geometry from escaping through them.
            traceback.print_exc()
            self._cache = ((), (), ())

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        palette = _palette()
        background = palette["controls"]
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        try:
            size = self.GetClientSize()
            canvas_rect = wx.Rect(6, 6, max(1, size.width - 12), max(1, size.height - 12))
            radius = 16
            dc.SetPen(wx.Pen(palette["border"], 1))
            dc.SetBrush(wx.Brush(palette["canvas"]))
            dc.DrawRoundedRectangle(canvas_rect, radius)
            dark = is_dark_mode(wx)
            dot_colour = (
                wx.Colour(93, 98, 92)
                if dark
                else wx.Colour(193, 187, 173)
            )
            dc.SetPen(wx.Pen(dot_colour, 1))
            for x in range(canvas_rect.x + 7, canvas_rect.GetRight(), 14):
                for y in range(canvas_rect.y + 7, canvas_rect.GetBottom(), 14):
                    if self._inside_rounded_rect(x, y, canvas_rect, radius):
                        dc.DrawPoint(x, y)
            filled, strokes, guides = self._cache
            # Geometry is fitted only when artwork or canvas size changes.
            # Native DC transforms keep wheel/drag events constant-time even
            # for repeated artwork containing thousands of polygons.
            dc.SetDeviceOrigin(
                size.width // 2 + self._pan.x,
                size.height // 2 + self._pan.y,
            )
            dc.SetUserScale(self._zoom, self._zoom)
            foreground = palette["text"]
            dc.SetPen(wx.Pen(foreground, 1))
            dc.SetBrush(wx.Brush(foreground))
            if filled:
                dc.DrawPolygonList(filled)
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            for points in strokes:
                if len(points) > 1:
                    dc.SetPen(wx.Pen(foreground, 2))
                    dc.DrawLines(points + [points[0]])
            for index, points in enumerate(guides):
                if len(points) > 1:
                    colour = ACCENT if index == 0 else wx.Colour(145, 145, 145)
                    dc.SetPen(wx.Pen(colour, 1, wx.PENSTYLE_SHORT_DASH))
                    dc.DrawLines(points + [points[0]])
            if self._anchor is not None:
                anchor = self._world_to_device(self._anchor)
                x, y = round(anchor.x), round(anchor.y)
                dc.SetPen(wx.Pen(ACCENT, 1))
                dc.SetBrush(wx.TRANSPARENT_BRUSH)
                dc.DrawCircle(x, y, 4)
                dc.DrawLine(x - 8, y, x + 8, y)
                dc.DrawLine(x, y - 8, x, y + 8)
            if self._transform_handler is not None and self._transform_corners:
                dc.SetPen(wx.Pen(ACCENT,1,wx.PENSTYLE_SHORT_DASH)); dc.SetBrush(wx.TRANSPARENT_BRUSH)
                points=[wx.Point(round(item.x),round(item.y)) for item in self._transform_corners]
                dc.DrawLines(points+[points[0]])
                for point in points:
                    dc.SetBrush(wx.Brush(ACCENT)); dc.DrawRectangle(point.x-4,point.y-4,8,8)
                top=wx.Point(round((points[0].x+points[1].x)/2),round((points[0].y+points[1].y)/2)); rotate=self._rotation_handle
                dc.DrawLine(top.x,top.y,round(rotate.x),round(rotate.y)); dc.DrawCircle(round(rotate.x),round(rotate.y),5)
        except Exception:
            # Never unwind through wx's native paint callback. A paint-time
            # Python exception can invalidate the native DC and crash KiCad.
            traceback.print_exc()
            dc.SetUserScale(1.0, 1.0)
            dc.SetDeviceOrigin(0, 0)
            dc.SetBackground(wx.Brush(background))
            dc.Clear()

    @staticmethod
    def _inside_rounded_rect(x, y, rect, radius):
        if rect.x + radius <= x <= rect.GetRight() - radius:
            return True
        if rect.y + radius <= y <= rect.GetBottom() - radius:
            return True
        centre_x = rect.x + radius if x < rect.x + radius else rect.GetRight() - radius
        centre_y = rect.y + radius if y < rect.y + radius else rect.GetBottom() - radius
        return (x - centre_x) ** 2 + (y - centre_y) ** 2 <= radius ** 2


class ToolPage(wx.Panel):
    """One independently-owned tool page with fixed navigation and scrolling content."""

    def __init__(self, parent, dialog, family, label, mode):
        super().__init__(
            parent,
            style=wx.TAB_TRAVERSAL | wx.BORDER_NONE | wx.CLIP_CHILDREN,
        )
        self.dialog = dialog
        self.family = family
        self.label = label
        self.mode = mode
        self.controls = {}
        self.field_widgets = {}
        self.measurement_unit = MeasurementUnit.MILLIMETRES
        self._measurement_labels = {}
        self._symbol_reference = ""
        self._content_widgets = {}
        self._active_parent = self
        self._card_layout_columns = 1
        self.cards = []
        self.sections = []
        self.section_buttons = {}
        self._layout_pending = False
        self._scroll_to_top = False
        self.SetBackgroundColour(_palette()["controls"])
        self.root = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(self.root)
        self.section_bar = wx.Panel(self)
        self.section_bar.SetBackgroundColour(_palette()["subnav"])
        self.section_bar.SetMinSize(wx.Size(138, -1))
        self.section_sizer = wx.BoxSizer(wx.VERTICAL)
        self.section_bar.SetSizer(self.section_sizer)
        self.section_sizer.AddSpacer(12)
        self.root.Add(self.section_bar, 0, wx.EXPAND)
        self.content = wx.ScrolledWindow(
            self,
            style=wx.VSCROLL | wx.TAB_TRAVERSAL | wx.BORDER_NONE,
        )
        self.content.SetBackgroundColour(_palette()["controls"])
        self.content.SetScrollRate(0, 12)
        if hasattr(self.content, "ShowScrollbars"):
            never = getattr(wx, "SHOW_SB_NEVER", 0)
            self.content.ShowScrollbars(never, never)
        # Native controls must live on an ordinary panel rather than directly
        # on wx.ScrolledWindow. On both MSW and Cocoa, direct children can keep
        # stale native positions while a resize is updating the virtual area,
        # which leaves repeated controls and card borders painted behind them.
        self.content_panel = wx.Panel(
            self.content,
            style=wx.TAB_TRAVERSAL | wx.BORDER_NONE | wx.CLIP_CHILDREN,
        )
        self.content_panel.SetBackgroundColour(_palette()["controls"])
        columns = wx.BoxSizer(wx.HORIZONTAL)
        self.columns_sizer = columns
        self.card_columns = (wx.BoxSizer(wx.VERTICAL), wx.BoxSizer(wx.VERTICAL))
        columns.Add(self.card_columns[0], 1, wx.EXPAND | wx.RIGHT, 6)
        columns.Add(self.card_columns[1], 1, wx.EXPAND | wx.LEFT, 6)
        self.content_panel.SetSizer(columns)
        self.root.Add(self.content, 1, wx.EXPAND | wx.ALL, 14)
        self._build()
        self._build_section_nav()
        self._update_card_layout(force=True)
        self._show_section(self.sections[0])
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _schedule_layout(self, *, scroll_to_top=False):
        """Finish a settings visibility change after the native input event."""
        self._scroll_to_top = self._scroll_to_top or bool(scroll_to_top)
        if self._layout_pending:
            return
        self._layout_pending = True
        wx.CallAfter(self._apply_scheduled_layout)

    def _apply_scheduled_layout(self):
        self._layout_pending = False
        if not self or self.IsBeingDeleted():
            return
        scroll_to_top = self._scroll_to_top
        self._scroll_to_top = False
        self.Layout()
        # Keep the inner panel at its active card's natural height. Without an
        # explicit vertical minimum, wx can compress the native children to
        # the viewport while retaining a taller virtual size, leaving controls
        # clipped or overlapping instead of making them scrollable.
        viewport = self.content.GetClientSize()
        content_height = max(1, self.columns_sizer.CalcMin().height)
        content_size = wx.Size(
            max(1, viewport.width),
            max(max(1, viewport.height), content_height),
        )
        self.content_panel.SetSize(content_size)
        self.content_panel.Layout()
        self.content.SetVirtualSize(content_size)
        self.content.Refresh(False)
        if scroll_to_top:
            self.content.Scroll(0, 0)

    def _card(self, title):
        card = SettingsCard(self.content_panel, title)
        section = self._section_for_card(title)
        if section not in self.sections:
            self.sections.append(section)
        self.cards.append((card, section))
        self._active_parent = card
        return card.body

    def _cleanup_example(self, parent, title, filename):
        """Return a labelled, bounded before/after reference image box."""
        frame = wx.StaticBox(parent, label=title)
        sizer = wx.StaticBoxSizer(frame, wx.VERTICAL)
        image_path = Path(__file__).resolve().parents[1] / "resources" / "ReferenceImages" / filename
        try:
            image = wx.Image(str(image_path), wx.BITMAP_TYPE_PNG)
            if not image.IsOk():
                raise ValueError("invalid image")
            scale = min(220 / image.GetWidth(), 145 / image.GetHeight(), 1.0)
            image = image.Scale(
                max(1, round(image.GetWidth() * scale)),
                max(1, round(image.GetHeight() * scale)),
                wx.IMAGE_QUALITY_HIGH,
            )
            preview = wx.StaticBitmap(frame, bitmap=wx.Bitmap(image))
            sizer.Add(preview, 0, wx.ALIGN_CENTER | wx.ALL, 7)
        except Exception:
            # Keep the cleanup action usable even if a hand-edited package is
            # missing its optional explanatory artwork.
            sizer.Add(wx.StaticText(frame, label="Example image unavailable"), 0, wx.ALL, 12)
        return sizer

    def _add_cleanup_operation(self, box, title, description, operation, before_image, after_image):
        """Build one clear cleanup row with actions and visual consequences."""
        heading = wx.StaticText(self._active_parent, label=title)
        heading.SetFont(heading.GetFont().Bold())
        box.Add(heading, 0, wx.TOP | wx.BOTTOM, 3)
        note = wx.StaticText(self._active_parent, label=description)
        note.Wrap(540)
        box.Add(note, 0, wx.EXPAND | wx.BOTTOM, 8)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(
            KobeeAction(
                self._active_parent,
                "Selected footprints",
                lambda: self.dialog.run_board_cleanup(operation, "selected"),
                primary=True,
            ),
            0,
            wx.RIGHT,
            7,
        )
        actions.Add(
            KobeeAction(
                self._active_parent,
                "Whole board",
                lambda: self.dialog.run_board_cleanup(operation, "board"),
            ),
            0,
        )
        box.Add(actions, 0, wx.EXPAND | wx.BOTTOM, 8)
        examples = wx.BoxSizer(wx.HORIZONTAL)
        examples.Add(self._cleanup_example(self._active_parent, "Before", before_image), 1, wx.EXPAND | wx.RIGHT, 6)
        examples.Add(self._cleanup_example(self._active_parent, "After", after_image), 1, wx.EXPAND | wx.LEFT, 6)
        box.Add(examples, 0, wx.EXPAND | wx.BOTTOM, 12)

    def _desired_card_columns(self):
        # Cards belong to explicit sidebar sections. One focused card per
        # section keeps the settings readable without stealing preview width.
        return 1

    def _update_card_layout(self, force=False):
        columns = self._desired_card_columns()
        if not force and columns == self._card_layout_columns:
            return
        self._card_layout_columns = columns
        for column in self.card_columns:
            for index in range(column.GetItemCount() - 1, -1, -1):
                column.Detach(index)
        section_counts = {}
        for card, section in self.cards:
            index = section_counts.get(section, 0) % columns
            section_counts[section] = section_counts.get(section, 0) + 1
            self.card_columns[index].Add(card, 0, wx.EXPAND | wx.BOTTOM, 12)
        self.card_columns[0].AddStretchSpacer(1)
        if columns == 2:
            self.card_columns[1].AddStretchSpacer(1)
        left_column_item = self.columns_sizer.GetItem(self.card_columns[0])
        right_column_item = self.columns_sizer.GetItem(self.card_columns[1])
        if left_column_item is not None:
            left_column_item.SetProportion(1)
        if right_column_item is not None:
            right_column_item.SetProportion(1 if columns == 2 else 0)

    def _on_size(self, event):
        self._update_card_layout()
        self._schedule_layout()
        event.Skip()

    def _section_for_card(self, title):
        if title in ("Content", "Presentation", "Variable template"):
            return "Basics"
        if title == "Multipart label":
            return "Sections"
        if title == "Container":
            return "Container"
        if title == "Opening & spacing":
            return "Spacing"
        if title == "Component safe zone":
            return "Safe zone"
        if title == "Typography & spacing":
            return "Typography"
        if title == "Native text & spacing":
            return "Text & spacing"
        if title == "Text details":
            return "Advanced"
        if title == "Array":
            return "Array"
        if "header" in title.lower():
            return "Basics"
        if "code" in title.lower() or "barcode" in title.lower():
            return "Basics"
        return title

    def _build_section_nav(self):
        for section in self.sections:
            button = KobeeTab(
                self.section_bar,
                section,
                lambda value=section: self._show_section(value),
                kind="side",
            )
            self.section_sizer.Add(button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 7)
            self.section_buttons[section] = button
        self.section_sizer.AddStretchSpacer(1)

    def _show_section(self, section):
        self._update_card_layout()
        visible_cards = [
            card for card, card_section in self.cards if card_section == section
        ]
        for card, card_section in self.cards:
            card.Show(card_section == section)
        left_column_item = self.columns_sizer.GetItem(self.card_columns[0])
        right_column_item = self.columns_sizer.GetItem(self.card_columns[1])
        if left_column_item is not None:
            left_column_item.SetProportion(1)
        if right_column_item is not None:
            right_column_item.SetProportion(0 if len(visible_cards) == 1 else 1)
        for name, button in self.section_buttons.items():
            button.set_active(name == section)
        self._schedule_layout(scroll_to_top=True)

    def _grid(self, box, columns=1):
        grid = wx.FlexGridSizer(0, columns * 2, 7, 6)
        for index in range(columns):
            grid.AddGrowableCol(index * 2 + 1)
        box.Add(grid, 0, wx.EXPAND)
        return grid

    def _add(self, grid, key, label, control):
        field_label = wx.StaticText(self._active_parent, label=label)
        field_label.Wrap(92)
        field_label.SetToolTip(label)
        grid.Add(field_label, 0, wx.ALIGN_CENTER_VERTICAL)
        numeric = isinstance(control, (wx.SpinCtrl, wx.SpinCtrlDouble, ThemedSpinCtrl, ThemedSpinCtrlDouble))
        grid.Add(control, 0 if numeric else 1, (wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL) if numeric else wx.EXPAND)
        self.controls[key] = control
        control.SetName(label)
        self.field_widgets[key] = (field_label, control)
        if key in MEASUREMENT_SETTING_KEYS:
            self._measurement_labels[key] = label
        self._bind(control)
        return control

    def _bind(self, control):
        for event_type in (
            wx.EVT_TEXT,
            wx.EVT_CHOICE,
            wx.EVT_CHECKBOX,
            wx.EVT_SPINCTRL,
            wx.EVT_SPINCTRLDOUBLE,
        ):
            try:
                control.Bind(event_type, self.dialog.on_control_changed)
            except Exception:
                pass
        editor = getattr(control, "editor", None)
        if editor is not None:
            try:
                editor.Bind(wx.EVT_TEXT, self.dialog.on_control_changed)
            except Exception:
                pass

    def choice(self, choices, value=None):
        control = ThemedChoice(self._active_parent, choices=tuple(choices))
        control.SetMinSize(wx.Size(164, 30))
        if value is not None:
            control.SetStringSelection(str(value))
        elif control.GetCount():
            control.SetSelection(0)
        return control

    def segmented(self, choices, value, rows=1):
        return SegmentedChoice(self._active_parent, choices, value, rows=rows)

    def spin(self, minimum, maximum, value, increment=0.1, digits=2):
        control = ThemedSpinCtrlDouble(
            self._active_parent,
            value=str(value),
            min=minimum,
            max=maximum,
            initial=value,
            inc=increment,
        )
        control.SetDigits(digits)
        control._kobee_mm_range = (float(minimum), float(maximum))
        control._kobee_mm_increment = float(increment)
        control._kobee_mm_digits = int(digits)
        control.SetMinSize(wx.Size(120, 30))
        return control

    def _unit_label(self, label):
        unit = self.measurement_unit.value
        return str(label).replace("(mm)", "({})".format(unit)).replace("(mil)", "({})".format(unit))

    def set_measurement_unit(self, unit):
        unit = MeasurementUnit.parse(unit)
        if unit is self.measurement_unit:
            return
        old_unit = self.measurement_unit
        for key in MEASUREMENT_SETTING_KEYS:
            control = self.controls.get(key)
            if control is None or not isinstance(control, (wx.SpinCtrlDouble, ThemedSpinCtrlDouble)):
                continue
            current_mm = to_millimetres(control.GetValue(), old_unit)
            minimum_mm, maximum_mm = control._kobee_mm_range
            control.SetRange(
                from_millimetres(minimum_mm, unit),
                from_millimetres(maximum_mm, unit),
            )
            control.SetIncrement(from_millimetres(control._kobee_mm_increment, unit))
            control.SetDigits(
                control._kobee_mm_digits
                if unit is MeasurementUnit.MILLIMETRES
                else 2
            )
            control.SetValue(from_millimetres(current_mm, unit))
            label_control = self.field_widgets.get(key, (None,))[0]
            if label_control is not None:
                label_control.SetLabel(self._unit_label(self._measurement_labels[key]))
        self.measurement_unit = unit
        # Labels above were formatted using the previous unit; refresh once
        # after the state changes and let dynamic container labels follow it.
        for key, base_label in self._measurement_labels.items():
            label_control = self.field_widgets.get(key, (None,))[0]
            if label_control is not None:
                label_control.SetLabel(self._unit_label(base_label))
        self._update_container_ui()
        self.Layout()
        self.content.FitInside()

    def _measurement_mm(self, key):
        return to_millimetres(self.controls[key].GetValue(), self.measurement_unit)

    def _set_measurement_mm(self, key, value_mm):
        self.controls[key].SetValue(from_millimetres(value_mm, self.measurement_unit))

    def selected_symbol_reference(self):
        return self._symbol_reference

    def integer_spin(self, minimum, maximum, value):
        return ThemedSpinCtrl(self._active_parent, min=minimum, max=maximum, initial=value)

    def text(self, value="", multiline=False):
        return RoundedTextField(self._active_parent, value=value, multiline=multiline)

    def checkbox(self, label, value=False):
        return ThemedCheckBox(self._active_parent, label=label, value=value)

    def _build_content(self, box, *, multiline=False, subtitle=False, icon=False, preset=False):
        """Build an explicit text/symbol flow instead of two ambiguous pickers."""
        self._content_card = self._active_parent
        if icon:
            mode_label = wx.StaticText(self._active_parent, label="Make")
            mode_choice = self.segmented(
                ("Label", "Label + symbol", "Symbol only"), "Label", rows=2
            )
            box.Add(mode_label, 0, wx.TOP | wx.BOTTOM, 7)
            box.Add(mode_choice, 0, wx.EXPAND | wx.BOTTOM, 9)
            self.controls["ContentModeChoice"] = mode_choice
            self._bind(mode_choice)
            mode_choice.Bind(wx.EVT_CHOICE, self._on_content_mode_changed)

        if preset:
            preset_label = wx.StaticText(self._active_parent, label="Quick label")
            preset_button = PickerButton(
                self._active_parent,
                "Choose a quick label",
                "Custom label",
                kind="preset",
                callback=self._choose_preset,
            )
            box.Add(preset_label, 0, wx.BOTTOM, 4)
            box.Add(preset_button, 0, wx.EXPAND | wx.BOTTOM, 9)
            self._content_widgets["preset"] = (preset_label, preset_button)
            self.controls["PresetLabelChoice"] = preset_button

        text_label = wx.StaticText(
            self._active_parent,
            label="Label text" if self.mode == "Label" else "Labels (one per line)",
        )
        text = self.text(MODE_DEFAULTS[self.mode]["MultiLineText"], multiline)
        # Header and array labels are the places where users routinely enter
        # several lines.  Give those editors enough height to read and edit
        # the list without taking space from the live preview.
        if multiline and self.mode in ("2.54 mm Pin Header", "Component Array"):
            text.SetMinSize(wx.Size(104, 112))
        box.Add(text_label, 0, wx.TOP | wx.BOTTOM, 4)
        box.Add(text, 0, wx.EXPAND | wx.BOTTOM, 9)
        self._content_widgets["text"] = (text_label, text)
        self.controls["MultiLineText"] = text
        self._bind(text)

        if icon:
            symbol_label = wx.StaticText(self._active_parent, label="Symbol")
            icon_button = PickerButton(
                self._active_parent,
                "Choose a symbol",
                "No icon",
                kind="symbol",
                callback=self._choose_icon,
                symbol_catalog=self.dialog.symbol_catalog,
            )
            box.Add(symbol_label, 0, wx.BOTTOM, 4)
            box.Add(icon_button, 0, wx.EXPAND | wx.BOTTOM, 9)
            self._content_widgets["symbol"] = (symbol_label, icon_button)
            self.controls["IconChoice"] = icon_button

        if subtitle:
            grid = self._grid(box)
            self._add(grid, "ContentLayoutChoice", "Text layout", self.choice(CONTENT_LAYOUT_LABELS, "Single text"))
            self._add(grid, "SubtitleCtrl", "Subtitle", self.text(""))
            self.controls["ContentLayoutChoice"].Bind(wx.EVT_CHOICE, self._on_content_layout_changed)
        if icon:
            grid = self._grid(box)
            self._add(grid, "IconPositionChoice", "Symbol position", self.choice(("Left of text", "Right of text", "Above text", "Below text"), "Left of text"))
            icon_height = self._add(grid, "IconHeightCtrl", "Symbol size (mm)", self.spin(0, 20, 0, 0.1))
            icon_height._kobee_auto_value_resolver = lambda: self.controls["HeightCtrl"].GetValue()
            self._add(grid, "IconGapCtrl", "Symbol gap (mm)", self.spin(0, 20, 0.3, 0.1))
            self.controls["IconHeightCtrl"].SetToolTip("Automatic at 0; the first arrow press uses the current text height.")
            self._update_content_ui()

    def _set_content_widgets_visible(self, key, visible):
        for widget in self._content_widgets.get(key, ()):
            widget.Show(bool(visible))

    def _set_field_visible(self, key, visible):
        for widget in self.field_widgets.get(key, ()):
            widget.Show(bool(visible))

    def _update_content_ui(self):
        if "ContentModeChoice" not in self.controls:
            return
        mode = self.controls["ContentModeChoice"].GetStringSelection()
        text_enabled = mode != "Symbol only"
        symbol_enabled = mode != "Label"
        has_symbol = bool(self._symbol_reference)
        self._set_content_widgets_visible("preset", text_enabled)
        self._set_content_widgets_visible("text", text_enabled)
        self._set_content_widgets_visible("symbol", symbol_enabled)
        self._set_field_visible("ContentLayoutChoice", text_enabled)
        show_subtitle = (
            text_enabled
            and self.controls.get("ContentLayoutChoice")
            and self.controls["ContentLayoutChoice"].GetStringSelection()
            == "Title + subtitle"
        )
        self._set_field_visible("SubtitleCtrl", bool(show_subtitle))
        self._set_field_visible("SubtitleFontChoice", bool(show_subtitle))
        self._set_field_visible("SubtitleHeightCtrl", bool(show_subtitle))
        self._set_field_visible("SubtitleLineSpacingCtrl", False)
        self._set_field_visible("SubtitleGapCtrl", bool(show_subtitle))
        self._set_field_visible("IconPositionChoice", symbol_enabled and has_symbol and mode != "Symbol only")
        self._set_field_visible("IconHeightCtrl", symbol_enabled and has_symbol)
        self._set_field_visible("IconGapCtrl", symbol_enabled and has_symbol and mode != "Symbol only")
        self._schedule_layout()

    def _on_content_mode_changed(self, event):
        self._update_content_ui()
        self.dialog.request_preview()
        event.Skip()

    def _on_content_layout_changed(self, event):
        self._update_content_ui()
        self.dialog.request_preview()
        event.Skip()

    def _build_container(self, shapes, *, outline_only=False):
        box = self._card("Container")
        self._container_card = self._active_parent
        grid = self._grid(box)
        special_shape = (
            "Independent long edges"
            if self.mode == "2.54 mm Pin Header"
            else "Independent ends"
        )
        # Connector overlays deliberately use only the three robust enclosure
        # types in HEADER_SHAPE_LABELS.  Existing asymmetric payloads still
        # render, but are normalised to a rounded rectangle when edited.
        if self.mode == "2.54 mm Pin Header":
            special_shape = None
        base_shapes = tuple(shape for shape in shapes if shape != special_shape)
        self._container_special_shape = special_shape if special_shape in shapes else None
        self._last_standard_shape = "Rounded rectangle"
        if self._container_special_shape:
            self._add(
                grid,
                "IndependentEdgesChoice",
                "Long edges" if self.mode == "2.54 mm Pin Header" else "End treatment",
                self.segmented(("Matched", "Independent"), "Matched"),
            )
        shape = self._add(
            grid,
            "ShapeChoice",
            "Shape",
            self.choice(base_shapes, self._last_standard_shape),
        )
        appearances = ("Outline",) if outline_only else VARIANT_LABELS
        self._add(
            grid,
            "ShapeVariantChoice",
            "Appearance",
            self.segmented(appearances, "Outline" if outline_only else "Inverted fill"),
        )
        self._add(grid, "CornerRadiusCtrl", "Corner radius (mm)", self.spin(0, 100, 0.2, 0.05))
        self._add(grid, "BorderThicknessCtrl", "Outline width (mm)", self.spin(0.01, 10, 0.2, 0.05))
        self._add(grid, "FeatureSizeCtrl", "Feature size (mm)", self.spin(0, 100, 0.75, 0.1))
        self._add(grid, "ShapeDirectionChoice", "Direction", self.choice(("Left", "Right"), "Right"))
        caps = HEADER_CAP_LABELS if self.mode == "2.54 mm Pin Header" else CAP_LABELS
        self._add(grid, "StartCapChoice", "Left edge", self.choice(caps, "Square"))
        self._add(grid, "EndCapChoice", "Right edge", self.choice(caps, "Rounded"))
        shape.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.controls["ShapeVariantChoice"].Bind(
            wx.EVT_CHOICE, self._on_container_variant_changed
        )
        if "IndependentEdgesChoice" in self.controls:
            self.controls["IndependentEdgesChoice"].Bind(
                wx.EVT_CHOICE, self._on_independent_edges_changed
            )
        self._update_container_ui()

    def _on_shape_changed(self, event):
        shape = self.controls["ShapeChoice"].GetStringSelection()
        if shape:
            self._last_standard_shape = shape
        if "IndependentEdgesChoice" in self.controls:
            self.controls["IndependentEdgesChoice"].SetStringSelection("Matched")
        self._update_container_ui()
        self.dialog.request_preview()
        event.Skip()

    def _on_independent_edges_changed(self, event):
        independent = (
            self.controls["IndependentEdgesChoice"].GetStringSelection()
            == "Independent"
        )
        if independent:
            current = self.controls["ShapeChoice"].GetStringSelection()
            if current:
                self._last_standard_shape = current
        self._update_container_ui()
        self.dialog.request_preview()
        event.Skip()

    def _on_container_variant_changed(self, event):
        self._update_container_ui()
        self.dialog.request_preview()
        event.Skip()

    def _effective_shape_choice(self):
        if (
            getattr(self, "_container_special_shape", None)
            and self.controls.get("IndependentEdgesChoice")
            and self.controls["IndependentEdgesChoice"].GetStringSelection()
            == "Independent"
        ):
            return self._container_special_shape
        shape = self.controls.get("ShapeChoice")
        return shape.GetStringSelection() if shape is not None else "No container"

    def _effective_end_caps(self):
        """Resolve matched skew shapes without exposing slash glyphs as ends."""
        shape = self.controls.get("ShapeChoice")
        matched_shape = shape.GetStringSelection() if shape is not None else ""
        independent = (
            self.controls.get("IndependentEdgesChoice")
            and self.controls["IndependentEdgesChoice"].GetStringSelection() == "Independent"
        )
        if not independent and matched_shape in ("Skew left", "Skew right"):
            return matched_shape, matched_shape
        return (
            self.controls.get("StartCapChoice").GetStringSelection() if self.controls.get("StartCapChoice") else "Square",
            self.controls.get("EndCapChoice").GetStringSelection() if self.controls.get("EndCapChoice") else "Rounded",
        )

    def _update_container_ui(self):
        if "ShapeChoice" not in self.controls:
            return
        shape = self._effective_shape_choice()
        no_container = shape == "No container"
        independent = shape in ("Independent ends", "Independent long edges")
        uses_radius = shape in ("Rounded rectangle", "Independent long edges")
        feature_labels = {
            "Pointer": "Pointer depth (mm)",
            "Flag": "Flag notch depth (mm)",
            "Tab": "Tab depth (mm)",
            "Chamfer": "Chamfer size (mm)",
            "Hexagon": "Hexagon corner cut (mm)",
        }
        uses_feature = shape in feature_labels
        uses_direction = shape in ("Pointer", "Flag")
        outline = self.controls.get("ShapeVariantChoice") and self.controls["ShapeVariantChoice"].GetStringSelection() == "Outline"
        self._set_field_visible("IndependentEdgesChoice", not no_container)
        self._set_field_visible("ShapeChoice", not independent)
        self._set_field_visible("ShapeVariantChoice", not no_container)
        self._set_field_visible("CornerRadiusCtrl", uses_radius)
        self._set_field_visible("BorderThicknessCtrl", bool(outline and not no_container))
        self._set_field_visible("FeatureSizeCtrl", uses_feature)
        self._set_field_visible("ShapeDirectionChoice", uses_direction)
        self._set_field_visible("StartCapChoice", independent)
        self._set_field_visible("EndCapChoice", independent)
        if "FeatureSizeCtrl" in self.field_widgets and uses_feature:
            label, _control = self.field_widgets["FeatureSizeCtrl"]
            self._measurement_labels["FeatureSizeCtrl"] = feature_labels[shape]
            label.SetLabel(self._unit_label(feature_labels[shape]))
            label.Wrap(108)
        if independent:
            start_label, _control = self.field_widgets["StartCapChoice"]
            end_label, _control = self.field_widgets["EndCapChoice"]
            if self.mode == "2.54 mm Pin Header":
                start_label.SetLabel("Pin-side edge")
                end_label.SetLabel("Label-side edge")
            else:
                start_label.SetLabel("Left edge")
                end_label.SetLabel("Right edge")
            start_label.Wrap(108)
            end_label.Wrap(108)
        self._schedule_layout()

    def _update_text_details_ui(self):
        """Keep optional text effects out of the way until they are enabled."""
        if "UnderlineCheckbox" not in self.controls:
            return
        underline = self.controls["UnderlineCheckbox"].GetValue()
        inline = self.controls["inlineFormatTextbox"].GetValue()
        self._set_field_visible("UnderlineThicknessCtrl", underline)
        self._set_field_visible("UnderlineGapCtrl", underline)
        if "OverlineCheckbox" in self.controls:
            overline = self.controls["OverlineCheckbox"].GetValue()
            self._set_field_visible("OverlineThicknessCtrl", overline)
            self._set_field_visible("OverlineGapCtrl", overline)
        self._set_field_visible("lineoverStyleChoice", inline)
        self._set_field_visible("lineoverThicknessCtrl", inline)
        if hasattr(self, "formatting_hint"):
            self.formatting_hint.Show(inline)
        self._schedule_layout()

    def _add_formatting_hint(self, box):
        self.formatting_hint = wx.StaticText(
            self._active_parent,
            label="D_{0} subscript · V^{2} superscript\n~{RESET} overline · !{text} underline",
        )
        self.formatting_hint.Wrap(260)
        box.Add(self.formatting_hint, 0, wx.EXPAND | wx.TOP, 10)

    def _on_text_details_changed(self, event):
        self._update_text_details_ui()
        self.dialog.request_preview()
        event.Skip()

    def _update_header_opening_ui(self):
        if "HeaderOpeningChoice" not in self.controls:
            return
        mode = OPENING_LABELS.get(self.controls["HeaderOpeningChoice"].GetStringSelection())
        continuous = mode == "continuous"
        individual = mode == "individual"
        self._set_field_visible("HeaderOpeningEndPaddingCtrl", continuous)
        self._set_field_visible("HeaderCutoutEdgeChoice", continuous)
        self._set_field_visible("HeaderIndividualCutoutEdgeChoice", individual)
        cutout_choice = self.controls[
            "HeaderIndividualCutoutEdgeChoice" if individual else "HeaderCutoutEdgeChoice"
        ]
        self._set_field_visible(
            "HeaderCutoutRadiusCtrl",
            (continuous or individual)
            and cutout_choice.GetStringSelection() == "Rounded rectangle cutout",
        )
        self._schedule_layout()

    def _on_header_opening_changed(self, event):
        self._update_header_opening_ui()
        self.dialog.request_preview()
        event.Skip()

    def _update_component_safe_zone_ui(self):
        if "ComponentCutoutChoice" not in self.controls:
            return
        rounded = (
            self.controls["ComponentCutoutChoice"].GetStringSelection()
            == "Rounded rectangle"
        )
        self._set_field_visible("ComponentCutoutRadiusCtrl", rounded)
        self._schedule_layout()

    def _on_component_cutout_changed(self, event):
        self._update_component_safe_zone_ui()
        self.dialog.request_preview()
        event.Skip()

    def _update_machine_code_ui(self):
        if "MachineCodeShowContentCheckbox" not in self.controls:
            return
        barcode = self.label == "Barcode"
        presentation = self.controls.get("MachineCodePresentationChoice")
        presentation_label = presentation.GetStringSelection() if presentation else ""
        has_frame = presentation_label != "Plain code"
        has_footer = presentation_label == "Rounded frame + footer"
        readable = self.controls["MachineCodeShowContentCheckbox"].GetValue()
        self._set_field_visible("MachineCodeFramePaddingCtrl", not barcode and has_frame)
        self._set_field_visible("MachineCodeCaptionCtrl", not barcode and has_footer)
        self._set_field_visible("MachineCodeCaptionHeightCtrl", not barcode and has_footer)
        self._set_field_visible("MachineCodeContentCtrl", readable)
        self._set_field_visible("MachineCodeContentHeightCtrl", readable)
        self._set_field_visible("MachineCodeContentGapCtrl", readable)
        self._schedule_layout()

    def _on_machine_code_changed(self, event):
        self._update_machine_code_ui()
        self.dialog.request_preview()
        event.Skip()

    def _font_names(self):
        font_dir = Path(__file__).resolve().parents[1] / "fonts"
        bundled = tuple(sorted(path.stem for path in font_dir.iterdir() if path.suffix.lower() in (".ttf", ".otf")))
        installed = tuple(face.renderer_name for face in self.dialog.font_store.list())
        enabled_system = set(self.dialog.preferences.enabled_system_font_names)
        system = tuple(
            name for name in self.dialog.system_font_names
            if name in enabled_system and name not in bundled and name not in installed
        )
        return bundled + installed + system

    def _font_labels(self):
        font_dir = Path(__file__).resolve().parents[1] / "fonts"
        bundled = tuple(sorted(path.stem for path in font_dir.iterdir() if path.suffix.lower() in (".ttf", ".otf")))
        faces = self.dialog.font_store.list()
        installed = tuple(face.renderer_name for face in faces)
        enabled_system = set(self.dialog.preferences.enabled_system_font_names)
        system = tuple(
            name for name in self.dialog.system_font_names
            if name in enabled_system and name not in bundled and name not in installed
        )
        entries = (
            [("Built-in · {}".format(name), name) for name in bundled]
            + [("System font · {}".format(name), name) for name in system]
            + [("My Google Fonts · {}".format(face.display_name), face.renderer_name) for face in faces]
        )
        favourites = set(self.dialog.preferences.favourite_font_names)
        favourite_entries = [
            ("★ " + label, renderer)
            for label, renderer in entries if renderer in favourites
        ]
        ordinary_entries = [
            (label, renderer) for label, renderer in entries if renderer not in favourites
        ]
        self._font_renderer_by_label = dict(favourite_entries + ordinary_entries)
        self._font_label_by_renderer = {}
        for label, renderer in favourite_entries + ordinary_entries:
            self._font_label_by_renderer.setdefault(renderer, label)
        return tuple(self._font_renderer_by_label)

    def _font_label(self, renderer):
        self._font_labels()
        return self._font_label_by_renderer.get(str(renderer), str(renderer))

    def _font_renderer(self, label):
        self._font_labels()
        return self._font_renderer_by_label.get(str(label), str(label))

    def _selected_font_renderer(self, choice):
        """Resolve a choice using its previous mapping while regrouping favourites."""
        label = choice.GetStringSelection()
        cached = getattr(self, "_font_renderer_by_label", {})
        if label in cached:
            return cached[label]
        return self._font_renderer(label)

    def _sync_font_favourite(self):
        control = getattr(self, "font_favourite", None)
        choice = self.controls.get("FontComboBox")
        if control is None or choice is None:
            return
        renderer = self._selected_font_renderer(choice)
        control.SetValue(renderer in self.dialog.preferences.favourite_font_names)

    def _refresh_font_choices(self):
        choice = self.controls.get("FontComboBox")
        if choice is None:
            return
        renderer = self._selected_font_renderer(choice)
        choice.SetItems(self._font_labels())
        choice.SetStringSelection(self._font_label(renderer))
        subtitle = self.controls.get("SubtitleFontChoice")
        if subtitle is not None:
            selected = self._selected_font_renderer(subtitle)
            subtitle.SetItems((MATCH_MAIN_TYPEFACE,) + self._font_labels())
            subtitle.SetStringSelection(
                MATCH_MAIN_TYPEFACE if selected == MATCH_MAIN_TYPEFACE else self._font_label(selected)
            )
        self._sync_font_favourite()

    def _on_font_changed(self, event):
        choice = self.controls.get("FontComboBox")
        if choice is not None:
            self.dialog.font_selection_changed(self._font_renderer(choice.GetStringSelection()))
        self._sync_font_favourite()
        event.Skip()

    def _on_font_favourite_changed(self, event):
        choice = self.controls.get("FontComboBox")
        if choice is not None:
            self.dialog.set_font_favourite(
                self._font_renderer(choice.GetStringSelection()), self.font_favourite.GetValue()
            )
        event.Skip()

    def set_font_availability_error(self, message=""):
        warning = getattr(self, "font_availability_warning", None)
        if warning is None:
            return
        warning.SetLabel("⚠ Typeface unavailable" if message else "")
        warning.SetToolTip(message)
        self._schedule_layout()

    def _build_typography(self, *, padding=True, subtitle=False, width=False):
        box = self._card("Typography & spacing")
        grid = self._grid(box)
        defaults = MODE_DEFAULTS[self.mode]
        font_labels = self._font_labels()
        font_choice = self._add(grid, "FontComboBox", "Typeface", self.choice(font_labels, self._font_label(defaults.get("FontComboBox", "FreddySpark-Regular"))))
        self.font_favourite = ThemedCheckBox(
            self._active_parent, label="Favourite this typeface"
        )
        self.font_favourite.SetValue(
            defaults.get("FontComboBox", "FreddySpark-Regular")
            in self.dialog.preferences.favourite_font_names
        )
        self.font_favourite.SetToolTip(
            "Favourite fonts appear first in every Kobee typeface picker."
        )
        box.Add(self.font_favourite, 0, wx.TOP | wx.BOTTOM, 7)
        self.font_availability_warning = wx.StaticText(self._active_parent, label="")
        self.font_availability_warning.SetForegroundColour(wx.Colour(190, 55, 45))
        self.font_availability_warning.SetToolTip("")
        box.Add(self.font_availability_warning, 0, wx.EXPAND | wx.BOTTOM, 4)
        font_choice.Bind(wx.EVT_CHOICE, self._on_font_changed)
        self.font_favourite.Bind(wx.EVT_CHECKBOX, self._on_font_favourite_changed)
        max_height = maximum_pin_label_height() if self.mode == "2.54 mm Pin Header" else 128
        self._add(grid, "HeightCtrl", "Text height (mm)", self.spin(0.1, max_height, defaults.get("HeightCtrl", 1.2), 0.1))
        self._add(grid, "AlignmentChoice", "Alignment", self.choice(("Left", "Center", "Right"), defaults.get("AlignmentChoice", "Center")))
        self._add(grid, "LineSpacingCtrl", "Line spacing", self.spin(0.1, 10, 1.5, 0.1))
        if width:
            self._add(grid, "WidthCtrl", "Minimum width (mm)", self.spin(0, 200, 0, 0.1))
        if self.mode == "Label":
            anchor = self._add(grid, "PlacementAnchorChoice", "Placement anchor", self.choice(PLACEMENT_ANCHORS, "Centre"))
            anchor.SetToolTip("This point stays fixed when placing or editing the artwork on the PCB.")
        if subtitle:
            self._add(grid, "SubtitleFontChoice", "Subtitle typeface", self.choice((MATCH_MAIN_TYPEFACE,) + font_labels, MATCH_MAIN_TYPEFACE))
            self._add(grid, "SubtitleHeightCtrl", "Subtitle height (mm)", self.spin(0.1, 128, 0.8, 0.1))
            self._add(grid, "SubtitleLineSpacingCtrl", "Subtitle line spacing", self.spin(0.1, 10, 1.2, 0.1))
            self._add(grid, "SubtitleGapCtrl", "Title/subtitle gap (mm)", self.spin(0, 20, 0.25, 0.05))
        if padding:
            default_padding = (
                1.0
                if self.mode in ("Component Callout", "Component Array")
                else None
            )
            for key, label, value in (
                ("PaddingTopCtrl", "Top padding (mm)", DEFAULT_LABEL_DIMENSIONS["PaddingTopCtrl"]),
                ("PaddingBottomCtrl", "Bottom padding (mm)", DEFAULT_LABEL_DIMENSIONS["PaddingBottomCtrl"]),
                ("PaddingLeftCtrl", "Left padding (mm)", DEFAULT_LABEL_DIMENSIONS["PaddingLeftCtrl"]),
                ("PaddingRightCtrl", "Right padding (mm)", DEFAULT_LABEL_DIMENSIONS["PaddingRightCtrl"]),
            ):
                self._add(
                    grid,
                    key,
                    label,
                    self.spin(0, 100, default_padding if default_padding is not None else value, 0.1),
                )

    def _build(self):
        if self.label == "Variables":
            template = self._card("Variable template")
            helper = wx.StaticText(
                self._active_parent,
                label=(
                    "Create a reusable variable label. Kobee resolves ${NAME} using "
                    "the current project values, then places it as normal label artwork "
                    "with the selected container and knockout."
                ),
            )
            helper.Wrap(430)
            template.Add(helper, 0, wx.EXPAND | wx.BOTTOM, 10)
            grid = self._grid(template)
            self._variable_templates = ()
            saved = self._add(
                grid,
                "VariableTemplateChoice",
                "Saved template",
                self.choice(("New template",), "New template"),
            )
            save_scopes = ("My library",) + (("This project",) if self.dialog.project_variable_template_store is not None else ())
            self._add(
                grid,
                "VariableSaveScopeChoice",
                "Save in",
                self.choice(save_scopes, "My library"),
            )
            raw = self.text("", multiline=True)
            raw.SetMinSize(wx.Size(120, 118))
            raw.SetHint("Type label text, then choose a project value below to add its placeholder.")
            self._add(grid, "VariableTemplateText", "Template text", raw)
            # Bind the native editor as well as the rounded wrapper. Cocoa can
            # defer the wrapper's relayed event until focus changes; the live
            # preview must reflect ordinary typing straight away.
            raw.editor.Bind(wx.EVT_TEXT, self._on_variable_template_text_changed)
            available = self._add(
                grid,
                "VariableInsertChoice",
                "Add project value",
                self.choice(("Choose a project value…",), "Choose a project value…"),
            )
            # Keep the selected placeholder readable even in Kobee's compact
            # sidebar layout. The full current value remains in the status
            # text, not in the choice label where it used to be clipped.
            available.SetMinSize(wx.Size(250, 30))
            value_actions = wx.BoxSizer(wx.HORIZONTAL)
            value_actions.Add(
                KobeeAction(self._active_parent, "Refresh values", self._refresh_variable_values),
                0,
            )
            value_actions.Add(
                wx.StaticText(
                    self._active_parent,
                    label="Reloads the current project values for this label's preview.",
                ),
                1,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                8,
            )
            template.Add(value_actions, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 8)
            section_actions = wx.BoxSizer(wx.HORIZONTAL)
            section_actions.Add(
                KobeeAction(self._active_parent, "Add section [ ]", self._add_multipart_section),
                0,
            )
            section_actions.Add(
                wx.StaticText(
                    self._active_parent,
                    label="Adds brackets at the cursor; type or insert a project value inside.",
                ),
                1,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                8,
            )
            template.Add(section_actions, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 8)
            self.variable_status = wx.StaticText(self._active_parent, label="")
            self.variable_status.Wrap(430)
            template.Add(self.variable_status, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 10)
            actions = wx.BoxSizer(wx.HORIZONTAL)
            actions.Add(KobeeAction(self._active_parent, "Save as new…", self._save_variable_template), 0, wx.RIGHT, 7)
            self.variable_template_update = KobeeAction(self._active_parent, "Update", self._update_variable_template)
            self.variable_template_delete = KobeeAction(self._active_parent, "Delete", self._delete_variable_template)
            actions.Add(self.variable_template_update, 0, wx.RIGHT, 7)
            actions.Add(self.variable_template_delete, 0)
            template.Add(actions, 0, wx.EXPAND)
            saved.Bind(wx.EVT_CHOICE, self._on_variable_template_changed)
            available.Bind(wx.EVT_CHOICE, self._insert_selected_variable)
            self._refresh_variable_templates()
            multipart = self._card("Multipart label")
            multipart_note = wx.StaticText(
                self._active_parent,
                label=(
                    "Two or more [bracketed sections] automatically make one multipart label. "
                    "For example: [${PROJECT_NUMBER}] [Rev ${KOBEE_REVISION}] "
                    "[${KOBEE_HARDWARE_VERSION}]"
                ),
            )
            multipart_note.Wrap(430)
            multipart.Add(multipart_note, 0, wx.EXPAND | wx.BOTTOM, 10)
            multipart_grid = self._grid(multipart)
            self._add(multipart_grid, "MultiPartStartCapChoice", "Start end", self.choice(CAP_LABELS, "Rounded"))
            self._add(multipart_grid, "MultiPartEndCapChoice", "End end", self.choice(CAP_LABELS, "Square"))
            self._add(multipart_grid, "MultiPartSeparatorChoice", "Section separator", self.choice(("\\", "/", "|"), "\\"))
            self._add(multipart_grid, "MultiPartGapCtrl", "Section gap (mm)", self.spin(0, 20, 0.35, 0.05))
            self._add(multipart_grid, "MultiPartSeparatorDepthCtrl", "Slash depth (mm)", self.spin(0, 20, 0.75, 0.05))
            multipart.Add(wx.StaticText(self._active_parent, label="Per-section horizontal padding"), 0, wx.TOP | wx.BOTTOM, 8)
            padding_grid = self._grid(multipart)
            self._add(padding_grid, "MultiPartStartLeftPaddingCtrl", "Start left (mm)", self.spin(0, 100, 1.2, 0.1))
            self._add(padding_grid, "MultiPartStartRightPaddingCtrl", "Start right (mm)", self.spin(0, 100, 1.2, 0.1))
            self._add(padding_grid, "MultiPartMiddleLeftPaddingCtrl", "Middle left (mm)", self.spin(0, 100, 1.2, 0.1))
            self._add(padding_grid, "MultiPartMiddleRightPaddingCtrl", "Middle right (mm)", self.spin(0, 100, 1.2, 0.1))
            self._add(padding_grid, "MultiPartEndLeftPaddingCtrl", "End left (mm)", self.spin(0, 100, 1.2, 0.1))
            self._add(padding_grid, "MultiPartEndRightPaddingCtrl", "End right (mm)", self.spin(0, 100, 1.2, 0.1))
            for key in (
                "MultiPartStartCapChoice", "MultiPartEndCapChoice",
                "MultiPartSeparatorChoice", "MultiPartGapCtrl",
                "MultiPartSeparatorDepthCtrl", "MultiPartStartLeftPaddingCtrl",
                "MultiPartStartRightPaddingCtrl", "MultiPartMiddleLeftPaddingCtrl",
                "MultiPartMiddleRightPaddingCtrl", "MultiPartEndLeftPaddingCtrl",
                "MultiPartEndRightPaddingCtrl",
            ):
                self.controls[key].Bind(wx.EVT_TEXT, self._on_multipart_control_changed)
                self.controls[key].Bind(wx.EVT_CHOICE, self._on_multipart_control_changed)
                self.controls[key].Bind(wx.EVT_SPINCTRLDOUBLE, self._on_multipart_control_changed)
            self._build_container(LABEL_SHAPE_LABELS)
            self._build_typography(padding=True, width=True)
            details = self._card("Text details")
            details_grid = self._grid(details)
            self._add(details_grid, "UnderlineCheckbox", "Underline", self.checkbox("Enable", False))
            self._add(details_grid, "UnderlineThicknessCtrl", "Underline thickness (mm)", self.spin(0.05, 5, 0.15, 0.05))
            self._add(details_grid, "UnderlineGapCtrl", "Underline gap (mm)", self.spin(0, 10, 0.12, 0.05))
            self._add(details_grid, "OverlineCheckbox", "Overline", self.checkbox("Enable", False))
            self._add(details_grid, "OverlineThicknessCtrl", "Overline thickness (mm)", self.spin(0.05, 5, 0.15, 0.05))
            self._add(details_grid, "OverlineGapCtrl", "Overline gap (mm)", self.spin(0, 10, 0.12, 0.05))
            self.controls["OverlineCheckbox"].Bind(wx.EVT_CHECKBOX, self._on_text_details_changed)
            markup = self._add(details_grid, "inlineFormatTextbox", "Text formatting", self.checkbox("Enable", False))
            markup.SetToolTip("KiCad syntax: D_{0} for subscript, V^{2} for superscript, ~{RESET} for overline, !{text} for underline.")
            self._add(details_grid, "lineoverStyleChoice", "Overline style", self.choice(("Square", "Rounded"), "Rounded"))
            self._add(details_grid, "lineoverThicknessCtrl", "Overline weight", self.integer_spin(1, 10, 1))
            self._add_formatting_hint(details)
            self.controls["UnderlineCheckbox"].Bind(wx.EVT_CHECKBOX, self._on_text_details_changed)
            self.controls["inlineFormatTextbox"].Bind(wx.EVT_CHECKBOX, self._on_text_details_changed)
            self._update_text_details_ui()
        elif self.label == "Standard":
            content = self._card("Content")
            self._build_content(content, multiline=True, subtitle=True, icon=True, preset=True)
            self._build_container(LABEL_SHAPE_LABELS)
            self._build_typography(padding=True, subtitle=True, width=True)
            self._update_content_ui()
            extras = self._card("Text details")
            grid = self._grid(extras)
            self._add(grid, "UnderlineCheckbox", "Underline", self.checkbox("Enable", False))
            self._add(grid, "UnderlineThicknessCtrl", "Underline thickness (mm)", self.spin(0.05, 5, 0.15, 0.05))
            self._add(grid, "UnderlineGapCtrl", "Underline gap (mm)", self.spin(0, 10, 0.12, 0.05))
            self._add(grid, "OverlineCheckbox", "Overline", self.checkbox("Enable", False))
            self._add(grid, "OverlineThicknessCtrl", "Overline thickness (mm)", self.spin(0.05, 5, 0.15, 0.05))
            self._add(grid, "OverlineGapCtrl", "Overline gap (mm)", self.spin(0, 10, 0.12, 0.05))
            self.controls["OverlineCheckbox"].Bind(wx.EVT_CHECKBOX, self._on_text_details_changed)
            markup = self._add(grid, "inlineFormatTextbox", "Text formatting", self.checkbox("Enable", False))
            markup.SetToolTip("KiCad syntax: D_{0} for subscript, V^{2} for superscript, ~{RESET} for overline, !{text} for underline.")
            self._add(grid, "lineoverStyleChoice", "Overline style", self.choice(("Square", "Rounded"), "Rounded"))
            lineover = self.integer_spin(1, 10, 1)
            self._add(grid, "lineoverThicknessCtrl", "Overline weight", lineover)
            self._add_formatting_hint(extras)
            character_row = wx.BoxSizer(wx.HORIZONTAL)
            character_row.Add(wx.StaticText(self._active_parent, label="Insert"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            for character in ("Ω", "μ", "²", "°", "№", "/", "\\"):
                button = ThemedTextButton(
                    self._active_parent,
                    character,
                    lambda value=character: self._insert_character(value),
                )
                character_row.Add(button, 0, wx.RIGHT, 4)
            extras.Add(character_row, 0, wx.EXPAND | wx.TOP, 16)
            self.controls["UnderlineCheckbox"].Bind(
                wx.EVT_CHECKBOX, self._on_text_details_changed
            )
            self.controls["inlineFormatTextbox"].Bind(
                wx.EVT_CHECKBOX, self._on_text_details_changed
            )
            self._update_text_details_ui()
        elif self.label == "Connector Overlay":
            content = self._card("Connector")
            self._build_content(content, multiline=True)
            grid = self._grid(content)
            pitch_choice = self._add(grid, "HeaderPitchChoice", "Pitch", self.choice(HEADER_PITCH_CHOICES, "2.54 mm"))
            custom_pitch = self._add(grid, "HeaderCustomPitchCtrl", "Custom pitch (mm)", self.spin(0.5, 20, 2.54, 0.01))
            self.header_pitch_limit = wx.StaticText(self._active_parent, label="")
            content.Add(self.header_pitch_limit, 0, wx.EXPAND | wx.TOP, 7)
            pin_count = self._add(grid, "HeaderPinCountCtrl", "Pins", self.integer_spin(1, 40, 4))
            orientation = self._add(grid, "HeaderOrientationChoice", "Orientation", self.choice(("Vertical", "Horizontal"), "Vertical"))
            self._add(grid, "HeaderPinSideChoice", "Pins on", self.choice(("Left", "Right"), "Left"))
            self._add(grid, "HeaderPin1Choice", "Pin 1 end", self.choice(("Start", "End"), "Start"))
            self._add(grid, "HeaderPin1MarkerCheckbox", "Pin 1 marker", self.checkbox("Show marker", True))
            opening = self._card("Opening & spacing")
            grid = self._grid(opening)
            self._add(grid, "HeaderOpeningChoice", "Opening", self.choice(OPENING_LABELS, "Continuous plug opening"))
            self._add(
                grid,
                "HeaderCutoutEdgeChoice",
                "Cutout edge",
                self.choice(CONTINUOUS_CUTOUT_CHOICES, "Pill cutout"),
            )
            self._add(
                grid,
                "HeaderIndividualCutoutEdgeChoice",
                "Per-pin cutout edge",
                self.choice(INDIVIDUAL_CUTOUT_CHOICES, "Round cutout"),
            )
            self._add(
                grid,
                "HeaderCutoutRadiusCtrl",
                "Rounded corner radius (mm)",
                self.spin(0, 100, 0.5, 0.05),
            )
            self._add(grid, "HeaderPadClearanceCtrl", "Pin / opening width (mm)", self.spin(0.1, 100, 2.0, 0.1))
            self._add(grid, "HeaderOpeningEndPaddingCtrl", "Opening end pad (mm)", self.spin(0, 100, 0, 0.1))
            self._add(grid, "HeaderLeadingPaddingCtrl", "Pin 1 end pad (mm)", self.spin(0, 100, 0.3, 0.1))
            self._add(grid, "HeaderTrailingPaddingCtrl", "Far end pad (mm)", self.spin(0, 100, 0.3, 0.1))
            self._add(grid, "HeaderLabelPaddingCtrl", "Label row padding (mm)", self.spin(0, 20, 0.3, 0.1))
            self._add(grid, "HeaderPinOuterPaddingCtrl", "Outside pin padding (mm)", self.spin(0, 100, 0.3, 0.1))
            self._add(grid, "HeaderPinToLabelGapCtrl", "Pin-to-label gap (mm)", self.spin(0, 100, 0.3, 0.1))
            self._add(grid, "HeaderLabelOuterPaddingCtrl", "Outside label padding (mm)", self.spin(0, 100, 0.3, 0.1))
            self._add(grid, "HeaderCrossSizeCtrl", "Minimum rail size (mm)", self.spin(0, 100, 0, 0.1))
            self._build_container(HEADER_SHAPE_LABELS)
            self._build_typography(padding=False)
            pin_count.Bind(wx.EVT_SPINCTRL, self._on_header_pin_count_changed)
            pin_count.Bind(wx.EVT_TEXT, self._on_header_pin_count_changed)
            orientation.Bind(wx.EVT_CHOICE, self._on_header_orientation_changed)
            pitch_choice.Bind(wx.EVT_CHOICE, self._on_header_pitch_changed)
            custom_pitch.Bind(wx.EVT_TEXT, self._on_header_custom_pitch_changed)
            custom_pitch.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_header_custom_pitch_changed)
            self.controls["HeaderOpeningChoice"].Bind(
                wx.EVT_CHOICE, self._on_header_opening_changed
            )
            self.controls["HeaderCutoutEdgeChoice"].Bind(
                wx.EVT_CHOICE, self._on_header_opening_changed
            )
            self.controls["HeaderIndividualCutoutEdgeChoice"].Bind(
                wx.EVT_CHOICE, self._on_header_opening_changed
            )
            self._update_header_opening_ui()
            self._on_header_pitch_changed(None)
        elif self.label in ("Component Callout", "Component Array"):
            array = self.label == "Component Array"
            component_default_label = (
                STUDIO_DEFAULTS["ComponentPresetChoice"]
                if array
                else "Tactile switch (6 × 6 mm)"
            )
            component_default = COMPONENT_PRESET_BY_LABEL.get(component_default_label)
            content = self._card("Content")
            self._build_content(content, multiline=array, subtitle=not array, icon=not array, preset=False)
            if not array:
                self.controls["MultiLineText"].ChangeValue("BUTTON")
            component = self._card("Component safe zone")
            grid = self._grid(component)
            component_choices = tuple(label for label, item in self.dialog.component_preset_entries())
            preset_choice = self._add(grid, "ComponentPresetChoice", "Package / envelope", self.choice(component_choices, component_default_label))
            self._add(grid, "ComponentPositionChoice", "Component position", self.choice(COMPONENT_POSITION_LABELS, "Left of text"))
            self._add(grid, "ComponentCutoutChoice", "Safe-zone shape", self.choice(COMPONENT_CUTOUT_LABELS, "Rounded rectangle"))
            self._add(grid, "ComponentWidthCtrl", "Envelope width (mm)", self.spin(0.1, 100, component_default.width_mm if component_default else 2.2, 0.1))
            self._add(grid, "ComponentHeightCtrl", "Envelope height (mm)", self.spin(0.1, 100, component_default.height_mm if component_default else 1.1, 0.1))
            self._add(grid, "ComponentClearanceCtrl", "Extra clearance (mm)", self.spin(0, 50, 0.3, 0.05))
            self._add(grid, "ComponentCutoutRadiusCtrl", "Safe-zone radius (mm)", self.spin(0, 50, component_default.cutout_radius_mm if component_default else 0.2, 0.05))
            self._add(grid, "ComponentTextGapCtrl", "Component-to-text gap (mm)", self.spin(0, 100, 2.6, 0.1))
            self._add(grid, "ComponentMinWidthCtrl", "Minimum width (mm)", self.spin(0, 200, 0, 0.5))
            self._add(grid, "ComponentMinHeightCtrl", "Minimum height (mm)", self.spin(0, 200, 0, 0.5))
            if array:
                array_box = self._card("Array")
                grid = self._grid(array_box)
                array_count = self._add(grid, "ComponentArrayCountCtrl", "Component count", self.integer_spin(2, 16, 3))
                self._add(grid, "ComponentArrayOrientationChoice", "Array direction", self.choice(COMPONENT_ARRAY_ORIENTATION_LABELS, "Vertical stack"))
                self._add(grid, "ComponentArrayPitchCtrl", "Centre spacing (mm)", self.spin(0.1, 100, 5, 0.1))
                array_count.Bind(wx.EVT_SPINCTRL, self._on_component_array_count_changed)
                array_count.Bind(wx.EVT_TEXT, self._on_component_array_count_changed)
            self._build_container(COMPONENT_SHAPE_LABELS)
            self._build_typography(padding=True, subtitle=not array)
            self._update_content_ui()
            preset_choice.Bind(wx.EVT_CHOICE, self._on_component_preset_changed)
            self.controls["ComponentCutoutChoice"].Bind(
                wx.EVT_CHOICE, self._on_component_cutout_changed
            )
            self._update_component_safe_zone_ui()
        elif self.label == "Imported Graphic":
            source = self._card("Graphic file")
            grid = self._grid(source)
            self._graphic_assets = tuple(
                item for store in (self.dialog.global_asset_store, self.dialog.project_asset_store)
                if store is not None for item in store.list("graphics")
            )
            self._graphic_visible_assets = self._graphic_assets
            self._graphic_fallback_svg = ""; self._graphic_fallback_id = ""; self._graphic_missing = False
            choose_row = wx.BoxSizer(wx.HORIZONTAL)
            choose_row.Add(
                KobeeAction(self._active_parent, "Choose PNG or SVG…", self._choose_graphic_file),
                0,
                wx.RIGHT,
                8,
            )
            choose_row.Add(
                wx.StaticText(
                    self._active_parent,
                    label="Imports for this label only; it is not added to your library.",
                ),
                1,
                wx.ALIGN_CENTER_VERTICAL,
            )
            source.Add(choose_row, 0, wx.EXPAND | wx.BOTTOM, 10)
            self.graphic_source_status = wx.StaticText(
                self._active_parent,
                label="No file selected. Choose a PNG or SVG, or use a reusable graphic below.",
            )
            self.graphic_source_status.Wrap(430)
            source.Add(self.graphic_source_status, 0, wx.EXPAND | wx.BOTTOM, 10)
            source.Add(wx.StaticText(self._active_parent, label="Reusable graphics"), 0, wx.BOTTOM, 4)
            search = self._add(grid, "GraphicSearchCtrl", "Search", wx.SearchCtrl(self._active_parent, style=wx.TE_PROCESS_ENTER))
            search.SetDescriptiveText("Name, category, or scope")
            choices = tuple("{}  ·  {}".format(item.name, item.scope) for item in self._graphic_visible_assets) or ("No reusable graphics",)
            asset_choice = self._add(grid, "GraphicAssetChoice", "Graphic", self.choice(choices, choices[0]))
            transform = self._card("Transform")
            grid = self._grid(transform)
            graphic_width = self._add(grid, "GraphicWidthCtrl", "Width (mm)", self.spin(0.1, 1000, 20, 0.1))
            graphic_height = self._add(grid, "GraphicHeightCtrl", "Height (mm)", self.spin(0.1, 1000, 20, 0.1))
            aspect_lock = self._add(grid, "GraphicAspectLock", "Aspect ratio", self.checkbox("Lock aspect ratio", True))
            self._add(grid, "GraphicOffsetXCtrl", "Anchor X (mm)", self.spin(-1000, 1000, 0, 0.1))
            self._add(grid, "GraphicOffsetYCtrl", "Anchor Y (mm)", self.spin(-1000, 1000, 0, 0.1))
            self._add(grid, "GraphicRotationCtrl", "Rotation (degrees)", self.spin(-360, 360, 0, 1))
            self._add(grid, "GraphicMirrorHorizontal", "Mirror", self.checkbox("Horizontal", False))
            self._add(grid, "GraphicMirrorVertical", "Mirror", self.checkbox("Vertical", False))
            note = wx.StaticText(self._active_parent, label="Use Settings → Asset library only to save, edit, or organise reusable graphics.")
            transform.Add(note, 0, wx.EXPAND | wx.TOP, 12)
            search.Bind(wx.EVT_TEXT, self._on_graphic_search_changed)
            asset_choice.Bind(wx.EVT_CHOICE, self._on_graphic_asset_changed)
            for event_type in (wx.EVT_TEXT, wx.EVT_SPINCTRLDOUBLE):
                graphic_width.Bind(event_type, self._on_graphic_dimension_changed)
                graphic_height.Bind(event_type, self._on_graphic_dimension_changed)
            aspect_lock.Bind(wx.EVT_CHECKBOX, self._on_graphic_aspect_lock)
            self._graphic_aspect_ratio = 1.0; self._updating_graphic_size = False
            self._on_graphic_asset_changed(None)
        elif self.family == "board_tools":
            box = self._card("Board cleanup" if self.label == "Cleanup" else "Designator automation")
            if self.dialog.editor_session is None:
                box.Add(wx.StaticText(self._active_parent, label="Open Kobee Studio from KiCad PCB Editor to use board tools."), 0, wx.ALL, 8)
            elif self.label == "Cleanup":
                box.Add(wx.StaticText(self._active_parent, label="Safely update selected footprints or the whole board in one undoable KiCad operation."), 0, wx.BOTTOM, 12)
                self._add_cleanup_operation(
                    box,
                    "Remove designators",
                    "Hide native reference fields and remove linked Kobee designator labels. Component silkscreen remains unchanged.",
                    "designators",
                    "RemoveDesignatorBefore.png",
                    "RemoveDesignatorAfter.png",
                )
                self._add_cleanup_operation(
                    box,
                    "Remove silkscreen",
                    "Remove component graphics and free text on front and back silk. Existing Kobee designator labels are preserved.",
                    "silkscreen",
                    "RemoveSilkscreenBefore.png",
                    "RemoveSilkscreenAfter.png",
                )
            else:
                box.Add(wx.StaticText(self._active_parent, label="Create styled labels from footprint references at their existing anchors."), 0, wx.BOTTOM, 12)
                grid = self._grid(box)
                scope = self._add(grid, "DesignatorScopeChoice", "Apply to", self.choice(("Selected footprints", "Whole board"), "Selected footprints"))
                self._designator_profiles = self.dialog.profile_store.list("labels")
                profile = self._add(
                    grid, "DesignatorProfileChoice", "Saved label style",
                    self.choice(("Current settings",) + tuple(item.name for item in self._designator_profiles), "Current settings"),
                )
                reference = wx.TextCtrl(self._active_parent, value="Select a footprint in KiCad", style=wx.TE_READONLY)
                self._add(grid, "MultiLineText", "Preview reference", reference)
                self.designator_status = wx.StaticText(self._active_parent, label="")
                self.designator_status.Wrap(420)
                box.Add(self.designator_status, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 10)
                actions = wx.BoxSizer(wx.HORIZONTAL)
                automatic = wx.StaticText(self._active_parent, label="KiCad selection updates automatically")
                actions.Add(automatic, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 7)
                self.designator_apply_button = KobeeAction(self._active_parent, "Apply designators", self.dialog.apply_designators_from_page, primary=True)
                self.designator_apply_button.Disable()
                actions.Add(self.designator_apply_button, 0)
                box.Add(actions, 0, wx.EXPAND)

                content = self._card("Content")
                content.Add(wx.StaticText(self._active_parent, label="Layout"), 0, wx.BOTTOM, 4)
                layout = self.segmented(("Label", "Label + symbol"), "Label")
                content.Add(layout, 0, wx.EXPAND | wx.BOTTOM, 9)
                self.controls["ContentModeChoice"] = layout; self._bind(layout)
                symbol_label = wx.StaticText(self._active_parent, label="Symbol")
                symbol = PickerButton(
                    self._active_parent, "Choose a symbol", "No icon", kind="symbol",
                    callback=self._choose_icon, symbol_catalog=self.dialog.symbol_catalog,
                )
                content.Add(symbol_label, 0, wx.BOTTOM, 4); content.Add(symbol, 0, wx.EXPAND | wx.BOTTOM, 9)
                self.controls["IconChoice"] = symbol
                self._content_widgets["symbol"] = (symbol_label, symbol)
                grid = self._grid(content)
                self._add(
                    grid,
                    "ContentLayoutChoice",
                    "Reference layout",
                    self.choice(CONTENT_LAYOUT_LABELS, "Single text"),
                )
                self._add(grid, "SubtitleCtrl", "Detail line", self.text(""))
                self.controls["ContentLayoutChoice"].Bind(wx.EVT_CHOICE, self._on_content_layout_changed)
                self._add(
                    grid,
                    "IconPositionChoice",
                    "Symbol position",
                    self.choice(("Left of text", "Right of text", "Above text", "Below text"), "Left of text"),
                )
                icon_height = self._add(grid, "IconHeightCtrl", "Symbol size (mm)", self.spin(0, 20, 0, 0.1))
                icon_height._kobee_auto_value_resolver = lambda: self.controls["HeightCtrl"].GetValue()
                self._add(grid, "IconGapCtrl", "Symbol gap (mm)", self.spin(0, 20, 0.3, 0.1))
                layout.Bind(wx.EVT_CHOICE, self._on_content_mode_changed)
                scope.Bind(wx.EVT_CHOICE, self.dialog.on_designator_scope_changed)
                profile.Bind(wx.EVT_CHOICE, self._on_designator_profile_changed)
                self._build_container(LABEL_SHAPE_LABELS)
                self._build_typography(padding=True, subtitle=True, width=True)
                self._update_content_ui()
        else:
            barcode = self.label == "Barcode"
            code = self._card("Code 128 barcode" if barcode else "QR code")
            payload = self.text(
                "KOBEE-001"
                if barcode
                else MODE_DEFAULTS["QR / Barcode"]["MultiLineText"],
                not barcode,
            )
            if barcode:
                payload.SetMaxLength(48)
            code.Add(wx.StaticText(self._active_parent, label="Payload"), 0, wx.TOP | wx.BOTTOM, 7)
            code.Add(payload, 0, wx.EXPAND | wx.BOTTOM, 9)
            self.controls["MultiLineText"] = payload
            self._bind(payload)
            grid = self._grid(code)
            self._add(grid, "MachineCodeModuleSizeCtrl", "Module size (mm)", self.spin(CODE128_MIN_MODULE_MM if barcode else QR_MIN_MODULE_MM, 5, CODE128_DEFAULT_MODULE_MM if barcode else QR_MIN_MODULE_MM, 0.05))
            if barcode:
                self._add(grid, "MachineCodeBarHeightCtrl", "Bar height (mm)", self.spin(CODE128_MIN_HEIGHT_MM, 100, CODE128_DEFAULT_HEIGHT_MM, 0.5, 1))
            else:
                self._add(grid, "MachineCodePresentationChoice", "Presentation", self.choice(QR_PRESENTATION_LABELS, "Rounded frame + footer"))
                self._add(grid, "MachineCodeFramePaddingCtrl", "Extra frame gap (mm)", self.spin(0, 10, 0.2, 0.05))
            presentation = self._card("Presentation")
            grid = self._grid(presentation)
            if not barcode:
                caption = self.text("SCAN ME")
                caption.SetMaxLength(32)
                self._add(grid, "MachineCodeCaptionCtrl", "Footer text", caption)
                self._add(grid, "MachineCodeCaptionHeightCtrl", "Footer height (mm)", self.spin(0.8, 10, 1.2, 0.1, 1))
            self._add(grid, "MachineCodeShowContentCheckbox", "Readable text", self.checkbox("Show text below code", False))
            readable_text = self.text("kobee.com.au" if not barcode else "KOBEE-001")
            readable_text.SetMaxLength(96)
            self._add(grid, "MachineCodeContentCtrl", "Text below code", readable_text)
            self._add(grid, "MachineCodeContentHeightCtrl", "Text height (mm)", self.spin(0.6, 10, 0.9, 0.1, 1))
            self._add(grid, "MachineCodeContentGapCtrl", "Text gap (mm)", self.spin(0, 10, 0.5, 0.1, 1))
            if not barcode:
                self.controls["MachineCodePresentationChoice"].Bind(
                    wx.EVT_CHOICE, self._on_machine_code_changed
                )
            self.controls["MachineCodeShowContentCheckbox"].Bind(
                wx.EVT_CHECKBOX, self._on_machine_code_changed
            )
            self._update_machine_code_ui()

    def _variable_template_store(self):
        if (
            self.controls["VariableSaveScopeChoice"].GetStringSelection() == "This project"
            and self.dialog.project_variable_template_store is not None
        ):
            return self.dialog.project_variable_template_store
        return self.dialog.global_variable_template_store

    def _refresh_variable_templates(self, selected_id=None):
        if "VariableTemplateChoice" not in self.controls:
            return
        entries = []
        for label, store in (
            ("My library", self.dialog.global_variable_template_store),
            ("This project", self.dialog.project_variable_template_store),
        ):
            if store is None:
                continue
            entries.extend(("{}  ·  {}".format(item.name, label), item, store) for item in store.list())
        self._variable_templates = tuple(entries)
        choice = self.controls["VariableTemplateChoice"]
        choice.SetItems(("New template",) + tuple(item[0] for item in entries))
        selection = 0
        if selected_id:
            selection = next(
                (index + 1 for index, (_label, item, _store) in enumerate(entries) if item.template_id == selected_id),
                0,
            )
        choice.SetSelection(selection)
        self.variable_template_update.Enable(selection > 0)
        self.variable_template_delete.Enable(selection > 0)

    def _selected_variable_template(self):
        index = self.controls["VariableTemplateChoice"].GetSelection() - 1
        return self._variable_templates[index] if 0 <= index < len(self._variable_templates) else None

    def _on_variable_template_changed(self, event):
        selected = self._selected_variable_template()
        if selected is None:
            self.variable_template_update.Disable()
            self.variable_template_delete.Disable()
        else:
            _label, template, store = selected
            self.dialog._loading = True
            try:
                self.apply(dict(template.settings))
                self.controls["VariableTemplateText"].ChangeValue(template.template_text)
                self.controls["VariableSaveScopeChoice"].SetStringSelection(
                    "This project" if store.scope == "project" else "My library"
                )
            finally:
                self.dialog._loading = False
            self.variable_template_update.Enable()
            self.variable_template_delete.Enable()
        self.dialog._preview_fingerprint = None
        self.dialog._update_variable_status()
        self.dialog.request_preview()
        event.Skip()

    def _template_style_settings(self):
        settings = self.settings(resolve_variables=False)
        for key in (
            "MultiLineText",
            "VariableTemplateChoice",
            "VariableTemplateText",
            "VariableInsertChoice",
            "VariableSaveScopeChoice",
        ):
            settings.pop(key, None)
        return settings

    def _save_variable_template(self, event=None, template_id=None, default_name=""):
        prompt = wx.TextEntryDialog(self, "Name this reusable variable label:", "Save variable template", default_name)
        try:
            if prompt.ShowModal() != wx.ID_OK:
                return
            saved = self._variable_template_store().save(
                prompt.GetValue(),
                self.controls["VariableTemplateText"].GetValue(),
                self._template_style_settings(),
                template_id=template_id,
            )
            self._refresh_variable_templates(saved.template_id)
        except (OSError, TypeError, ValueError) as error:
            wx.MessageBox(str(error), "Could not save variable template", wx.OK | wx.ICON_ERROR, self)
        finally:
            prompt.Destroy()

    def _update_variable_template(self, event=None):
        selected = self._selected_variable_template()
        if selected is None:
            return
        _label, template, store = selected
        try:
            saved = store.save(
                template.name,
                self.controls["VariableTemplateText"].GetValue(),
                self._template_style_settings(),
                template_id=template.template_id,
            )
            self._refresh_variable_templates(saved.template_id)
        except (OSError, TypeError, ValueError) as error:
            wx.MessageBox(str(error), "Could not update variable template", wx.OK | wx.ICON_ERROR, self)

    def _delete_variable_template(self, event=None):
        selected = self._selected_variable_template()
        if selected is None:
            return
        _label, template, store = selected
        if wx.MessageBox(
            "Delete the saved variable template “{}”?".format(template.name),
            "Delete variable template",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            self,
        ) != wx.YES:
            return
        try:
            store.delete(template.template_id)
            self._refresh_variable_templates()
        except (OSError, LookupError) as error:
            wx.MessageBox(str(error), "Could not delete variable template", wx.OK | wx.ICON_ERROR, self)

    def _insert_selected_variable(self, event=None):
        choice = self.controls["VariableInsertChoice"]
        # Index zero is the explanatory prompt.  Inserting immediately on
        # selection makes the interaction match the wording: pick a project
        # value and its placeholder is added at the current text cursor.
        index = choice.GetSelection() - 1
        names = getattr(self, "_available_variable_names", ())
        if not 0 <= index < len(names):
            return
        control = self.controls["VariableTemplateText"]
        control.WriteText("${" + names[index] + "}")
        control.SetFocus()
        choice.SetSelection(0)
        self.dialog.request_preview(immediate=True)

    def _refresh_variable_values(self, event=None):
        """Reload project variables before rebuilding an existing label.

        Variable labels are deliberately normal, static Kobee artwork once
        placed.  This action makes the current values explicit in the preview;
        the normal Update artwork action then writes that rebuilt artwork back
        into the selected footprint.
        """
        self.dialog.prepare_variables()
        self.dialog.request_preview(immediate=True)

    def _add_multipart_section(self, event=None):
        """Insert an editable [] section at the current template cursor."""
        control = self.controls["VariableTemplateText"]
        editor = control.editor
        current = control.GetValue()
        # A multipart label needs two sections. On the first click create both
        # visible blank containers immediately. If the user already typed a
        # normal label, retain it as the first section and add an empty second.
        if not current.strip() or current.strip() == "[]":
            control.ChangeValue("[] []")
            editor.SetInsertionPoint(1)
            control.SetFocus()
            self.dialog.request_preview(immediate=True)
            return
        try:
            multipart_sections(current)
        except ValueError:
            converted = "[{}] []".format(current.strip())
            control.ChangeValue(converted)
            editor.SetInsertionPoint(len(converted) - 1)
            control.SetFocus()
            self.dialog.request_preview(immediate=True)
            return
        insertion = editor.GetInsertionPoint()
        prefix = " " if insertion > 0 and not current[insertion - 1].isspace() else ""
        control.WriteText(prefix + "[]")
        editor.SetInsertionPoint(insertion + len(prefix) + 1)
        control.SetFocus()
        self.dialog.request_preview(immediate=True)

    def _on_variable_template_text_changed(self, event):
        self.dialog._update_variable_status()
        if not self.dialog._loading:
            self.dialog.request_preview(immediate=True)
        event.Skip()

    def _on_multipart_control_changed(self, event):
        if not self.dialog._loading:
            self.dialog.request_preview(immediate=True)
        event.Skip()

    def _insert_character(self, value):
        control = self.controls["MultiLineText"]
        control.WriteText(value)
        control.SetFocus()

    def _on_designator_profile_changed(self, event):
        index = self.controls["DesignatorProfileChoice"].GetSelection()
        if index > 0 and index - 1 < len(self._designator_profiles):
            reference = self.controls["MultiLineText"].GetValue()
            scope = self.controls["DesignatorScopeChoice"].GetStringSelection()
            self.apply(self._designator_profiles[index - 1].settings)
            self.controls["MultiLineText"].ChangeValue(reference)
            self.controls["DesignatorScopeChoice"].SetStringSelection(scope)
            self.dialog._preview_fingerprint = None
            self.dialog.request_preview()
        event.Skip()

    def _resize_lines(self, count, prefix):
        control = self.controls["MultiLineText"]
        labels = control.GetValue().splitlines()[:count]
        labels.extend(
            "{} {}".format(prefix, index)
            for index in range(len(labels) + 1, count + 1)
        )
        value = "\n".join(labels)
        if value != control.GetValue():
            control.ChangeValue(value)
            control.ShowEnd()

    def _on_header_pin_count_changed(self, event):
        self._resize_lines(self.controls["HeaderPinCountCtrl"].GetValue(), "Pin")
        event.Skip()

    def _on_header_orientation_changed(self, event):
        control = self.controls["HeaderPinSideChoice"]
        requested = control.GetStringSelection()
        horizontal = self.controls["HeaderOrientationChoice"].GetStringSelection() == "Horizontal"
        control.SetItems(("Top", "Bottom") if horizontal else ("Left", "Right"))
        if not control.SetStringSelection(requested):
            control.SetSelection(0)
        event.Skip()

    def _on_header_pitch_changed(self, event):
        if "HeaderPitchChoice" not in self.controls: return
        choice = self.controls["HeaderPitchChoice"].GetStringSelection()
        custom = choice == "Custom"
        self._set_field_visible("HeaderCustomPitchCtrl", custom)
        pitch = self._measurement_mm("HeaderCustomPitchCtrl") if custom else float(choice.split()[0])
        height = self.controls.get("HeightCtrl")
        if height is not None:
            maximum_mm = maximum_pin_label_height(pitch)
            minimum_mm, _ = height._kobee_mm_range
            height._kobee_mm_range = (minimum_mm, maximum_mm)
            height.SetRange(from_millimetres(minimum_mm, self.measurement_unit), from_millimetres(maximum_mm, self.measurement_unit))
            if event is not None and self._measurement_mm("HeightCtrl") > maximum_mm:
                self._set_measurement_mm("HeightCtrl", maximum_mm)
            height.SetToolTip("Maximum text height for this pitch: {:.2f} mm".format(maximum_mm))
            if hasattr(self, "header_pitch_limit"):
                self.header_pitch_limit.SetLabel(
                    "Maximum label height at {:.2f} mm pitch: {:.2f} mm".format(pitch, maximum_mm)
                )
        self._schedule_layout()
        if event is not None:
            self.dialog.request_preview(); event.Skip()

    def _on_header_custom_pitch_changed(self, event):
        if self.controls["HeaderPitchChoice"].GetStringSelection() == "Custom":
            self._on_header_pitch_changed(event)
        else:
            event.Skip()

    def _on_component_preset_changed(self, event):
        preset = self.dialog.component_preset(self.controls["ComponentPresetChoice"].GetStringSelection())
        if preset is not None:
            self._set_measurement_mm("ComponentWidthCtrl", preset.width_mm)
            self._set_measurement_mm("ComponentHeightCtrl", preset.height_mm)
            self.controls["ComponentCutoutChoice"].SetStringSelection(
                COMPONENT_CUTOUT_ID_TO_LABEL[preset.cutout_shape]
            )
            self._set_measurement_mm("ComponentCutoutRadiusCtrl", preset.cutout_radius_mm)
            orientation = self.controls.get("ComponentArrayOrientationChoice")
            pitch = self.controls.get("ComponentArrayPitchCtrl")
            if orientation is not None and pitch is not None:
                minimum_pitch = (
                    preset.height_mm
                    if orientation.GetStringSelection() == "Vertical stack"
                    else preset.width_mm
                )
                pitch.SetValue(
                    max(
                        pitch.GetValue(),
                        from_millimetres(minimum_pitch, self.measurement_unit),
                    )
                )
        self._update_component_safe_zone_ui()
        event.Skip()

    def _choose_graphic_file(self, event=None):
        """Embed one SVG or traced PNG for the current placed graphic only."""
        picker = wx.FileDialog(
            self,
            "Choose a PCB graphic",
            wildcard="PCB graphics (*.svg;*.png)|*.svg;*.png|SVG files (*.svg)|*.svg|PNG files (*.png)|*.png",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if picker.ShowModal() != wx.ID_OK:
                return
            source = Path(picker.GetPath())
        finally:
            picker.Destroy()

        try:
            if source.suffix.lower() == ".png":
                converter = PngTraceDialog(self, source)
                try:
                    if converter.ShowModal() != wx.ID_OK or converter.result is None:
                        return
                    result = converter.result
                finally:
                    converter.Destroy()
                geometry = result.svg.decode("utf-8")
                width, height = result.pixel_size
                aspect_ratio = width / max(1, height)
            else:
                # Validate the original SVG before embedding it in the
                # footprint metadata, and measure it for aspect-ratio lock.
                geometry = source.read_text(encoding="utf-8")
                _polygons, natural = render_svg(source, 10.0, allow_strokes=True)
                aspect_ratio = natural.width / max(0.001, natural.height)
                repair_advice = svg_import_repair_advice(geometry)
            if source.suffix.lower() == ".png":
                repair_advice = ""
        except (OSError, RuntimeError, UnicodeError, ValueError) as error:
            wx.MessageBox(str(error), "Could not import graphic", wx.OK | wx.ICON_ERROR, self)
            return

        self._graphic_fallback_id = "embedded.{}".format(source.stem)
        self._graphic_fallback_svg = geometry
        # The source is deliberately not added to either asset store. The
        # embedded SVG follows this placed graphic; Settings is only for a
        # reusable library item.
        self._graphic_missing = True
        self._graphic_aspect_ratio = aspect_ratio
        width = self._measurement_mm("GraphicWidthCtrl")
        self._set_measurement_mm("GraphicHeightCtrl", width / max(0.001, aspect_ratio))
        self.graphic_source_status.SetLabel(
            "Current file: {} — embedded for this placement only.{}".format(
                source.name,
                "\nSVG repair: Kobee closed open paths. For best fidelity, export outlined, closed filled paths."
                if repair_advice else "",
            )
        )
        self.graphic_source_status.Wrap(430)
        self._schedule_layout()
        self.dialog._preview_fingerprint = None
        self.dialog.request_preview()

    def _on_graphic_asset_changed(self, event):
        if not getattr(self, "_graphic_visible_assets", ()): return
        index = self.controls["GraphicAssetChoice"].GetSelection()
        if 0 <= index < len(self._graphic_visible_assets):
            try:
                asset = self._graphic_visible_assets[index]
                if event is not None:
                    self._graphic_missing = False
                    self._graphic_fallback_id = asset.asset_id
                self._graphic_fallback_svg = asset.path.read_text(encoding="utf-8")
                self.graphic_source_status.SetLabel(
                    "Reusable graphic: {} · {}. Manage reusable graphics in Settings → Asset library.".format(asset.name, asset.scope)
                )
                self.graphic_source_status.Wrap(430)
                self._schedule_layout()
                _, natural = render_svg(asset.path, 10.0, allow_strokes=True)
                self._graphic_aspect_ratio = natural.width / natural.height
                width = self._measurement_mm("GraphicWidthCtrl")
                self._set_measurement_mm("GraphicHeightCtrl", width * natural.height / natural.width)
            except (OSError, ValueError): pass
        if event is not None:
            self.dialog.request_preview(); event.Skip()

    def _on_graphic_aspect_lock(self, event):
        if self.controls["GraphicAspectLock"].GetValue():
            self._graphic_aspect_ratio = self._measurement_mm("GraphicWidthCtrl") / max(0.1, self._measurement_mm("GraphicHeightCtrl"))
        self.dialog.request_preview(); event.Skip()

    def _on_graphic_dimension_changed(self, event):
        if self.dialog._loading or self._updating_graphic_size or not self.controls["GraphicAspectLock"].GetValue():
            event.Skip(); return
        width_control = self.controls["GraphicWidthCtrl"]
        height_control = self.controls["GraphicHeightCtrl"]
        source = event.GetEventObject()
        # Native text events bubble from the numeric control's child editor
        # before the control relays its own event. Both identify the same axis.
        is_width = source in (width_control, width_control.editor)
        if not is_width and source not in (height_control, height_control.editor):
            event.Skip(); return
        self._updating_graphic_size = True
        try:
            if is_width:
                self._set_measurement_mm("GraphicHeightCtrl", self._measurement_mm("GraphicWidthCtrl") / max(0.0001, self._graphic_aspect_ratio))
            else:
                self._set_measurement_mm("GraphicWidthCtrl", self._measurement_mm("GraphicHeightCtrl") * self._graphic_aspect_ratio)
        finally:
            self._updating_graphic_size = False
        self.dialog.request_preview(); event.Skip()

    def _on_graphic_search_changed(self, event):
        query = self.controls["GraphicSearchCtrl"].GetValue().strip().casefold()
        current_id = self._graphic_fallback_id
        self._graphic_visible_assets = tuple(
            item for item in self._graphic_assets
            if query in "{} {} {}".format(item.name, item.category, item.scope).casefold()
        )
        choices = tuple("{}  ·  {}".format(item.name, item.scope) for item in self._graphic_visible_assets)
        self.controls["GraphicAssetChoice"].SetItems(choices or ("No matching graphics",))
        selected = next((index for index, item in enumerate(self._graphic_visible_assets) if item.asset_id == current_id), None)
        if selected is not None:
            self.controls["GraphicAssetChoice"].SetSelection(selected)
        elif self._graphic_visible_assets and not self._graphic_missing:
            self.controls["GraphicAssetChoice"].SetSelection(0)
            self._on_graphic_asset_changed(None)
        event.Skip()

    def _on_component_array_count_changed(self, event):
        self._resize_lines(
            self.controls["ComponentArrayCountCtrl"].GetValue(), "Component"
        )
        event.Skip()

    def _choose_preset(self, event):
        linked_catalog = self.dialog.symbol_catalog
        dialog = AssetPickerDialog(
            self,
            "Choose a quick label",
            label_picker_items(linked_catalog),
            "",
            symbol_catalog=linked_catalog,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                linked = next(
                    (
                        item
                        for item in linked_catalog.labels
                        if item.preset_id == dialog.selected_id
                    ),
                    None,
                ) if linked_catalog is not None else None
                preset = linked or PRESET_BY_ID.get(dialog.selected_id)
                if preset:
                    display_name = PRESET_ID_TO_LABEL.get(
                        dialog.selected_id,
                        "{} — {}".format(preset.category, preset.text),
                    )
                    self.controls["PresetLabelChoice"].SetStringSelection(display_name)
                    self.controls["MultiLineText"].SetValue(preset.text)
                    symbol_id = getattr(preset, "symbol_id", getattr(preset, "icon_id", ""))
                    symbol_variant = getattr(preset, "symbol_variant", "default")
                    symbol_reference = (
                        format_symbol_reference(symbol_id, symbol_variant)
                        if symbol_id
                        else ""
                    )
                    self.controls["IconChoice"].SetStringSelection(
                        ICON_ID_TO_LABEL.get(symbol_id, "No icon")
                    )
                    self._symbol_reference = symbol_reference
                    self.controls["IconChoice"].symbol_reference = symbol_reference
                    if "ContentModeChoice" in self.controls:
                        self.controls["ContentModeChoice"].SetStringSelection(
                            "Label + symbol" if symbol_reference else "Label"
                        )
                    self._update_content_ui()
                    self.dialog.request_preview()
        finally:
            dialog.Destroy()

    def _choose_icon(self, event):
        current = self._symbol_reference
        dialog = AssetPickerDialog(
            self,
            "Choose a symbol",
            icon_picker_items(self.dialog.symbol_catalog),
            current,
            symbol_catalog=self.dialog.symbol_catalog,
            one_variant_per_family=True,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self._symbol_reference = dialog.selected_id
                icon_button = self.controls["IconChoice"]
                icon_button.symbol_reference = dialog.selected_id
                if dialog.selected_id:
                    try:
                        symbol = self.dialog.symbol_catalog.resolve_reference(dialog.selected_id)
                        display_name = symbol.name if symbol.variant == "default" else "{} — {}".format(symbol.name, symbol.variant.replace("_", " ").title())
                    except ValueError:
                        display_name = "Missing symbol"
                else:
                    display_name = "No icon"
                icon_button.SetStringSelection(display_name)
                if (
                    dialog.selected_id
                    and "ContentModeChoice" in self.controls
                    and self.controls["ContentModeChoice"].GetStringSelection() == "Label"
                ):
                    self.controls["ContentModeChoice"].SetStringSelection("Label + symbol")
                self._update_content_ui()
                self.dialog.request_preview()
        finally:
            dialog.Destroy()

    def settings(self, resolve_variables=True):
        settings = {key: _control_value(control) for key, control in self.controls.items()}
        settings.pop("GraphicSearchCtrl", None)
        if "FontComboBox" in settings:
            settings["FontComboBox"] = self._font_renderer(settings["FontComboBox"])
        if "SubtitleFontChoice" in settings and settings["SubtitleFontChoice"] != MATCH_MAIN_TYPEFACE:
            settings["SubtitleFontChoice"] = self._font_renderer(settings["SubtitleFontChoice"])
        for key in MEASUREMENT_SETTING_KEYS:
            if key in settings:
                settings[key] = self._measurement_mm(key)
        if "IconChoice" in self.controls:
            if self._symbol_reference:
                asset_id, variant = parse_symbol_reference(self._symbol_reference)
                settings["SymbolAssetId"] = asset_id
                settings["SymbolVariant"] = variant
                settings["IconChoice"] = ICON_ID_TO_LABEL.get(asset_id, self.controls["IconChoice"].GetStringSelection())
            else:
                settings["SymbolAssetId"] = ""
                settings["SymbolVariant"] = "default"
                settings["IconChoice"] = "No icon"
        if "GraphicAssetChoice" in self.controls:
            selection = self.controls["GraphicAssetChoice"].GetSelection()
            if not self._graphic_missing and 0 <= selection < len(self._graphic_visible_assets):
                asset = self._graphic_visible_assets[selection]
                settings["GraphicAssetId"] = asset.asset_id
                settings["GraphicGeometrySvg"] = asset.path.read_text(encoding="utf-8")
            else:
                settings["GraphicAssetId"] = self._graphic_fallback_id
                settings["GraphicGeometrySvg"] = self._graphic_fallback_svg
        if "VariableTemplateText" in self.controls:
            raw_template = self.controls["VariableTemplateText"].GetValue()
            settings["VariableTemplateText"] = raw_template
            if resolve_variables:
                settings["MultiLineText"] = self.dialog.resolve_variable_template(raw_template)
            else:
                settings["MultiLineText"] = raw_template
            # Brackets are the multipart affordance.  This makes the result
            # match what the user typed without a separate hidden mode which
            # could leave valid sections rendering as one literal string.
            try:
                multipart_sections(raw_template)
            except ValueError:
                settings["VariableLayoutChoice"] = "Single label"
            else:
                settings["VariableLayoutChoice"] = "Multipart label"
                settings["MultiPartSectionTemplate"] = raw_template
        return settings

    def apply(self, settings):
        if "HeaderOrientationChoice" in self.controls:
            orientation = str(settings.get("HeaderOrientationChoice", "Vertical"))
            self.controls["HeaderOrientationChoice"].SetStringSelection(orientation)
            side = self.controls["HeaderPinSideChoice"]
            side.SetItems(
                ("Top", "Bottom")
                if orientation == "Horizontal"
                else ("Left", "Right")
            )
            self.controls["HeaderIndividualCutoutEdgeChoice"].SetStringSelection("Round cutout")
        saved_shape = str(settings.get("ShapeChoice", ""))
        if self.mode == "2.54 mm Pin Header" and saved_shape not in HEADER_SHAPE_LABELS:
            saved_shape = "Rounded rectangle"
        special_shape = getattr(self, "_container_special_shape", None)
        if special_shape and "IndependentEdgesChoice" in self.controls:
            independent = saved_shape == special_shape
            self.controls["IndependentEdgesChoice"].SetStringSelection(
                "Independent" if independent else "Matched"
            )
        for key, control in self.controls.items():
            if key == "ShapeChoice" and saved_shape == special_shape:
                continue
            if key in settings:
                raw_value = settings[key]
                if key in ("FontComboBox", "SubtitleFontChoice") and raw_value != MATCH_MAIN_TYPEFACE:
                    raw_value = self._font_label(raw_value)
                if key in ("StartCapChoice", "EndCapChoice"):
                    raw_value = {
                        "Skew /": "Skew left",
                        "Skew \\": "Skew right",
                    }.get(raw_value, raw_value)
                if key in MEASUREMENT_SETTING_KEYS:
                    # Older artwork may contain null/blank optional dimensions.
                    # wx numeric controls cannot accept those values, while the
                    # historical editor treated them as zero.
                    raw_value = 0.0 if raw_value in (None, "") else raw_value
                    value = from_millimetres(float(raw_value), self.measurement_unit)
                else:
                    value = raw_value
                _set_control_value(control, value)
        if "IconChoice" in self.controls:
            legacy_id = ICON_LABELS.get(settings.get("IconChoice", "No icon"), "")
            asset_id = str(settings.get("SymbolAssetId", "") or legacy_id)
            variant = str(settings.get("SymbolVariant", "default"))
            self._symbol_reference = format_symbol_reference(asset_id, variant) if asset_id else ""
            icon_button = self.controls["IconChoice"]
            icon_button.symbol_reference = self._symbol_reference
            if self._symbol_reference:
                try:
                    symbol = self.dialog.symbol_catalog.resolve_reference(self._symbol_reference)
                    display_name = symbol.name if symbol.variant == "default" else "{} — {}".format(symbol.name, symbol.variant.replace("_", " ").title())
                except ValueError:
                    display_name = ICON_ID_TO_LABEL.get(asset_id, "Missing symbol")
                icon_button.SetStringSelection(display_name)
            else:
                icon_button.SetStringSelection("No icon")
        if "GraphicAssetChoice" in self.controls:
            asset_id = str(settings.get("GraphicAssetId", ""))
            self._graphic_fallback_id = asset_id
            self._graphic_fallback_svg = str(settings.get("GraphicGeometrySvg", ""))
            self._graphic_missing = bool(asset_id)
            for index, asset in enumerate(self._graphic_assets):
                if asset.asset_id == asset_id:
                    self.controls["GraphicSearchCtrl"].ChangeValue("")
                    self._graphic_visible_assets = self._graphic_assets
                    self.controls["GraphicAssetChoice"].SetItems(tuple("{}  ·  {}".format(item.name, item.scope) for item in self._graphic_assets))
                    self.controls["GraphicAssetChoice"].SetSelection(index); self._graphic_missing = False; break
            if self._graphic_missing and self._graphic_fallback_svg:
                self.graphic_source_status.SetLabel(
                    "Embedded graphic from this placed item — not saved to the reusable library."
                )
                self.graphic_source_status.Wrap(430)
                self._schedule_layout()
            self._graphic_aspect_ratio = self._measurement_mm("GraphicWidthCtrl") / max(0.1, self._measurement_mm("GraphicHeightCtrl"))
        if "ContentModeChoice" in self.controls:
            saved_mode = settings.get("ContentModeChoice")
            if not saved_mode:
                icon = self._symbol_reference
                position = settings.get("IconPositionChoice", "")
                saved_mode = (
                    "Symbol only"
                    if icon and position == "Icon only"
                    else "Label + symbol" if icon else "Label"
                )
            self.controls["ContentModeChoice"].SetStringSelection(str(saved_mode))
        self._update_content_ui()
        self._update_container_ui()
        self._update_text_details_ui()
        self._update_header_opening_ui()
        self._update_component_safe_zone_ui()
        self._update_machine_code_ui()
        self._sync_font_favourite()
        if "HeaderPitchChoice" in self.controls:
            self._on_header_pitch_changed(None)


class StudioEditorDialog(AsyncDialog):
    """Modern, page-based Kobee Studio editor with a persistent preview."""

    def __init__(self, parent, config, buzzard, func, editor_session=None, build_label=""):
        self.config_file = config
        self.data_root = Path(config).expanduser().parent
        self.preferences_store = AppPreferencesStore(self.data_root)
        self.profile_store = SettingsProfileStore(self.data_root)
        self.preferences = self.preferences_store.load()
        effective_unit = self.preferences.measurement_unit
        self.measurement_unit = effective_unit
        set_appearance_preference(self.preferences.appearance)
        self.project_path = _active_project_path(editor_session)
        self.project_data_catalog_store = ProjectDataCatalogStore(self.data_root)
        try:
            self.project_data_catalog = self.project_data_catalog_store.load()
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self.project_data_catalog = ProjectDataCatalog.empty()
        self.project_data_store = ProjectDataStore(self.project_path) if self.project_path is not None else None
        self.project_data_record_exists = bool(self.project_data_store is not None and self.project_data_store.path.is_file())
        self.project_data_fingerprint = None
        self.project_data_recovery_error = None
        try:
            if self.project_data_store is not None:
                self.project_data_fingerprint = self.project_data_store.fingerprint()
                self.project_data = self.project_data_store.load()
            else:
                self.project_data = ProjectData.empty()
        except (OSError, TypeError, ValueError, json.JSONDecodeError, ProjectDataRecoveryError) as error:
            self.project_data = ProjectData.empty()
            self.project_data_recovery_error = str(error)
        self.global_asset_store = SvgAssetStore.global_store(self.data_root)
        self.font_store = FontLibraryStore(self.data_root)
        self.global_component_store = ComponentPresetStore.global_store(self.data_root)
        self.global_label_store = QuickLabelStore.global_store(self.data_root)
        self.global_variable_template_store = VariableTemplateStore.global_store(self.data_root)
        self.project_asset_store = (
            SvgAssetStore.project_store(self.project_path)
            if self.project_path is not None
            else None
        )
        self.project_component_store = (
            ComponentPresetStore.project_store(self.project_path)
            if self.project_path is not None else None
        )
        self.project_label_store = (
            QuickLabelStore.project_store(self.project_path)
            if self.project_path is not None
            else None
        )
        self.project_variable_template_store = (
            VariableTemplateStore.project_store(self.project_path)
            if self.project_path is not None
            else None
        )
        self.symbol_catalog = symbol_catalog_for_context(
            project=self.project_path,
            data_root=self.data_root,
            hidden_symbol_ids=self.preferences.hidden_symbol_ids,
            hidden_label_ids=self.preferences.hidden_label_ids,
        )
        title = "Kobee Studio" + (" — " + str(build_label) if build_label else "")
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.buzzard = buzzard
        self.system_font_names = tuple(self.buzzard.system_font_names())
        self.system_font_paths = self.buzzard.system_font_paths()
        for face in self.font_store.list():
            self.buzzard.register_font(face.renderer_name, face.path)
        self.func = func
        self.editor_session = editor_session
        self.updateFootprint = None
        self.artwork = None
        self.polys = []
        self.stroke_polys = []
        self.guide_polys = []
        self.error = None
        self._last_valid = None
        self._pending_preview = False
        self._preview_fingerprint = None
        self._loading = True
        self._family = "labels"
        self._tool = "Standard"
        self._last_tool_by_family = {}
        self._editing_existing = False
        self._default_applied_tools = set()
        self._recalled_profile_ids = {}
        self.restart_requested = False
        self.restart_state = None
        self._missing_font_metadata = None
        self._designator_footprints = ()
        self._designator_skipped = 0
        self._selection_fingerprint = None
        self._project_text_variables = {}
        self._output_layers = (FRONT_SILKSCREEN,)
        self._text_vectorizer = TextVectorizer(self.buzzard)
        self._timer = self.own_timer()
        self.Bind(wx.EVT_TIMER, self._on_preview_timer, self._timer)
        self._selection_timer = self.own_timer()
        self.Bind(wx.EVT_TIMER, self._on_board_selection_timer, self._selection_timer)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        settings, footprint = self._initial_settings()
        self.updateFootprint = footprint
        self._build_shell(build_label)
        for page in self.page_by_tool.values():
            page.set_measurement_unit(self.measurement_unit)
        self._route_settings(settings)
        self._default_applied_tools.add(self._tool)
        self._refresh_profile_bar()
        apply_native_theme(self, wx, _palette())
        self._loading = False
        self.Centre(wx.BOTH)
        # Let Windows paint the dialog before generating geometry for its first preview.
        wx.CallAfter(self.request_preview)
        if self._tool == "Variables":
            wx.CallAfter(self.prepare_variables)
        if self._missing_font_metadata:
            wx.CallAfter(self._offer_missing_font)

    def component_preset_entries(self):
        entries = [(item.label, item) for item in COMPONENT_PRESET_BY_LABEL.values()]
        for store in (self.global_component_store, self.project_component_store):
            if store is None: continue
            entries.extend(("{}  ·  {}".format(item.name, item.scope), item) for item in store.list())
        return tuple(entries)

    def component_preset(self, label):
        return next((item for item_label, item in self.component_preset_entries() if item_label == label), None)

    def _initial_settings(self):
        if self.editor_session is not None:
            try:
                selected = self.editor_session.selected_artwork()
                if selected is not None:
                    params, footprint = selected
                    params = dict(params)
                    params["_LoadedFootprintSettings"] = True
                    self._editing_existing = True
                    return self._normalise_loaded_settings(params), footprint
                from ..integration.connector_prefill import connector_prefill

                prefill = connector_prefill(self.editor_session.selected_items())
                if prefill is not None:
                    defaults = mode_defaults("2.54 mm Pin Header")
                    defaults.update(prefill)
                    return defaults, None
            except Exception:
                wx.LogError(traceback.format_exc())
        else:
            try:
                import pcbnew

                board = pcbnew.GetBoard()
                selected = [item for item in board.Footprints() if item.IsSelected()] if board else []
                if len(selected) == 1:
                    footprint = selected[0]
                    encoded = footprint.GetKeywords()
                    reference = footprint.GetReference().lower()
                    if encoded.startswith("kb_params=") and any(
                        marker in reference for marker in ("kibuzzard", "kobeestudio", "kobee-studio")
                    ):
                        payload = json.loads(base64.b64decode(encoded[10:]).decode("utf-8"))
                        params = payload.get("legacy_settings", payload) if payload.get("format") == "kobee-studio-composition" else payload
                        params["_LoadedFootprintSettings"] = True
                        self._editing_existing = True
                        return self._normalise_loaded_settings(params), footprint
            except Exception:
                wx.LogError(traceback.format_exc())
        defaults = mode_defaults("Label")
        defaults.update(DEFAULT_LABEL_DIMENSIONS)
        defaults["LayerComboBox"] = FRONT_SILKSCREEN
        try:
            profile = self.profile_store.load("labels")
            defaults.update(profile.settings)
            self._recalled_profile_ids["labels"] = profile.profile_id
        except (LookupError, OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return defaults, None

    @staticmethod
    def _normalise_loaded_settings(params):
        params = dict(params)
        if "HeaderPinSideChoice" not in params and "HeaderLabelSideChoice" in params:
            params["HeaderPinSideChoice"] = {
                "Above": "Bottom",
                "Below": "Top",
                "Left": "Right",
                "Right": "Left",
            }.get(str(params["HeaderLabelSideChoice"]), "Left")
        if "ShapeChoice" not in params:
            left = params.get("CapLeftChoice", "")
            right = params.get("CapRightChoice", "")
            if left == "(" and right == ")":
                params["ShapeChoice"] = "Pill"
            elif left or right:
                params["ShapeChoice"] = "Independent ends"
                params["StartCapChoice"] = "Rounded" if left == "(" else "Square"
                params["EndCapChoice"] = "Rounded" if right == ")" else "Square"
            else:
                params["ShapeChoice"] = "No container"
        return params

    def _build_shell(self, build_label):
        palette = _palette()
        self.SetBackgroundColour(palette["window"])
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)
        header = BrandedHeader(self)
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        header.SetSizer(header_sizer)
        header_sizer.AddSpacer(14)
        icon_path = (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "kobee-studio-app-icon.png"
        )
        if icon_path.is_file():
            image = wx.Image(str(icon_path)).Scale(30, 30, wx.IMAGE_QUALITY_HIGH)
            header_sizer.Add(wx.StaticBitmap(header, bitmap=wx.Bitmap(image)), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 9)
        name = wx.StaticText(header, label="Kobee Studio")
        name.SetFont(name.GetFont().Bold())
        name.SetForegroundColour(palette["text"])
        header_sizer.Add(name, 0, wx.ALIGN_CENTER_VERTICAL)
        ui_badge = wx.StaticText(header, label=__version__)
        ui_badge.SetForegroundColour(palette["muted"])
        header_sizer.Add(ui_badge, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        if build_label:
            build = wx.StaticText(header, label=str(build_label))
            build.SetForegroundColour(palette["muted"])
            header_sizer.Add(build, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        header_sizer.AddStretchSpacer(1)
        settings_button = KobeeAction(
            header,
            "Settings",
            self._open_settings,
        )
        header_sizer.Add(settings_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 7)
        help_button = KobeeAction(
            header,
            "Need help?",
            lambda: wx.LaunchDefaultBrowser(KOBEE_STUDIO_DOCS_URL),
        )
        header_sizer.Add(help_button, 0, wx.ALIGN_CENTER_VERTICAL)
        header_sizer.AddSpacer(14)
        root.Add(header, 0, wx.EXPAND)

        self.family_bar = wx.Panel(self)
        self.family_bar.SetBackgroundColour(palette["title"])
        family_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.family_bar.SetSizer(family_sizer)
        family_sizer.AddSpacer(14)
        self.family_buttons = {}
        for family, label in (("labels", "Labels"), ("graphics", "Graphics"), ("codes", "Codes"), ("board_tools", "Board Tools"), ("project_data", "Project Data")):
            button = KobeeTab(
                self.family_bar,
                label,
                lambda value=family: self._select_family(value),
                kind="family",
                icon=family,
            )
            family_sizer.Add(button, 0, wx.RIGHT, 6)
            self.family_buttons[family] = button
        family_sizer.AddStretchSpacer(1)
        root.Add(self.family_bar, 0, wx.EXPAND)

        self.tool_bar = wx.Panel(self)
        self.tool_bar.SetBackgroundColour(palette["subnav"])
        self.tool_sizer = wx.WrapSizer(wx.HORIZONTAL, flags=0)
        self.tool_bar.SetSizer(self.tool_sizer)
        self.tool_sizer.AddSpacer(14)
        self.tool_buttons = {}
        for family, label, mode in TOOL_DEFINITIONS:
            button = KobeeTab(
                self.tool_bar,
                label,
                lambda value=label: self._select_tool(value),
                kind="sub",
            )
            self.tool_sizer.Add(button, 0, wx.RIGHT, 5)
            self.tool_buttons[label] = button
        root.Add(self.tool_bar, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 6)

        # Profiles are a concise, tool-level workflow control. Keeping the
        # row separate from target layers avoids treating them as navigation.
        self.profile_bar = wx.Panel(self)
        self.profile_bar.SetBackgroundColour(palette["subnav"])
        profile_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.profile_bar.SetSizer(profile_sizer)
        profile_sizer.AddStretchSpacer(1)
        self.profile_status = wx.StaticText(self.profile_bar, label="Profile: None")
        self.profile_status.SetFont(self.profile_status.GetFont().Bold())
        self.profile_status.SetForegroundColour(palette["text"])
        profile_sizer.Add(self.profile_status, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        profile_sizer.Add(
            KobeeAction(self.profile_bar, "Load…", self._recall_profile_for_active_tool),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6,
        )
        profile_sizer.Add(
            KobeeAction(self.profile_bar, "Save…", self._save_profile_for_active_tool),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6,
        )
        profile_sizer.Add(
            KobeeAction(self.profile_bar, "?", self._show_profile_help),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14,
        )
        root.Add(self.profile_bar, 0, wx.EXPAND | wx.BOTTOM, 4)

        # Placement is a first-class decision, not a preview setting.  Keep
        # every selected PCB layer visible and independently controllable.
        self.placement_bar = wx.Panel(self)
        self.placement_bar.SetBackgroundColour(palette["subnav"])
        placement_sizer = wx.WrapSizer(wx.HORIZONTAL, flags=0)
        self.placement_bar.SetSizer(placement_sizer)
        placement_sizer.AddSpacer(14)
        placement_label = wx.StaticText(self.placement_bar, label="Place artwork on")
        placement_label.SetForegroundColour(palette["muted"])
        placement_sizer.Add(placement_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.layer_toggles = {}
        for layer in LAYER_ORDER:
            toggle = ThemedCheckBox(
                self.placement_bar,
                label=TARGET_LAYER_LABELS[layer],
                value=layer in self._output_layers,
            )
            toggle.SetToolTip(LAYER_LABELS[layer])
            toggle.Bind(wx.EVT_CHECKBOX, self._on_target_layers_changed)
            placement_sizer.Add(toggle, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            self.layer_toggles[layer] = toggle
        root.Add(self.placement_bar, 0, wx.EXPAND | wx.BOTTOM, 6)

        workspace = wx.BoxSizer(wx.HORIZONTAL)
        self.pages = wx.Simplebook(self)
        self.pages.SetBackgroundColour(palette["controls"])
        self.page_by_tool = {}
        self.page_index_by_tool = {}
        for family, label, mode in TOOL_DEFINITIONS:
            page = ProjectDataPage(self.pages, self) if family == "project_data" else ToolPage(self.pages, self, family, label, mode)
            self.pages.AddPage(page, label)
            self.page_by_tool[label] = page
            self.page_index_by_tool[label] = self.pages.GetPageCount() - 1
        # These minima fit together at the dialog's compact 760 px width. The
        # old 500 + 390 px pair forced sizers past the viewport on smaller
        # displays and during window resizing.
        self.pages.SetMinSize(wx.Size(450, 360))
        workspace.Add(self.pages, 1, wx.EXPAND | wx.RIGHT, 10)

        preview_panel = wx.Panel(self, style=wx.BORDER_NONE)
        self.preview_panel = preview_panel
        # Keep the surrounding column invisible; PreviewCanvas owns the one
        # rounded surface the user interacts with.
        preview_panel.SetBackgroundColour(palette["controls"])
        preview_root = wx.BoxSizer(wx.VERTICAL)
        preview_panel.SetSizer(preview_root)
        toolbar = wx.BoxSizer(wx.VERTICAL)
        preview_heading = wx.BoxSizer(wx.HORIZONTAL)
        preview_title = wx.StaticText(preview_panel, label="Live preview")
        preview_title.SetFont(preview_title.GetFont().Bold())
        preview_title.SetForegroundColour(palette["text"])
        preview_heading.Add(preview_title, 0, wx.ALIGN_CENTER_VERTICAL)
        toolbar.Add(preview_heading, 0, wx.EXPAND | wx.BOTTOM, 6)
        preview_controls = wx.BoxSizer(wx.VERTICAL)
        preview_layer_row = wx.BoxSizer(wx.HORIZONTAL)
        preview_layer_row.Add(wx.StaticText(preview_panel, label="Preview layer"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.layer_choice = ThemedChoice(preview_panel, choices=tuple(PREVIEW_LAYER_LABELS[layer] for layer in self._output_layers))
        self.layer_choice.SetMinSize(wx.Size(140, 30))
        self.layer_choice.SetStringSelection(PREVIEW_LAYER_LABELS[FRONT_SILKSCREEN])
        self.layer_choice.Bind(wx.EVT_CHOICE, self.on_control_changed)
        preview_layer_row.Add(self.layer_choice, 1, wx.ALIGN_CENTER_VERTICAL)
        preview_controls.Add(preview_layer_row, 0, wx.EXPAND | wx.BOTTOM, 6)
        preview_zoom_row = wx.BoxSizer(wx.HORIZONTAL)
        preview_zoom_row.AddStretchSpacer(1)
        for label, handler in (
            ("Fit", lambda: self.preview.fit()),
            ("−", lambda: self.preview.zoom(1 / 1.2)),
            ("+", lambda: self.preview.zoom(1.2)),
        ):
            button = KobeeAction(preview_panel, label, handler)
            preview_zoom_row.Add(button, 0, wx.RIGHT, 4)
        preview_controls.Add(preview_zoom_row, 0, wx.EXPAND)
        toolbar.Add(preview_controls, 0, wx.EXPAND)
        preview_root.Add(toolbar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.preview = PreviewCanvas(preview_panel)
        self.preview.SetMinSize(wx.Size(220, 300))
        preview_root.Add(self.preview, 1, wx.EXPAND | wx.TOP, 8)
        self.preview_status = wx.StaticText(preview_panel, label="Front side · Front Silkscreen")
        preview_root.Add(self.preview_status, 0, wx.TOP, 7)
        self.preview_error = wx.StaticText(preview_panel, label="")
        self.preview_error.SetForegroundColour(wx.Colour(190, 55, 45))
        self.preview_error.SetMinSize(wx.Size(-1, 34))
        preview_root.Add(self.preview_error, 0, wx.EXPAND | wx.TOP, 4)
        preview_panel.SetMinSize(wx.Size(250, -1))
        workspace.Add(preview_panel, 1, wx.EXPAND)
        root.Add(workspace, 1, wx.EXPAND)

        root.Add(wx.StaticLine(self), 0, wx.EXPAND)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.footer_shortcut = wx.StaticText(self, label="Ctrl/Shift + Enter places artwork")
        self.footer_shortcut.SetForegroundColour(palette["muted"])
        footer.Add(self.footer_shortcut, 1, wx.ALIGN_CENTER_VERTICAL)
        cancel = KobeeAction(self, "Cancel", self._cancel)
        self.place_button = KobeeAction(
            self,
            "Update artwork" if self.updateFootprint is not None else "Place artwork",
            lambda: self.OnOkClick(None),
            primary=True,
        )
        self.designator_footer_button = KobeeAction(
            self,
            "Apply designators",
            self.apply_designators_from_page,
            primary=True,
        )
        self.designator_footer_button.Disable()
        self.designator_footer_button.Hide()
        footer.Add(cancel, 0, wx.RIGHT, 7)
        footer.Add(self.place_button, 0)
        footer.Add(self.designator_footer_button, 0)
        root.Add(footer, 0, wx.EXPAND | wx.ALL, 12)

        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        display = wx.GetClientDisplayRect()
        minimum_width = min(760, max(560, display.width - 40))
        minimum_height = min(600, max(480, display.height - 40))
        self.SetMinSize(wx.Size(minimum_width, minimum_height))
        self.SetSize(wx.Size(min(1220, display.width - 50), min(780, display.height - 50)))

    def _profile_module(self):
        if self._family == "project_data":
            return None
        return profile_module_for_mode(self.active_page.mode)

    def _recall_profile_for_active_tool(self):
        module = self._profile_module()
        profiles = self.profile_store.list(module)
        dialog = ProfileRecallDialog(
            self, MODULE_LABELS_FOR_PROFILE[module], profiles, self._recalled_profile_ids.get(module)
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            if not dialog.selected_profile_id:
                self._recalled_profile_ids.pop(module, None)
                self._refresh_profile_bar()
                return
            profile = self.profile_store.load(module, dialog.selected_profile_id)
            self._recalled_profile_ids[module] = profile.profile_id
            self._apply_profile_settings(dict(profile.settings))
            self._refresh_profile_bar()
        except (OSError, ValueError, LookupError) as error:
            wx.MessageBox(str(error), "Could not recall profile", wx.OK | wx.ICON_ERROR, self)
        finally:
            dialog.Destroy()

    def _save_profile_for_active_tool(self):
        module = self._profile_module()
        recalled_id = self._recalled_profile_ids.get(module)
        recalled = None
        if recalled_id:
            try:
                recalled = self.profile_store.load(module, recalled_id)
            except (OSError, ValueError, LookupError):
                self._recalled_profile_ids.pop(module, None)
        if recalled is not None:
            choice = wx.MessageDialog(
                self,
                "You recalled “{}”. Save these current settings as a new profile, or overwrite that profile?".format(recalled.name),
                "Save profile",
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
            )
            try:
                choice.SetYesNoLabels("Save as new", "Overwrite “{}”".format(recalled.name))
                result = choice.ShowModal()
            finally:
                choice.Destroy()
            if result == wx.ID_CANCEL:
                return
            if result == wx.ID_NO:
                confirmation = wx.MessageBox(
                    "Overwrite “{}” with the current {} settings? This replaces its saved values.".format(
                        recalled.name, MODULE_LABELS_FOR_PROFILE[module].lower()
                    ),
                    "Confirm profile overwrite", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self,
                )
                if confirmation != wx.YES:
                    return
                try:
                    self.profile_store.save(module, recalled.name, self.CurrentSettings(), profile_id=recalled.profile_id)
                    self._refresh_profile_bar()
                except (OSError, ValueError) as error:
                    wx.MessageBox(str(error), "Could not overwrite profile", wx.OK | wx.ICON_ERROR, self)
                return
        prompt = wx.TextEntryDialog(self, "Profile name", "Save {} settings as a profile".format(MODULE_LABELS_FOR_PROFILE[module].lower()))
        try:
            if prompt.ShowModal() != wx.ID_OK:
                return
            profile = self.profile_store.save(module, prompt.GetValue(), self.CurrentSettings())
            self._recalled_profile_ids[module] = profile.profile_id
            self._refresh_profile_bar()
        except (OSError, ValueError) as error:
            wx.MessageBox(str(error), "Could not save profile", wx.OK | wx.ICON_ERROR, self)
        finally:
            prompt.Destroy()

    def capture_session_state(self):
        """Retain unsaved forms across a library-triggered editor rebuild."""
        pages = {}
        sections = {}
        for tool, page in self.page_by_tool.items():
            if isinstance(page, ToolPage):
                try:
                    pages[tool] = page.settings(resolve_variables=False)
                except (OSError, ValueError):
                    # A missing library file must not prevent Settings opening
                    # to repair it. Retain the other fields without reading it.
                    pages[tool] = {key: _control_value(control) for key, control in page.controls.items()
                                   if key not in MEASUREMENT_SETTING_KEYS}
                    for key in MEASUREMENT_SETTING_KEYS.intersection(page.controls):
                        pages[tool][key] = page._measurement_mm(key)
                sections[tool] = next((name for name, button in page.section_buttons.items() if button.active), None)
        active = dict(pages.get(self._tool, {}))
        active["StudioModeChoice"] = self.active_page.mode if isinstance(self.active_page, ToolPage) else "Label"
        if self._tool == "Variables":
            active["StudioTool"] = "Variables"
        active["LayerComboBox"] = self.output_layer
        active["OutputLayers"] = list(self.output_layers)
        if isinstance(self.active_page, ToolPage):
            try:
                active.update(self.CurrentSettings())
            except (OSError, ValueError):
                pass
        project_page = self.page_by_tool["Project Data"]
        return {
            "tool": self._tool, "pages": pages, "sections": sections, "active": active,
            "footprint": self.updateFootprint, "editing": self._editing_existing,
            "defaults": set(self._default_applied_tools), "profiles": dict(self._recalled_profile_ids),
            "family_tools": dict(self._last_tool_by_family),
            "project_fields": {key: _control_value(control) for key, (_field, control) in project_page.controls.items()},
            "project_dirty": project_page._dirty,
        }

    def restore_session_state(self, state):
        self._loading = True
        try:
            self.updateFootprint = state["footprint"]
            self._editing_existing = state["editing"]
            self._default_applied_tools = set(state["defaults"])
            self._recalled_profile_ids = dict(state["profiles"])
            self._last_tool_by_family = dict(state["family_tools"])
            for tool, settings in state["pages"].items():
                self.page_by_tool[tool].apply(settings)
                section = state["sections"].get(tool)
                if section in self.page_by_tool[tool].sections:
                    self.page_by_tool[tool]._show_section(section)
            if state["tool"] not in ("Project Data", "Cleanup", "Designators"):
                self._route_settings(dict(state["active"]))
            self._set_output_layers(state["active"]["OutputLayers"], state["active"]["LayerComboBox"])
            self.place_button.SetLabel("Update artwork" if self.updateFootprint is not None else "Place artwork")
        finally:
            self._loading = False
        self._tool = ""  # Run the normal workflow chrome and selection setup.
        self._select_tool(state["tool"])
        self._restore_project_draft(state)
        self.request_preview()

    def _restore_project_draft(self, state):
        project_page = self.page_by_tool["Project Data"]
        for key, value in state["project_fields"].items():
            if key in project_page.controls:
                control = project_page.controls[key][1]
                if hasattr(control, "ChangeValue"):
                    control.ChangeValue(str(value))
                else:
                    _set_control_value(control, value)
        project_page._dirty = state["project_dirty"]

    def _open_settings(self, initial_page=0):
        if not self.accepts_background_results():
            return
        session_state = self.capture_session_state()
        try:
            dialog = SettingsDialog(
                self,
                preferences_store=self.preferences_store,
                profile_store=self.profile_store,
                global_asset_store=self.global_asset_store,
                project_asset_store=self.project_asset_store,
                global_label_store=self.global_label_store,
                project_label_store=self.project_label_store,
                font_store=self.font_store,
                global_component_store=self.global_component_store,
                project_component_store=self.project_component_store,
                project_data_catalog_store=self.project_data_catalog_store,
                font_preview_renderer=self._render_font_settings_preview,
                system_font_names=self.system_font_names,
                system_font_paths=self.system_font_paths,
                symbol_catalog=symbol_catalog_for_context(
                    project=self.project_path,
                    data_root=self.data_root,
                ),
                hidden_symbol_ids=self.preferences.hidden_symbol_ids,
                hidden_label_ids=self.preferences.hidden_label_ids,
                current_module=self._profile_module(),
                initial_page=initial_page,
                preferences_changed=self._on_preferences_changed,
            )
        except Exception as error:
            traceback.print_exc()
            wx.MessageBox(
                "Kobee could not open Settings. Your project and existing settings were not changed.\n\n{}".format(error),
                "Could not open Settings", wx.OK | wx.ICON_ERROR, self,
            )
            return
        restart_requested = False
        try:
            dialog.ShowModal()
            restart_requested = dialog.restart_editor
        finally:
            dialog.Destroy()
        if restart_requested:
            # Settings changed the complete on-disk data set. Close this
            # editor instance so the host entry point can construct a fresh
            # one with the restored preferences, assets, and profiles.
            self.restart_requested = True
            self.restart_state = session_state
            self._cancel()
            return
        self._refresh_symbol_catalog()
        try:
            self.project_data_catalog = self.project_data_catalog_store.load()
            self.page_by_tool["Project Data"].reload(self.project_data, self.project_data_catalog)
            self._restore_project_draft(session_state)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        self._refresh_profile_bar()
        self.request_preview()

    def _render_font_settings_preview(self, path, renderer_name, sample):
        """Render Settings' selected face through the PCB polygon pipeline."""
        self.buzzard.register_font(renderer_name, path)
        style = DocumentStyle(
            typography=TypographyStyle(
                font_name=renderer_name,
                height_mm=2.0,
                alignment="center",
            ),
            shape=ShapeStyle(
                padding=Padding.symmetric(0.0, 0.0),
                border_thickness_mm=0.0,
            ),
        )
        return render_label_artwork(
            self._text_vectorizer,
            str(sample),
            style,
            FRONT_SILKSCREEN,
            shape=None,
        )

    def _show_profile_help(self):
        wx.MessageBox(
            "Profiles save the current settings for this tool, such as its typography, container, symbol, and target layers. "
            "Load applies a saved profile. Save lets you create a new profile or overwrite the one currently loaded. "
            "Set a default profile in Settings to apply it when starting new artwork.",
            "Profiles",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def _refresh_profile_bar(self):
        if not hasattr(self, "profile_status"):
            return
        module = self._profile_module()
        if module is None:
            self.profile_status.SetLabel("Project Data has no artwork profile")
            self.profile_bar.Layout()
            return
        profile_id = self._recalled_profile_ids.get(module)
        name = "None"
        if profile_id:
            try:
                name = self.profile_store.load(module, profile_id).name
            except (LookupError, OSError, TypeError, ValueError):
                self._recalled_profile_ids.pop(module, None)
        self.profile_status.SetLabel("Profile: {}".format(name))
        self.profile_bar.Layout()

    def _apply_profile_settings(self, settings):
        self._loading = True
        try:
            self._route_settings(dict(settings))
        finally:
            self._loading = False
        self.request_preview()

    def _on_preferences_changed(self, preferences):
        old_appearance = self.preferences.appearance
        self.preferences = preferences
        # Keep the current window on its original palette until it is reopened.
        # Painted controls consult the global preference on every repaint.
        # Switching it here mixes new fields with old panel backgrounds.
        # Settings can opt system fonts in or out while this editor is open.
        # Refresh choices immediately; no restart should be needed just to
        # use a font the user has explicitly enabled.
        for page in self.page_by_tool.values():
            if hasattr(page, "_refresh_font_choices"):
                page._refresh_font_choices()
        requested_unit = preferences.measurement_unit
        if requested_unit is not self.measurement_unit:
            self._loading = True
            try:
                for page in self.page_by_tool.values():
                    page.set_measurement_unit(requested_unit)
                self.measurement_unit = requested_unit
            finally:
                self._loading = False
            self.request_preview()
        if old_appearance != preferences.appearance:
            wx.MessageBox(
                "The appearance preference was saved and will be applied the next time Kobee Studio opens.",
                "Kobee Studio Appearance",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )

    def _refresh_symbol_catalog(self):
        self.symbol_catalog = symbol_catalog_for_context(
            project=self.project_path,
            data_root=self.data_root,
            hidden_symbol_ids=self.preferences.hidden_symbol_ids,
            hidden_label_ids=self.preferences.hidden_label_ids,
        )
        # An uploaded SVG may have changed while its selected asset ID stayed
        # the same, so the settings fingerprint alone cannot prove equivalence.
        self._preview_fingerprint = None
        for page in self.page_by_tool.values():
            button = page.controls.get("IconChoice")
            if button is not None:
                button.symbol_catalog = self.symbol_catalog

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN and (event.ControlDown() or event.ShiftDown()):
            if self._tool == "Designators":
                self.apply_designators_from_page(event)
            elif self._family != "board_tools":
                self.OnOkClick(event)
            return
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._cancel()
            return
        event.Skip()

    def _cancel(self):
        self._timer.Stop()
        self._selection_timer.Stop()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event):
        self._timer.Stop()
        self._selection_timer.Stop()
        event.Skip()

    def run_board_cleanup(self, operation, scope):
        if self.editor_session is None: return
        service = self.editor_session.board_tools()
        eligible, skipped = service.eligible(scope)
        if not eligible:
            wx.MessageBox("No eligible footprints were found.", "Board cleanup", wx.OK | wx.ICON_INFORMATION, self); return
        description = "designators" if operation == "designators" else "silkscreen graphics and free text on both sides"
        if wx.MessageBox("Remove {} from {} footprint(s)?\n\n{} locked or generated footprint(s) will be skipped.".format(description, len(eligible), skipped), "Confirm board cleanup", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES: return
        try:
            result = service.remove_designators(scope) if operation == "designators" else service.remove_silkscreen(scope)
            wx.MessageBox("Updated {} footprint(s); skipped {}. Removed {} linked/item object(s).".format(result.affected, result.skipped, result.removed_items), "Board cleanup complete", wx.OK | wx.ICON_INFORMATION, self)
        except Exception as error:
            traceback.print_exc(); wx.MessageBox(str(error), "Board cleanup failed", wx.OK | wx.ICON_ERROR, self)

    def _on_graphic_transform(self, operation, first, second):
        page = self.page_by_tool.get("Imported Graphic")
        if page is None: return
        if operation == "move":
            page._set_measurement_mm("GraphicOffsetXCtrl", page._measurement_mm("GraphicOffsetXCtrl") + first)
            page._set_measurement_mm("GraphicOffsetYCtrl", page._measurement_mm("GraphicOffsetYCtrl") + second)
        elif operation == "resize":
            if page.controls["GraphicAspectLock"].GetValue():
                old_width=max(0.1,page._measurement_mm("GraphicWidthCtrl")); old_height=max(0.1,page._measurement_mm("GraphicHeightCtrl"))
                second=first*(old_height/old_width)
            page._set_measurement_mm("GraphicWidthCtrl", first); page._set_measurement_mm("GraphicHeightCtrl", second)
        elif operation == "rotate":
            page.controls["GraphicRotationCtrl"].SetValue(first)
        self.request_preview(immediate=True)

    @staticmethod
    def _footprint_id_text(footprint):
        identifier = getattr(footprint, "id", "")
        return str(getattr(identifier, "value", identifier))

    @staticmethod
    def _reference_sort_key(footprint):
        reference = str(getattr(footprint.reference_field.text, "value", "")).strip()
        parts = tuple(
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"([0-9]+)", reference)
            if part
        )
        return parts

    def _set_designator_apply_enabled(self, enabled):
        page = self.page_by_tool.get("Designators")
        if page is not None and hasattr(page, "designator_apply_button"):
            page.designator_apply_button.Enable(bool(enabled))
        if hasattr(self, "designator_footer_button"):
            self.designator_footer_button.Enable(bool(enabled))

    def _eligible_reference_footprints(self, scope):
        service = self.editor_session.board_tools()
        footprints, skipped = service.eligible(scope)
        with_references = tuple(
            sorted(
                (
                    item for item in footprints
                    if str(getattr(item.reference_field.text, "value", "")).strip()
                ),
                key=self._reference_sort_key,
            )
        )
        return with_references, skipped + len(footprints) - len(with_references)

    def _build_designator_record(self, source, settings, existing, api):
        reference = str(source.reference_field.text.value).strip(); source_id = self._footprint_id_text(source)
        layer = self._designator_output_layer(source, api)
        local = dict(settings, MultiLineText=reference, LayerComboBox=layer, StudioModeChoice="Label")
        style = self._document_style(local)
        icon_id = str(local.get("SymbolAssetId", "") or ICON_LABELS.get(local.get("IconChoice", "No icon"), "")) if local.get("ContentModeChoice") == "Label + symbol" else ""
        variant = str(local.get("SymbolVariant", "default"))
        artwork = render_label_artwork(
            self._text_vectorizer, reference, style, layer,
            shape=LABEL_SHAPE_LABELS.get(local.get("ShapeChoice")), minimum_width_mm=float(local.get("WidthCtrl", 0)),
            icon_id=icon_id, icon_position=ICON_POSITION_LABELS.get(local.get("IconPositionChoice", "Left of text"), "left"),
            icon_height_mm=float(local.get("IconHeightCtrl", 0)), icon_gap_mm=float(local.get("IconGapCtrl", 0.3)), icon_variant=variant,
            subtitle_text=(
                str(local.get("SubtitleCtrl", ""))
                if local.get("ContentLayoutChoice") == "Title + subtitle"
                else ""
            ),
            subtitle_typography=style.secondary_typography,
            subtitle_gap_mm=float(local.get("SubtitleGapCtrl", 0.25)),
            icon_renderer=(lambda asset_id, height_mm, selected_variant=variant: render_symbol(asset_id,height_mm,selected_variant,catalog=self.symbol_catalog)),
        )
        feature = {"kind":"designator_label", "source_footprint_id":source_id, "reference":reference}
        payload = build_footprint_payload(local, document=artwork.document, feature=feature)
        return source, artwork, payload, layer, existing.get(source_id)

    @staticmethod
    def _designator_scope_id(label):
        return "board" if str(label) == "Whole board" else "selected"

    def _designator_output_layer(self, source, api=None):
        reference_layer = source.reference_field.layer
        back_values = {BOTTOM_SILKSCREEN, "B.SilkS"}
        if api is not None:
            back_values.add(api["BoardLayer"].BL_B_SilkS)
        if reference_layer in back_values:
            return BOTTOM_SILKSCREEN
        front_values = {FRONT_SILKSCREEN, "F.SilkS"}
        if api is not None:
            front_values.add(api["BoardLayer"].BL_F_SilkS)
        if reference_layer in front_values:
            return FRONT_SILKSCREEN
        if api is not None and source.layer == api["BoardLayer"].BL_B_Cu:
            return BOTTOM_SILKSCREEN
        return FRONT_SILKSCREEN

    def prepare_designators(self, scope=None, show_message=False):
        page = self.page_by_tool.get("Designators")
        if page is None or self.editor_session is None:
            return ()
        if scope in ("single", "selected", "board"):
            scope = "selected" if scope == "single" else scope
            page.controls["DesignatorScopeChoice"].SetStringSelection(
                "Whole board" if scope == "board" else "Selected footprints"
            )
        else:
            scope = self._designator_scope_id(page.controls["DesignatorScopeChoice"].GetStringSelection())
        with_references, skipped = self._eligible_reference_footprints(scope)
        fingerprint = (
            "designators",
            scope,
            tuple(
                (
                    self._footprint_id_text(item),
                    str(item.reference_field.text.value).strip(),
                    str(getattr(item.reference_field, "layer", "")),
                )
                for item in with_references
            ),
            skipped,
        )
        self._designator_footprints = with_references
        self._designator_skipped = skipped
        unchanged = fingerprint == self._selection_fingerprint
        self._selection_fingerprint = fingerprint
        if not with_references:
            page.controls["MultiLineText"].ChangeValue("Select a footprint in KiCad")
            page.designator_status.SetLabel(
                "No eligible footprints with references were found. Select an ordinary footprint in KiCad; this view updates automatically."
                if scope == "selected" else
                "No eligible board footprints with references were found."
            )
            self._set_designator_apply_enabled(False)
            self.preview.set_artwork((), (), (), FRONT_SILKSCREEN)
            self.preview_error.SetLabel("")
            if show_message:
                wx.MessageBox(page.designator_status.GetLabel(), "Designators", wx.OK | wx.ICON_INFORMATION, self)
            return ()
        if unchanged:
            self._set_designator_apply_enabled(True)
            return with_references
        reference = str(with_references[0].reference_field.text.value).strip()
        page.controls["MultiLineText"].ChangeValue(reference)
        page.designator_status.SetLabel(
            "Previewing {}. The style will be applied to {} footprint(s); {} locked, generated, or empty-reference item(s) will be skipped.".format(
                reference, len(with_references), skipped
            )
        )
        self._set_designator_apply_enabled(True)
        layer = self._designator_output_layer(with_references[0])
        self._set_output_layers((layer,), preview_layer=layer)
        self._preview_fingerprint = None
        self.request_preview()
        return with_references

    def refresh_designator_selection(self, event=None):
        self._selection_fingerprint = None
        self.prepare_designators()

    def on_designator_scope_changed(self, event):
        self._selection_fingerprint = None
        self.prepare_designators()
        self._sync_board_selection_timer()
        event.Skip()

    def _file_text_variables(self):
        if self.project_path is None:
            return {}
        project_file = Path(self.project_path).with_suffix(".kicad_pro")
        try:
            payload = json.loads(project_file.read_text(encoding="utf-8"))
            values = payload.get("text_variables", {})
            return {str(key): str(value) for key, value in values.items()} if isinstance(values, dict) else {}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}

    def save_project_data(self, project_data):
        """Persist a validated Project Data record beside the KiCad project."""
        if self.project_data_store is None:
            raise ValueError("Save the active board as a KiCad project first")
        if self.project_data_recovery_error:
            raise ProjectDataRecoveryError("Back up the unreadable Project Data record before creating a new one")
        self.project_data_fingerprint = self.project_data_store.save(
            project_data, expected_fingerprint=self.project_data_fingerprint,
        )
        self.project_data = project_data
        self.project_data_record_exists = True

    def reload_project_data(self):
        if self.project_data_store is None:
            return
        self.project_data_fingerprint = self.project_data_store.fingerprint()
        self.project_data = self.project_data_store.load()
        self.project_data_recovery_error = None
        self.project_data_record_exists = self.project_data_store.path.is_file()
        self.page_by_tool["Project Data"].reload(self.project_data, self.project_data_catalog)

    def resolve_project_data_conflict(self, parent):
        if wx.MessageBox(
            "kobee-project.json changed, was deleted, or was replaced outside Kobee. Reload it now? Unsaved edits in this window will be discarded.",
            "Project Data changed", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, parent,
        ) != wx.YES:
            return
        try:
            self.reload_project_data()
        except (OSError, TypeError, ValueError, json.JSONDecodeError, ProjectDataRecoveryError) as error:
            self.project_data_recovery_error = str(error)
            self.page_by_tool["Project Data"].reload(self.project_data, self.project_data_catalog)

    def recover_project_data(self):
        if self.project_data_store is None or not self.project_data_recovery_error:
            return None
        backup = self.project_data_store.backup_corrupt_record()
        self.project_data_store.remove_corrupt_record_after_backup(backup)
        self.project_data_fingerprint = None
        self.project_data_recovery_error = None
        self.save_project_data(ProjectData.empty())
        return backup

    def import_project_data_record(self, record_path):
        if self.project_data_store is None:
            raise ValueError("Save the active board as a KiCad project first")
        if self.project_data_record_exists:
            raise ValueError("This project already has Project Data; reload or recover it instead")
        imported = ProjectDataStore.read_record(record_path)
        self.save_project_data(imported)
        return imported

    def sync_project_data(self, create_checkpoint=False):
        """Merge only Kobee-owned names into KiCad's project text variables."""
        if self.project_data_store is None:
            wx.MessageBox("Save the active board as a KiCad project first.", "Project Data", wx.OK | wx.ICON_INFORMATION, self)
            return
        if self.editor_session is None:
            wx.MessageBox(
                "Project Data sync requires the KiCad IPC plugin so Kobee can safely update the active project.",
                "KiCad IPC required", wx.OK | wx.ICON_INFORMATION, self,
            )
            return
        kicad_variables_applied = False
        try:
            page = self.page_by_tool["Project Data"]
            draft = page.collect()
            if create_checkpoint and not str(draft.revision_draft.get("default_change_summary", "")).strip():
                if wx.MessageBox(
                    "This checkpoint has no change summary. Create it anyway?",
                    "Missing change summary", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self,
                ) != wx.YES:
                    return
            project_data = draft.with_checkpoint(draft.revision_draft) if create_checkpoint else draft
            project = self.editor_session.board.get_project()
            text_variables = project.get_text_variables()
            generated = generated_variables(project_data, self.project_data_catalog)
            merged, managed = merge_kicad_variables(
                text_variables.variables, generated, project_data.managed_variable_names,
            )
            project_data = project_data.with_managed_variable_names(managed).with_sync_state(pending=True)
            # Persist the checkpoint and the intended variable ownership first.
            # If KiCad is unavailable afterwards, a retry remains deterministic.
            self.save_project_data(project_data)
            text_variables.variables = merged
            try:
                project.set_text_variables(text_variables)
                kicad_variables_applied = True
            except Exception as error:
                page.reload(project_data, self.project_data_catalog)
                wx.MessageBox(
                    "Project Data was saved, but KiCad variables were not updated. Retry Sync to KiCad after resolving the issue.\n\n{}".format(error),
                    "KiCad sync pending", wx.OK | wx.ICON_WARNING, self,
                )
                return
            project_data = project_data.mark_synced()
            self.save_project_data(project_data)
            self._project_text_variables = merged
            if "Variables" in self.page_by_tool:
                self.prepare_variables()
            page.reload(project_data, self.project_data_catalog)
            message = "Created revision checkpoint and synced {} KiCad variable(s)." if create_checkpoint else "Synced {} KiCad variable(s)."
            wx.MessageBox(message.format(len(generated)), "Project Data", wx.OK | wx.ICON_INFORMATION, self)
        except ProjectDataConflictError:
            if kicad_variables_applied:
                wx.MessageBox(
                    "KiCad variables were updated, but kobee-project.json changed before Kobee could mark the sync complete. Reload it, then retry Sync to KiCad to reconcile the record.",
                    "Project Data sync needs review", wx.OK | wx.ICON_WARNING, self,
                )
            self.resolve_project_data_conflict(self)
        except (AttributeError, OSError, TypeError, ValueError, ProjectDataRecoveryError) as error:
            wx.MessageBox(str(error), "Could not sync Project Data", wx.OK | wx.ICON_ERROR, self)

    def prepare_variables(self):
        page = self.page_by_tool.get("Variables")
        if page is None:
            return {}
        values = self._file_text_variables()
        if self.editor_session is not None:
            try:
                project_values = self.editor_session.board.get_project().get_text_variables().variables
                values.update({str(key): str(value) for key, value in project_values.items()})
            except Exception:
                pass
        self._project_text_variables = values
        names = tuple(sorted(values, key=str.casefold))
        page._available_variable_names = names
        choice = page.controls["VariableInsertChoice"]

        def menu_label(name):
            token = "${{{}}}".format(name)
            value = str(values.get(name, "")).replace("\r", "").replace("\n", " ↵ ").strip()
            if not value:
                return token if len(token) <= 44 else token[:43].rstrip() + "…"
            # Keep the closed choice legible while still making it clear what
            # will be inserted. The complete value is available as a tooltip.
            token = token if len(token) <= 28 else token[:27].rstrip() + "…"
            value = value if len(value) <= 26 else value[:25].rstrip() + "…"
            return "{}  —  {}".format(token, value)

        choice.SetItems(
            ("Choose a project value…",)
            + tuple(menu_label(name) for name in names)
        )
        choice.SetSelection(0)
        choice.SetToolTip(
            "Choose a project value to insert its ${NAME} placeholder at the text cursor. "
            "The text after the dash is that value's current contents."
        )
        self._update_variable_status()
        self._preview_fingerprint = None
        self.request_preview()
        return values

    def _update_variable_status(self):
        page = self.page_by_tool.get("Variables")
        if page is None or not hasattr(page, "variable_status"):
            return
        names = tuple(sorted(self._project_text_variables, key=str.casefold))
        used = variable_names(page.controls["VariableTemplateText"].GetValue())
        unresolved = tuple(name for name in used if name not in self._project_text_variables)
        detail = (
            " Unknown in the current project: {}.".format(
                ", ".join("${" + name + "}" for name in unresolved)
            )
            if unresolved else ""
        )
        page.variable_status.SetLabel(
                "{} project value(s) available. Choose one above to add its ${{NAME}} placeholder at the cursor. "
            "Preview uses the current value for {}. Use Refresh values, then Update artwork, after a project value changes.{}".format(
                len(names),
                ", ".join("${" + name + "}" for name in used) if used else "the template text",
                detail,
            )
        )

    def resolve_variable_template(self, template_text):
        raw = validate_variable_template(template_text)
        # Kobee-managed values are read directly from the project's current
        # text-variable map before asking KiCad to resolve anything else.
        # KiCad can retain a previously expanded value in an open board, even
        # though get_text_variables() already exposes the new value. Resolving
        # the known values first prevents that stale expansion from being baked
        # back into an existing static Kobee label on Update artwork.
        current = expand_variable_template(raw, self._project_text_variables)
        if self.editor_session is not None:
            try:
                # Let KiCad resolve any remaining built-ins or foreign
                # project variables, then fill anything it intentionally left
                # native from the current map.
                expanded = str(self.editor_session.board.expand_text_variables(current))
                return expand_variable_template(expanded, self._project_text_variables)
            except Exception:
                pass
        return current

    def _sync_board_selection_timer(self):
        selected_scope = False
        if self.editor_session is not None and self._tool == "Designators":
            page = self.page_by_tool["Designators"]
            selected_scope = self._designator_scope_id(page.controls["DesignatorScopeChoice"].GetStringSelection()) == "selected"
        if selected_scope:
            if not self._selection_timer.IsRunning():
                self._selection_timer.Start(450)
        else:
            self._selection_timer.Stop()

    def _on_board_selection_timer(self, event):
        try:
            if self._tool == "Designators":
                self.prepare_designators()
            else:
                self._selection_timer.Stop()
        except Exception:
            # Selection polling is convenience only. The explicit Apply/Place
            # path will surface any IPC error with full context.
            pass

    def apply_designators_from_page(self, event=None):
        page = self.page_by_tool["Designators"]
        scope = self._designator_scope_id(page.controls["DesignatorScopeChoice"].GetStringSelection())
        self.run_add_designators(scope)

    def run_add_designators(self, scope=None):
        if self.editor_session is None: return
        footprints = self.prepare_designators(scope, show_message=True)
        skipped = self._designator_skipped
        if not footprints:
            return
        self.request_preview(immediate=True)
        if self.error or self.artwork is None:
            wx.MessageBox(self.error or "The designator preview could not be generated.", "Could not add designators", wx.OK | wx.ICON_ERROR, self)
            return
        settings = mode_defaults("Label"); settings.update(DEFAULT_LABEL_DIMENSIONS)
        settings.update(self.page_by_tool["Designators"].settings())
        if wx.MessageBox("Create or update styled designators for {} footprint(s)?\n\nThe native reference fields will be hidden after successful placement.".format(len(footprints)), "Confirm designator creation", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES: return
        try:
            existing = {}
            for generated in self.editor_session.board.get_footprints():
                for item in getattr(generated.definition, "items", ()):
                    if getattr(item, "name", "") != METADATA_FIELD_NAME: continue
                    try: payload = decode_metadata(item.text.value)
                    except Exception: continue
                    feature = payload.get("feature", {})
                    if isinstance(feature, dict) and feature.get("kind") == "designator_label": existing[str(feature.get("source_footprint_id", ""))] = generated
            api = IpcArtworkPlacement._api(); records = []
            failures = []
            for source in footprints:
                try:
                    records.append(self._build_designator_record(source, settings, existing, api))
                except Exception as error:
                    failures.append("{}: {}".format(getattr(source.reference_field.text,"value","Unknown"), error))
            if failures:
                wx.MessageBox("No board changes were made because these designators could not be generated:\n\n{}".format("\n".join(failures)), "Could not add designators", wx.OK | wx.ICON_ERROR, self)
                return
            created, updated = IpcArtworkPlacement(self.editor_session).place_designators(records)
            wx.MessageBox("Created {} and updated {} designator label(s); skipped {} footprint(s).".format(created, updated, skipped), "Designators complete", wx.OK | wx.ICON_INFORMATION, self)
        except Exception as error:
            traceback.print_exc(); wx.MessageBox(str(error), "Could not add designators", wx.OK | wx.ICON_ERROR, self)

    def _select_family(self, family):
        if self._loading:
            return
        tools = [label for item_family, label, mode in TOOL_DEFINITIONS if item_family == family]
        self._family = family
        if self._tool not in tools:
            # Route through the normal tool selector so a default profile is
            # applied consistently when a family is first opened.
            self._select_tool(self._last_tool_by_family.get(family, tools[0]))
            return
        self.Freeze()
        try:
            self._update_tab_state()
            self._show_active_page()
        finally:
            self.Thaw()
        self._refresh_profile_bar()
        # QR/barcode construction can be comparatively expensive.  Let wx
        # finish changing pages before the debounced preview work begins.
        self.request_preview()

    def _select_tool(self, tool):
        if tool == self._tool and not self._loading:
            return
        self._tool = tool
        self._last_valid = None
        self._preview_fingerprint = None
        self._family = self.page_by_tool[tool].family
        self._last_tool_by_family[self._family] = tool
        was_loading = self._loading
        self._loading = True
        try:
            if self._family != "project_data" and not self._editing_existing and tool not in self._default_applied_tools:
                try:
                    profile = self.profile_store.load(profile_module_for_mode(self.page_by_tool[tool].mode))
                    self.page_by_tool[tool].apply(profile.settings)
                    self._recalled_profile_ids[profile.module] = profile.profile_id
                    layer = profile.settings.get("LayerComboBox", FRONT_SILKSCREEN)
                    layers = profile.settings.get("OutputLayers", (layer,))
                    self._set_output_layers(
                        layers if isinstance(layers, (tuple, list)) else (layer,),
                        preview_layer=layer,
                    )
                except (LookupError, OSError, TypeError, ValueError, json.JSONDecodeError):
                    pass
            self._default_applied_tools.add(tool)
            self.Freeze()
            try:
                self._update_tab_state()
                self._show_active_page()
            finally:
                self.Thaw()
        finally:
            self._loading = was_loading
        self._refresh_profile_bar()
        board_tools = self._family == "board_tools"
        project_data = self._family == "project_data"
        self.tool_bar.Show(not project_data)
        self.profile_bar.Show(not board_tools and not project_data)
        self.placement_bar.Show(not board_tools and not project_data)
        self.preview_panel.Show(self._tool_needs_preview(tool))
        self.place_button.Show(not board_tools and not project_data)
        self.designator_footer_button.Show(tool == "Designators")
        self.footer_shortcut.Show(self._tool_needs_preview(tool))
        self.footer_shortcut.SetLabel(
            "Ctrl/Shift + Enter applies designators"
            if tool == "Designators" else
            "Ctrl/Shift + Enter places artwork"
        )
        self.Layout()
        self._selection_fingerprint = None
        if tool == "Designators":
            self.prepare_designators()
        elif tool == "Variables":
            self.prepare_variables()
        elif project_data:
            self.preview.set_artwork((), (), (), FRONT_SILKSCREEN); self.preview_error.SetLabel("")
            project_page = self.page_by_tool["Project Data"]
            project_page.reload(self.project_data, self.project_data_catalog)
            wx.CallAfter(project_page.maybe_offer_adoption)
        elif board_tools:
            self.preview.set_artwork((), (), (), FRONT_SILKSCREEN); self.preview_error.SetLabel("")
        else:
            self.request_preview()
        self._sync_board_selection_timer()

    def _rebuild_tool_bar(self):
        for family, label, mode in TOOL_DEFINITIONS:
            button = self.tool_buttons[label]
            button.Show(family == self._family)
            button.set_active(label == self._tool)
        self.tool_bar.Layout()

    def _tool_needs_preview(self, tool=None):
        """Return whether the selected workflow benefits from artwork preview.

        Cleanup is a board operation with its own before/after examples; its
        empty artwork canvas only wastes space. Designators still uses the
        preview to show the generated reference label.
        """
        page = self.page_by_tool[tool or self._tool]
        return not (
            page.family == "project_data"
            or (page.family == "board_tools" and page.label == "Cleanup")
        )

    def _update_tab_state(self):
        for family, button in self.family_buttons.items():
            selected = family == self._family
            button.set_active(selected)
        self._rebuild_tool_bar()

    def _show_active_page(self):
        page = self.page_by_tool[self._tool]
        self.pages.ChangeSelection(self.page_index_by_tool[self._tool])
        # Apply this here as well as in _select_tool so a routed initial page
        # cannot leave an irrelevant preview column visible.
        self.preview_panel.Show(self._tool_needs_preview())
        page._schedule_layout(scroll_to_top=True)

    def _route_settings(self, settings):
        # Profiles created before the expanded cutout control used the two
        # shorter labels. Preserve their intent rather than silently falling
        # back to the new default pill.
        legacy_cutout = settings.get("HeaderCutoutEdgeChoice")
        if legacy_cutout == "Rounded cutout":
            settings["HeaderCutoutEdgeChoice"] = "Rounded rectangle cutout"
        elif legacy_cutout == "Square edge cutout":
            settings["HeaderCutoutEdgeChoice"] = "Square rectangle cutout"
        mode = settings.get("StudioModeChoice", "Label")
        if settings.get("StudioTool") == "Variables":
            tool = "Variables"
        elif mode == "QR / Barcode":
            tool = "Barcode" if settings.get("MachineCodeTypeChoice") == "Code 128 barcode" else "QR Code"
        else:
            tool = {
                "Label": "Standard",
                "2.54 mm Pin Header": "Header Overlay",
                "Imported Graphic": "Imported Graphic",
                "Component Callout": "Component Callout",
                "Component Array": "Component Array",
            }.get(mode, "Standard")
        if tool == "Header Overlay": tool = "Connector Overlay"
        self._tool = tool
        self._family = self.page_by_tool[tool].family
        requested_font = str(settings.get("FontComboBox", ""))
        font_control = self.page_by_tool[tool].controls.get("FontComboBox")
        self._missing_font_metadata = None
        if requested_font and font_control is not None and requested_font not in self.page_by_tool[tool]._font_names():
            font_control.SetItems((requested_font,) + self.page_by_tool[tool]._font_labels())
            metadata = settings.get("FontFaceMetadata")
            self._missing_font_metadata = dict(metadata) if isinstance(metadata, dict) else {"renderer_name":requested_font}
        self.page_by_tool[tool].apply(settings)
        self._update_font_availability()
        configured_layers = settings.get("OutputLayers", ())
        if isinstance(configured_layers, str):
            configured_layers = (configured_layers,)
        if not isinstance(configured_layers, (tuple, list)):
            configured_layers = ()
        configured_layers = tuple(layer for layer in LAYER_ORDER if layer in configured_layers)
        layer = settings.get("LayerComboBox", FRONT_SILKSCREEN)
        if not configured_layers:
            configured_layers = (layer,) if layer in LAYER_LABELS else (FRONT_SILKSCREEN,)
        self._set_output_layers(configured_layers, preview_layer=layer)
        self._update_tab_state()
        self._show_active_page()

    @property
    def active_page(self):
        return self.page_by_tool[self._tool]

    @property
    def output_layer(self):
        label = self.layer_choice.GetStringSelection()
        for layer, layer_label in PREVIEW_LAYER_LABELS.items():
            if label == layer_label:
                return layer
        return FRONT_SILKSCREEN

    @property
    def output_layers(self):
        return self._output_layers

    def _set_output_layers(self, layers, preview_layer=None):
        layers = tuple(layer for layer in LAYER_ORDER if layer in layers)
        self._output_layers = layers or (FRONT_SILKSCREEN,)
        if hasattr(self, "layer_choice"):
            self.layer_choice.SetItems(tuple(PREVIEW_LAYER_LABELS[layer] for layer in self._output_layers))
            preview_layer = preview_layer if preview_layer in self._output_layers else self._output_layers[0]
            self.layer_choice.SetStringSelection(PREVIEW_LAYER_LABELS[preview_layer])
        if hasattr(self, "layer_toggles"):
            for layer, toggle in self.layer_toggles.items():
                toggle.SetValue(layer in self._output_layers)

    def _on_target_layers_changed(self, event):
        layers = tuple(layer for layer in LAYER_ORDER if self.layer_toggles[layer].GetValue())
        if not layers:
            self.layer_toggles[FRONT_SILKSCREEN].SetValue(True)
            layers = (FRONT_SILKSCREEN,)
            wx.MessageBox("At least one target layer is required.", "Target layers", wx.OK | wx.ICON_INFORMATION, self)
        self._set_output_layers(layers, preview_layer=self.output_layer)
        if not self._loading:
            self.request_preview()
        event.Skip()

    def CurrentSettings(self):
        settings = mode_defaults(self.active_page.mode)
        settings.update(self.active_page.settings())
        if hasattr(self.active_page, "_effective_shape_choice"):
            settings["ShapeChoice"] = self.active_page._effective_shape_choice()
        if hasattr(self.active_page, "_effective_end_caps"):
            settings["StartCapChoice"], settings["EndCapChoice"] = self.active_page._effective_end_caps()
        settings["StudioModeChoice"] = self.active_page.mode
        if self._tool == "Variables":
            settings["StudioTool"] = "Variables"
        settings["MachineCodeTypeChoice"] = "Code 128 barcode" if self._tool == "Barcode" else settings.get("MachineCodeTypeChoice", "QR Code")
        settings["LayerComboBox"] = self.output_layer
        settings["OutputLayers"] = list(self.output_layers)
        settings["StudioDimensionsVersion"] = STUDIO_DIMENSIONS_VERSION
        settings["StudioDefaultsVersion"] = STUDIO_DEFAULTS_VERSION
        font_name = settings.get("FontComboBox")
        face = next((item for item in self.font_store.list() if item.renderer_name == font_name), None)
        if face is not None:
            settings["FontFaceMetadata"] = {"renderer_name":face.renderer_name,"family":face.family,"weight":face.weight,"style":face.style,"source_url":face.source_url,"licence_url":face.licence_url,"source":"google"}
        elif font_name:
            settings["FontFaceMetadata"] = {
                "renderer_name": str(font_name),
                "family": str(font_name),
                "source": (
                    "system" if font_name in self.system_font_names else "bundled"
                ),
            }
        return settings

    def _offer_missing_font(self):
        if not self.accepts_background_results():
            return
        metadata = self._missing_font_metadata
        if not metadata: return
        if metadata.get("source") != "google" or not metadata.get("family"):
            return
        if wx.MessageBox("This artwork uses the missing Google Font face “{}”. Redownload it now?".format(metadata.get("family", metadata.get("renderer_name", "Unknown"))), "Missing font", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES: return
        tool = self._tool
        expected_renderer = self.active_page._selected_font_renderer(self.active_page.controls["FontComboBox"])
        def worker():
            try: face, error = self.font_store.download_google_face(metadata["family"], int(metadata.get("weight",400)), metadata.get("style","normal")), None
            except Exception as caught: face, error = None, caught
            wx.CallAfter(self._missing_font_finished, face, error, tool, expected_renderer)
        threading.Thread(target=worker,daemon=True).start()

    def _missing_font_finished(self, face, error, tool=None, expected_renderer=None):
        if not self.accepts_background_results():
            return
        if error is not None:
            wx.MessageBox(str(error), "Could not redownload font", wx.OK | wx.ICON_ERROR, self); return
        self.buzzard.register_font(face.renderer_name, face.path)
        target_tool = tool or self._tool
        page = self.page_by_tool.get(target_tool)
        choice = page.controls.get("FontComboBox") if page is not None else None
        if choice is not None and (expected_renderer is None or page._selected_font_renderer(choice) == expected_renderer):
            choice.SetItems(page._font_labels()); choice.SetStringSelection(page._font_label(face.renderer_name))
            page.set_font_availability_error()
        if expected_renderer is None or (self._missing_font_metadata or {}).get("renderer_name") == expected_renderer:
            self._missing_font_metadata=None
        if target_tool == self._tool:
            self._update_font_availability()
        self._preview_fingerprint=None; self.request_preview(immediate=True)

    def _update_font_availability(self):
        page = self.page_by_tool.get(self._tool)
        if page is None or not hasattr(page, "set_font_availability_error"):
            return
        metadata = self._missing_font_metadata
        if not metadata:
            page.set_font_availability_error()
            return
        name = str(metadata.get("family") or metadata.get("renderer_name") or "Unknown font")
        page.set_font_availability_error(
            "Font “{}” is no longer available on this computer. Install it or choose another typeface, then save the profile again.".format(name)
        )

    def font_selection_changed(self, renderer_name):
        """Clear a moved-profile warning once the user picks an available face."""
        if renderer_name in self.active_page._font_names():
            self._missing_font_metadata = None
        self._update_font_availability()

    def set_font_favourite(self, renderer_name, favourite):
        """Persist one favourite and refresh the compact typeface pickers."""
        renderer_name = str(renderer_name).strip()
        if not renderer_name:
            return
        favourites = set(self.preferences.favourite_font_names)
        if favourite:
            favourites.add(renderer_name)
        else:
            favourites.discard(renderer_name)
        preferences = AppPreferences(
            appearance=self.preferences.appearance,
            measurement_unit=self.preferences.measurement_unit,
            hidden_symbol_ids=self.preferences.hidden_symbol_ids,
            hidden_label_ids=self.preferences.hidden_label_ids,
            favourite_font_names=tuple(favourites),
            enabled_system_font_names=self.preferences.enabled_system_font_names,
        )
        try:
            self.preferences_store.save(preferences)
        except (OSError, TypeError, ValueError) as error:
            wx.MessageBox(str(error), "Could not save favourite fonts", wx.OK | wx.ICON_ERROR, self)
            return
        self.preferences = preferences
        for page in self.page_by_tool.values():
            if hasattr(page, "_refresh_font_choices"):
                page._refresh_font_choices()

    def on_control_changed(self, event):
        if self._tool == "Variables" and hasattr(self.active_page, "variable_status"):
            self._update_variable_status()
        if not self._loading:
            # Variable labels have a compact, lightweight renderer. Keeping
            # every edit immediate avoids stale section previews when changing
            # gaps, end treatments, or individual padding controls.
            self.request_preview(immediate=self._tool == "Variables")
        event.Skip()

    def request_preview(self, immediate=False):
        if not self.accepts_background_results() or self._loading:
            return
        self._timer.Stop()
        if immediate:
            self._pending_preview = False
            self._regenerate_preview()
        else:
            self._pending_preview = True
            self.place_button.Disable()
            self.place_button.Refresh(False)
            self._timer.StartOnce(300)

    def _on_preview_timer(self, event):
        if self._pending_preview:
            self._pending_preview = False
            self._regenerate_preview()

    def _document_style(self, settings):
        shape_name = settings.get("ShapeChoice", "Rounded rectangle")
        filled = settings.get("ShapeVariantChoice", "Inverted fill") == "Inverted fill" and shape_name != "No container"
        if self.active_page.mode == "2.54 mm Pin Header":
            padding = Padding.symmetric(float(settings.get("HeaderLabelPaddingCtrl", 0.3)), float(settings.get("HeaderLabelPaddingCtrl", 0.3)))
        else:
            padding = Padding(
                top=float(settings.get("PaddingTopCtrl", 0.5)),
                right=float(settings.get("PaddingRightCtrl", 1.2)),
                bottom=float(settings.get("PaddingBottomCtrl", 0.5)),
                left=float(settings.get("PaddingLeftCtrl", 1.2)),
            )
        secondary = None
        if settings.get("ContentLayoutChoice") == "Title + subtitle":
            secondary = TypographyStyle(
                font_name=_subtitle_font_name(settings.get("SubtitleFontChoice"), settings.get("FontComboBox", "FreddySpark-Regular")),
                height_mm=max(0.01, float(settings.get("SubtitleHeightCtrl", 0.8))),
                line_spacing=max(0.1, float(settings.get("SubtitleLineSpacingCtrl", 1.2))),
                alignment=str(settings.get("AlignmentChoice", "Center")).lower(),
            )
        return DocumentStyle(
            typography=TypographyStyle(
                font_name=settings.get("FontComboBox", "FreddySpark-Regular"),
                height_mm=max(0.01, float(settings.get("HeightCtrl", 1.2))),
                width_mm=max(0.0, float(settings.get("WidthCtrl", 0.0))),
                line_spacing=max(0.1, float(settings.get("LineSpacingCtrl", 1.5))),
                alignment=str(settings.get("AlignmentChoice", "Center")).lower(),
            ),
            secondary_typography=secondary,
            shape=ShapeStyle(
                padding=padding,
                border_thickness_mm=0.0 if filled else max(0.01, float(settings.get("BorderThicknessCtrl", 0.2))),
                corner_radius_mm=max(0.0, float(settings.get("CornerRadiusCtrl", 0.2))),
                feature_size_mm=max(0.0, float(settings.get("FeatureSizeCtrl", 0.75))),
                filled=filled,
                inverted=filled,
                direction=str(settings.get("ShapeDirectionChoice", "Right")).lower(),
                start_cap=cap_style_id(settings.get("StartCapChoice", "Square")),
                end_cap=cap_style_id(settings.get("EndCapChoice", "Rounded")),
            ),
        )

    def _regenerate_preview(self):
        # Read settings inside the error boundary too. Missing imported files,
        # invalid numeric input and project-variable errors occur before the
        # renderer is reached, often from a native wx timer callback.
        try:
            self._render_preview()
        except Exception as error:
            traceback.print_exc()
            self._preview_fingerprint = None
            self._show_preview_error(error)

    def _render_preview(self):
        if self._family == "project_data" or (self._family == "board_tools" and self._tool != "Designators"):
            return
        settings = self.CurrentSettings()
        fingerprint = json.dumps(settings, sort_keys=True, separators=(",", ":"))
        if fingerprint == self._preview_fingerprint:
            self.place_button.Enable(self.error is None and self.artwork is not None)
            self.place_button.Refresh(False)
            return
        self._preview_fingerprint = fingerprint
        mode = self.active_page.mode
        text = str(settings.get("MultiLineText", ""))
        style = self._document_style(settings)
        icon_id = str(
            settings.get("SymbolAssetId", "")
            or ICON_LABELS.get(settings.get("IconChoice", "No icon"), "")
        )
        icon_variant = str(settings.get("SymbolVariant", "default"))

        def icon_renderer(asset_id, height_mm):
            return render_symbol(
                asset_id,
                height_mm,
                icon_variant,
                catalog=self.symbol_catalog,
            )

        self.error = None
        try:
            if self._tool == "Imported Graphic":
                geometry = str(settings.get("GraphicGeometrySvg", ""))
                if not geometry:
                    # A missing graphic is an empty state, not a failed
                    # version of the previous label.  Never retain stale
                    # artwork here: it makes the Graphic tab appear to have
                    # selected a label that cannot actually be placed.
                    self.artwork = None
                    self.polys = []
                    self.stroke_polys = []
                    self.guide_polys = []
                    self.preview.set_artwork((), (), (), self.output_layer)
                    self.preview.set_transform_handler()
                    self.preview_error.SetLabel("Choose or upload a graphic asset")
                    self.preview_error.Wrap(max(240, self.preview.GetClientSize().width))
                    self.place_button.Disable()
                    side = "Bottom side · front-view mirror" if is_bottom(self.output_layer) else "Front side"
                    self.preview_status.SetLabel("{} · {}".format(side, LAYER_LABELS[self.output_layer]))
                    return
                graphic = GraphicObject(
                    object_id="graphic.main", asset_id=str(settings.get("GraphicAssetId", "embedded")), geometry_svg=geometry,
                    position=Point(float(settings.get("GraphicOffsetXCtrl", 0)), float(settings.get("GraphicOffsetYCtrl", 0))),
                    size=Size(float(settings.get("GraphicWidthCtrl", 20)), float(settings.get("GraphicHeightCtrl", 20))),
                    rotation_deg=float(settings.get("GraphicRotationCtrl", 0)),
                    mirror_horizontal=bool(settings.get("GraphicMirrorHorizontal", False)),
                    mirror_vertical=bool(settings.get("GraphicMirrorVertical", False)),
                )
                self.artwork = render_graphic_artwork(graphic, self.output_layer)
            elif self._tool in ("QR Code", "Barcode"):
                kind = "code128" if self._tool == "Barcode" else "qr"
                self.artwork = render_machine_code_artwork(
                    payload=text,
                    kind=kind,
                    module_size_mm=float(settings.get("MachineCodeModuleSizeCtrl", QR_MIN_MODULE_MM)),
                    bar_height_mm=float(settings.get("MachineCodeBarHeightCtrl", CODE128_DEFAULT_HEIGHT_MM)),
                    output_layer=self.output_layer,
                    vectorizer=self._text_vectorizer,
                    presentation="plain" if kind == "code128" else QR_PRESENTATION_LABELS.get(settings.get("MachineCodePresentationChoice"), "plain"),
                    caption_text=settings.get("MachineCodeCaptionCtrl", ""),
                    caption_height_mm=float(settings.get("MachineCodeCaptionHeightCtrl", 1.2)),
                    frame_padding_mm=float(settings.get("MachineCodeFramePaddingCtrl", 0.2)),
                    show_content_text=bool(settings.get("MachineCodeShowContentCheckbox", False)),
                    content_text=settings.get("MachineCodeContentCtrl", ""),
                    content_height_mm=float(settings.get("MachineCodeContentHeightCtrl", 0.9)),
                    content_gap_mm=float(settings.get("MachineCodeContentGapCtrl", 0.5)),
                )
            elif mode == "2.54 mm Pin Header":
                labels = tuple(text.splitlines())
                pin_count = int(settings.get("HeaderPinCountCtrl", 4))
                if len(labels) != pin_count:
                    raise ValueError("Enter exactly {} pin labels, one per line".format(pin_count))
                orientation = str(settings.get("HeaderOrientationChoice", "Vertical")).lower()
                side = settings.get("HeaderPinSideChoice", "Left")
                if orientation == "horizontal" and side not in ("Top", "Bottom"):
                    side = "Top"
                if orientation == "vertical" and side not in ("Left", "Right"):
                    side = "Left"
                spec = PinHeaderSpec(
                    pin_count=pin_count,
                    pin_labels=labels,
                    pitch_mm=(float(settings.get("HeaderCustomPitchCtrl", 2.54)) if settings.get("HeaderPitchChoice") == "Custom" else float(str(settings.get("HeaderPitchChoice", "2.54 mm")).split()[0])),
                    orientation=orientation,
                    pin1_end=str(settings.get("HeaderPin1Choice", "Start")).lower(),
                    label_side=PIN_SIDE_TO_LABEL_SIDE[side],
                    pad_clearance_mm=float(settings.get("HeaderPadClearanceCtrl", 2.0)),
                    opening_mode=OPENING_LABELS.get(settings.get("HeaderOpeningChoice"), "continuous"),
                    opening_shape=HEADER_CUTOUT_SHAPES.get(settings.get("HeaderCutoutEdgeChoice"), "pill"),
                    individual_opening_shape=HEADER_CUTOUT_SHAPES.get(
                        settings.get("HeaderIndividualCutoutEdgeChoice"), "pill"
                    ),
                    opening_corner_radius_mm=float(settings.get("HeaderCutoutRadiusCtrl", 0.5)),
                    opening_end_padding_mm=float(settings.get("HeaderOpeningEndPaddingCtrl", 0)),
                    leading_padding_mm=float(settings.get("HeaderLeadingPaddingCtrl", 0.3)),
                    trailing_padding_mm=float(settings.get("HeaderTrailingPaddingCtrl", 0.3)),
                    label_padding_mm=float(settings.get("HeaderLabelPaddingCtrl", 0.3)),
                    pin_outer_padding_mm=float(settings.get("HeaderPinOuterPaddingCtrl", 0.3)),
                    pin_to_label_gap_mm=float(settings.get("HeaderPinToLabelGapCtrl", 0.3)),
                    label_outer_padding_mm=float(settings.get("HeaderLabelOuterPaddingCtrl", 0.3)),
                    rail_cross_size_mm=float(settings.get("HeaderCrossSizeCtrl", 0)),
                    pin1_marker=bool(settings.get("HeaderPin1MarkerCheckbox", True)),
                    shape=HEADER_SHAPE_LABELS.get(settings.get("ShapeChoice"), "rounded_rectangle"),
                    output_layer=self.output_layer,
                    style=style,
                )
                self.artwork = render_header_artwork(self._text_vectorizer, spec)
            elif mode in ("Component Callout", "Component Array"):
                array = mode == "Component Array"
                content_mode = settings.get("ContentModeChoice", "Label")
                if content_mode == "Label":
                    icon_id = ""
                if content_mode == "Symbol only" and not icon_id:
                    raise ValueError("Choose a symbol to make a symbol-only marking")
                preset = self.component_preset(settings.get("ComponentPresetChoice"))
                width = float(settings.get("ComponentWidthCtrl", preset.width_mm if preset else 2.2))
                height = float(settings.get("ComponentHeightCtrl", preset.height_mm if preset else 1.1))
                spec = ComponentCalloutSpec(
                    title=text,
                    subtitle=(
                        settings.get("SubtitleCtrl", "")
                        if not array
                        and settings.get("ContentLayoutChoice") == "Title + subtitle"
                        and content_mode != "Symbol only"
                        else ""
                    ),
                    preset_id=(getattr(preset, "preset_id", None) or COMPONENT_PRESET_LABELS.get(settings.get("ComponentPresetChoice"), "custom")),
                    component_width_mm=width,
                    component_height_mm=height,
                    component_clearance_mm=float(settings.get("ComponentClearanceCtrl", 0.3)),
                    cutout_shape=COMPONENT_CUTOUT_LABELS.get(settings.get("ComponentCutoutChoice"), "rounded_rectangle"),
                    cutout_radius_mm=float(settings.get("ComponentCutoutRadiusCtrl", 0.2)),
                    component_position=COMPONENT_POSITION_LABELS.get(settings.get("ComponentPositionChoice"), "left"),
                    component_to_text_gap_mm=float(settings.get("ComponentTextGapCtrl", 2.6)),
                    array_count=int(settings.get("ComponentArrayCountCtrl", 3)) if array else 1,
                    array_orientation=COMPONENT_ARRAY_ORIENTATION_LABELS.get(settings.get("ComponentArrayOrientationChoice"), "vertical"),
                    array_pitch_mm=float(settings.get("ComponentArrayPitchCtrl", 5.0)),
                    subtitle_gap_mm=float(settings.get("SubtitleGapCtrl", 0.25)),
                    minimum_width_mm=float(settings.get("ComponentMinWidthCtrl", 0)),
                    minimum_height_mm=float(settings.get("ComponentMinHeightCtrl", 0)),
                    shape=COMPONENT_SHAPE_LABELS.get(settings.get("ShapeChoice"), "rounded_rectangle"),
                    output_layer=self.output_layer,
                    style=style,
                )
                self.artwork = render_component_callout_artwork(
                    self._text_vectorizer,
                    spec,
                    icon_id="" if array else icon_id,
                    icon_position=(
                        "only"
                        if content_mode == "Symbol only"
                        else ICON_POSITION_LABELS.get(settings.get("IconPositionChoice", "Left of text"), "left")
                    ),
                    icon_height_mm=float(settings.get("IconHeightCtrl", 0)),
                    icon_gap_mm=float(settings.get("IconGapCtrl", 0.3)),
                    icon_variant=icon_variant,
                    icon_renderer=icon_renderer,
                )
            elif (
                self._tool == "Variables"
                and settings.get("VariableLayoutChoice") == "Multipart label"
            ):
                raw_sections = multipart_sections(settings.get("VariableTemplateText", ""))
                sections = tuple(
                    self.resolve_variable_template(section) for section in raw_sections
                )
                self.artwork = render_multipart_label_artwork(
                    self._text_vectorizer,
                    sections,
                    style,
                    self.output_layer,
                    start_cap=cap_style_id(settings.get("MultiPartStartCapChoice", "Rounded")),
                    end_cap=cap_style_id(settings.get("MultiPartEndCapChoice", "Square")),
                    separator=str(settings.get("MultiPartSeparatorChoice", "\\")),
                    gap_mm=float(settings.get("MultiPartGapCtrl", 0.35)),
                    separator_depth_mm=float(settings.get("MultiPartSeparatorDepthCtrl", 0.75)),
                    start_padding_left_mm=float(settings.get("MultiPartStartLeftPaddingCtrl", style.shape.padding.left)),
                    start_padding_right_mm=float(settings.get("MultiPartStartRightPaddingCtrl", style.shape.padding.right)),
                    middle_padding_left_mm=float(settings.get("MultiPartMiddleLeftPaddingCtrl", style.shape.padding.left)),
                    middle_padding_right_mm=float(settings.get("MultiPartMiddleRightPaddingCtrl", style.shape.padding.right)),
                    end_padding_left_mm=float(settings.get("MultiPartEndLeftPaddingCtrl", style.shape.padding.left)),
                    end_padding_right_mm=float(settings.get("MultiPartEndRightPaddingCtrl", style.shape.padding.right)),
                    inline_format=bool(settings.get("inlineFormatTextbox", False)),
                    lineover_style=settings.get("lineoverStyleChoice", "Rounded"),
                    lineover_thickness=int(settings.get("lineoverThicknessCtrl", 1)),
                    underline=bool(settings.get("UnderlineCheckbox", False)),
                    underline_thickness_mm=float(settings.get("UnderlineThicknessCtrl", 0.15)),
                    underline_gap_mm=float(settings.get("UnderlineGapCtrl", 0.12)),
                    overline=bool(settings.get("OverlineCheckbox", False)),
                    overline_thickness_mm=float(settings.get("OverlineThicknessCtrl", 0.15)),
                    overline_gap_mm=float(settings.get("OverlineGapCtrl", 0.12)),
                )
            else:
                shape = LABEL_SHAPE_LABELS.get(settings.get("ShapeChoice"))
                content_mode = settings.get("ContentModeChoice", "Label")
                if content_mode == "Label":
                    icon_id = ""
                if content_mode == "Symbol only" and not icon_id:
                    raise ValueError("Choose a symbol to make a symbol-only marking")
                label_text = "" if content_mode == "Symbol only" else text
                subtitle = (
                    settings.get("SubtitleCtrl", "")
                    if content_mode != "Symbol only"
                    and settings.get("ContentLayoutChoice") == "Title + subtitle"
                    else ""
                )
                self.artwork = render_label_artwork(
                    self._text_vectorizer,
                    label_text,
                    style,
                    self.output_layer,
                    shape=shape,
                    minimum_width_mm=float(settings.get("WidthCtrl", 0)),
                    inline_format=bool(settings.get("inlineFormatTextbox", False)),
                    lineover_style=settings.get("lineoverStyleChoice", "Rounded"),
                    lineover_thickness=int(settings.get("lineoverThicknessCtrl", 1)),
                    icon_id=icon_id,
                    icon_position=(
                        "only"
                        if content_mode == "Symbol only"
                        else ICON_POSITION_LABELS.get(settings.get("IconPositionChoice", "Left of text"), "left")
                    ),
                    icon_height_mm=float(settings.get("IconHeightCtrl", 0)),
                    icon_gap_mm=float(settings.get("IconGapCtrl", 0.3)),
                    subtitle_text=subtitle,
                    subtitle_typography=style.secondary_typography,
                    subtitle_gap_mm=float(settings.get("SubtitleGapCtrl", 0.25)),
                    underline=bool(settings.get("UnderlineCheckbox", False)),
                    underline_thickness_mm=float(settings.get("UnderlineThicknessCtrl", 0.15)),
                    underline_gap_mm=float(settings.get("UnderlineGapCtrl", 0.12)),
                    overline=bool(settings.get("OverlineCheckbox", False)),
                    overline_thickness_mm=float(settings.get("OverlineThicknessCtrl", 0.15)),
                    overline_gap_mm=float(settings.get("OverlineGapCtrl", 0.12)),
                    icon_variant=icon_variant,
                    icon_renderer=icon_renderer,
                )
            if "PlacementAnchorChoice" in settings:
                self.artwork = with_placement_anchor(self.artwork, settings["PlacementAnchorChoice"])
            self.polys = list(self.artwork.filled_polygons)
            self.stroke_polys = list(self.artwork.strokes)
            self.guide_polys = list(self.artwork.guides)
            self._last_valid = (self.artwork, tuple(self.polys), tuple(self.stroke_polys), tuple(self.guide_polys))
            self.preview.set_artwork(self.polys, self.stroke_polys, self.guide_polys, self.output_layer)
            self.preview._anchor = self.artwork.document.origin if "PlacementAnchorChoice" in settings else None
            graphic = next((item for item in self.artwork.document.objects if isinstance(item, GraphicObject)), None)
            self.preview.set_transform_handler(graphic, self._on_graphic_transform) if graphic is not None else self.preview.set_transform_handler()
            self.preview_error.SetLabel("")
            self.place_button.Enable()
        except ValueError as error:
            self._show_preview_error(error)
        except Exception as error:
            traceback.print_exc()
            self._show_preview_error(error)
        side = "Bottom side · front-view mirror" if is_bottom(self.output_layer) else "Front side"
        self.preview_status.SetLabel("{} · {}".format(side, LAYER_LABELS[self.output_layer]))

    def _show_preview_error(self, error):
        self.error = str(error) or "Preview unavailable"
        self.place_button.Disable()
        self.place_button.Refresh(False)
        if self._last_valid:
            artwork, filled, strokes, guides = self._last_valid
            self.artwork = artwork
            self.polys = list(filled)
            self.stroke_polys = list(strokes)
            self.guide_polys = list(guides)
        self.preview.set_artwork(
            self.polys,
            self.stroke_polys,
            self.guide_polys,
            self.output_layer,
        )
        self.preview_error.SetLabel(self.error)
        self.preview_error.Wrap(max(240, self.preview.GetClientSize().width))

    def OnOkClick(self, event):
        if self._family == "project_data":
            self.sync_project_data(False)
            return
        if self._tool == "Variables" and self.editor_session is None:
            wx.MessageBox(
                "Variable labels must be placed from KiCad 10 using the IPC plugin. "
                "Kobee uses the active project's current values to render the label.",
                "KiCad IPC required",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        self.request_preview(immediate=True)
        if self.error or self.artwork is None:
            wx.MessageBox(self.error or "Enter valid artwork before placing it.", "Kobee Studio", wx.OK | wx.ICON_ERROR, self)
            return
        self.place_button.Disable()
        try:
            self.func(self, self.buzzard)
        except Exception as error:
            traceback.print_exc()
            self.place_button.Enable()
            wx.MessageBox(str(error), "Kobee Studio could not place artwork", wx.OK | wx.ICON_ERROR, self)


# Keep the entry-point import concise while the retained editor remains
# available for rollback and compatibility comparisons.
MainDialog = StudioEditorDialog

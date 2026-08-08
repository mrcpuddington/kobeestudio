"""Kobee Studio 2.0 editor shell.

This editor intentionally does not inherit or rearrange the retained
wxFormBuilder/KiBuzzard dialog.  Every window is created under its final parent
and attached to one sizer for its entire lifetime, which keeps the UI stable on
Windows while giving each artwork tool a focused page.
"""

from __future__ import annotations

import base64
import json
import traceback
from pathlib import Path

import wx

from ..core.app_preferences import AppPreferences, AppPreferencesStore
from ..core.composition import DocumentStyle, Padding, ShapeStyle, TypographyStyle
from ..core.component_callout import ComponentCalloutSpec
from ..core.icon_catalog import render_symbol
from ..core.machine_codes import (
    CODE128_DEFAULT_HEIGHT_MM,
    CODE128_DEFAULT_MODULE_MM,
    CODE128_MIN_HEIGHT_MM,
    CODE128_MIN_MODULE_MM,
    QR_MIN_MODULE_MM,
)
from ..core.measurement_units import MeasurementUnit, from_millimetres, to_millimetres
from ..core.pin_header import PinHeaderSpec, maximum_pin_label_height
from ..core.settings_profiles import SettingsProfileStore, profile_module_for_mode
from ..core.studio_artwork import (
    TextVectorizer,
    render_component_callout_artwork,
    render_header_artwork,
    render_label_artwork,
    render_machine_code_artwork,
)
from ..core.svg_symbols import (
    SvgAssetStore,
    format_symbol_reference,
    parse_symbol_reference,
    symbol_catalog_for_context,
)
from ..core.quick_labels import QuickLabelStore
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
from .settings_dialog import SettingsDialog
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
    CONTENT_LAYOUT_LABELS,
    DEFAULT_LABEL_DIMENSIONS,
    HEADER_CAP_LABELS,
    HEADER_SHAPE_LABELS,
    ICON_ID_TO_LABEL,
    ICON_LABELS,
    ICON_POSITION_LABELS,
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


KOBEE_STUDIO_DOCS_URL = "https://www.coreybusuttil.com/kobeestudio/docs/"
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
}

TOOL_DEFINITIONS = (
    ("labels", "Standard", "Label"),
    ("labels", "Header Overlay", "2.54 mm Pin Header"),
    ("labels", "Component Callout", "Component Callout"),
    ("labels", "Component Array", "Component Array"),
    ("codes", "QR Code", "QR / Barcode"),
    ("codes", "Barcode", "QR / Barcode"),
)

MEASUREMENT_SETTING_KEYS = frozenset(
    (
        "BorderThicknessCtrl", "ComponentArrayPitchCtrl", "ComponentClearanceCtrl",
        "ComponentCutoutRadiusCtrl", "ComponentHeightCtrl", "ComponentMinHeightCtrl",
        "ComponentMinWidthCtrl", "ComponentTextGapCtrl", "ComponentWidthCtrl",
        "CornerRadiusCtrl", "FeatureSizeCtrl", "HeaderCrossSizeCtrl",
        "HeaderLabelOuterPaddingCtrl", "HeaderLabelPaddingCtrl", "HeaderLeadingPaddingCtrl",
        "HeaderOpeningEndPaddingCtrl", "HeaderPadClearanceCtrl", "HeaderPinOuterPaddingCtrl",
        "HeaderPinToLabelGapCtrl", "HeaderTrailingPaddingCtrl", "HeightCtrl", "IconGapCtrl",
        "IconHeightCtrl", "MachineCodeBarHeightCtrl", "MachineCodeCaptionHeightCtrl",
        "MachineCodeContentGapCtrl", "MachineCodeContentHeightCtrl", "MachineCodeFramePaddingCtrl",
        "MachineCodeModuleSizeCtrl", "PaddingBottomCtrl", "PaddingLeftCtrl", "PaddingRightCtrl",
        "PaddingTopCtrl", "SubtitleGapCtrl", "SubtitleHeightCtrl", "UnderlineGapCtrl",
        "UnderlineThicknessCtrl", "WidthCtrl",
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
            self.SetMinSize(wx.Size(112, 38))
        else:
            icon_width = 20 if icon else 0
            self.SetMinSize(wx.Size(width + icon_width + (28 if kind == "family" else 24), 38))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._activate)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

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
        width, height = parent.GetTextExtent(label)
        self.SetMinSize(wx.Size(width + 30, 36))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, lambda event: self.callback())
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

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
        rect = self.GetClientRect().Deflate(1)
        fill = ACCENT if self.primary else palette["active"]
        if self.hovered and self.primary:
            fill = wx.Colour(246, 189, 32)
        dc.SetPen(wx.Pen(wx.Colour(204, 146, 0) if self.primary else palette["border"]))
        dc.SetBrush(wx.Brush(fill))
        dc.DrawRoundedRectangle(rect, 9)
        dc.SetFont(self.GetFont().Bold())
        dc.SetTextForeground(ACCENT_TEXT if self.primary else palette["text"])
        dc.DrawLabel(self.GetLabel(), self.GetClientRect(), wx.ALIGN_CENTER)


class SettingsCard(wx.Panel):
    """Soft neutral settings card matching the approved mockup."""

    def __init__(self, parent, title):
        super().__init__(parent, style=wx.BORDER_NONE)
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
            style |= wx.TE_MULTILINE | getattr(wx, "TE_NO_VSCROLL", 0)
        self.editor = wx.TextCtrl(self, value=value, style=style)
        if multiline and hasattr(self.editor, "ShowScrollbars"):
            never = getattr(wx, "SHOW_SB_NEVER", 0)
            self.editor.ShowScrollbars(never, never)
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

    def SetFocus(self):
        return self.editor.SetFocus()

    def _relay_text(self, event):
        command = wx.CommandEvent(wx.EVT_TEXT.typeId, self.GetId())
        command.SetEventObject(self)
        self.ProcessWindowEvent(command)

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
        self.ProcessWindowEvent(command)

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
        self._profile_ids = ("") + tuple(profile.profile_id for profile in self._profiles)
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
        self.SetMinSize(wx.Size(470, 190))
        self.SetSize(wx.Size(500, 210))

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
        self._cache = ((), (), ())
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_left_up)

    def set_artwork(self, filled, strokes, guides, layer, error=None):
        self._filled = tuple(tuple(poly) for poly in filled)
        self._strokes = tuple(tuple(stroke.points) for stroke in strokes)
        self._guides = tuple(tuple(poly) for poly in guides)
        self._layer = layer
        self._error = error
        self._rebuild_cache()
        self.Refresh(False)

    def fit(self):
        self._zoom = 1.0
        self._pan = wx.Point(0, 0)
        self._rebuild_cache()
        self.Refresh(False)

    def zoom(self, factor):
        self._zoom = max(0.4, min(4.0, self._zoom * float(factor)))
        self._rebuild_cache()
        self.Refresh(False)

    def _on_size(self, event):
        self._rebuild_cache()
        event.Skip()

    def _on_wheel(self, event):
        self.zoom(1.12 if event.GetWheelRotation() > 0 else 1.0 / 1.12)

    def _on_left_down(self, event):
        self._drag_anchor = event.GetPosition() - self._pan
        if not self.HasCapture():
            self.CaptureMouse()

    def _on_left_up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        self._drag_anchor = None
        if event is not None:
            event.Skip()

    def _on_motion(self, event):
        if self._drag_anchor is None or not event.Dragging() or not event.LeftIsDown():
            return
        self._pan = event.GetPosition() - self._drag_anchor
        self._rebuild_cache()
        self.Refresh(False)

    @staticmethod
    def _device_points(polygons, zoom, pan):
        result = []
        for polygon in polygons:
            points = [
                wx.Point(
                    int(round(x * zoom + pan.x)),
                    int(round(y * zoom + pan.y)),
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
            fitted = fit_preview_polygons(converted, width, height, margin=0.12)
            device = self._device_points(fitted, self._zoom, self._pan)
            filled_end = len(self._filled)
            stroke_end = filled_end + len(self._strokes)
            self._cache = (
                device[:filled_end],
                device[filled_end:stroke_end],
                device[stroke_end:],
            )
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
            dc.SetDeviceOrigin(size.width // 2, size.height // 2)
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
        except Exception:
            # Never unwind through wx's native paint callback. A paint-time
            # Python exception can invalidate the native DC and crash KiCad.
            traceback.print_exc()
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
        super().__init__(parent, style=wx.TAB_TRAVERSAL | wx.BORDER_NONE)
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
        self.SetBackgroundColour(_palette()["controls"])
        self.root = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(self.root)
        self.section_bar = wx.Panel(self)
        self.section_bar.SetBackgroundColour(_palette()["subnav"])
        self.section_bar.SetMinSize(wx.Size(126, -1))
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
        columns = wx.BoxSizer(wx.HORIZONTAL)
        self.columns_sizer = columns
        self.card_columns = (wx.BoxSizer(wx.VERTICAL), wx.BoxSizer(wx.VERTICAL))
        columns.Add(self.card_columns[0], 1, wx.EXPAND | wx.RIGHT, 6)
        columns.Add(self.card_columns[1], 1, wx.EXPAND | wx.LEFT, 6)
        self.content.SetSizer(columns)
        self.root.Add(self.content, 1, wx.EXPAND | wx.ALL, 14)
        self._build()
        self._build_section_nav()
        self._update_card_layout(force=True)
        self._show_section(self.sections[0])
        self.content.FitInside()
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _card(self, title):
        card = SettingsCard(self.content, title)
        section = self._section_for_card(title)
        if section not in self.sections:
            self.sections.append(section)
        self.cards.append((card, section))
        self._active_parent = card
        return card.body

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
        event.Skip()

    def _section_for_card(self, title):
        if title in ("Content", "Presentation"):
            return "Basics"
        if title == "Container":
            return "Container"
        if title == "Opening & spacing":
            return "Spacing"
        if title == "Component safe zone":
            return "Safe zone"
        if title == "Typography & spacing":
            return "Typography"
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
        self.content.Layout()
        self.content.FitInside()
        self.content.Scroll(0, 0)

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
            self._add(grid, "IconPositionChoice", "Symbol position", self.choice(("Left of text", "Right of text"), "Left of text"))
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
        self._content_card.Layout()
        self.Layout()
        self.content.FitInside()

    def _on_content_mode_changed(self, event):
        self._update_content_ui()
        self.dialog.request_preview(immediate=True)
        event.Skip()

    def _on_content_layout_changed(self, event):
        self._update_content_ui()
        self.dialog.request_preview(immediate=True)
        event.Skip()

    def _build_container(self, shapes):
        box = self._card("Container")
        self._container_card = self._active_parent
        grid = self._grid(box)
        special_shape = (
            "Independent long edges"
            if self.mode == "2.54 mm Pin Header"
            else "Independent ends"
        )
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
        self._add(grid, "ShapeVariantChoice", "Appearance", self.segmented(VARIANT_LABELS, "Inverted fill"))
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
        self.dialog.request_preview(immediate=True)
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
        self.dialog.request_preview(immediate=True)
        event.Skip()

    def _on_container_variant_changed(self, event):
        self._update_container_ui()
        self.dialog.request_preview(immediate=True)
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
        self._container_card.Layout()
        self.Layout()
        self.content.FitInside()

    def _update_text_details_ui(self):
        """Keep optional text effects out of the way until they are enabled."""
        if "UnderlineCheckbox" not in self.controls:
            return
        underline = self.controls["UnderlineCheckbox"].GetValue()
        inline = self.controls["inlineFormatTextbox"].GetValue()
        self._set_field_visible("UnderlineThicknessCtrl", underline)
        self._set_field_visible("UnderlineGapCtrl", underline)
        self._set_field_visible("lineoverStyleChoice", inline)
        self._set_field_visible("lineoverThicknessCtrl", inline)
        self.Layout()
        self.content.FitInside()

    def _on_text_details_changed(self, event):
        self._update_text_details_ui()
        self.dialog.request_preview(immediate=True)
        event.Skip()

    def _update_header_opening_ui(self):
        if "HeaderOpeningChoice" not in self.controls:
            return
        continuous = (
            self.controls["HeaderOpeningChoice"].GetStringSelection()
            == "Continuous plug opening"
        )
        self._set_field_visible("HeaderOpeningEndPaddingCtrl", continuous)
        self.Layout()
        self.content.FitInside()

    def _on_header_opening_changed(self, event):
        self._update_header_opening_ui()
        self.dialog.request_preview(immediate=True)
        event.Skip()

    def _update_component_safe_zone_ui(self):
        if "ComponentCutoutChoice" not in self.controls:
            return
        rounded = (
            self.controls["ComponentCutoutChoice"].GetStringSelection()
            == "Rounded rectangle"
        )
        self._set_field_visible("ComponentCutoutRadiusCtrl", rounded)
        self.Layout()
        self.content.FitInside()

    def _on_component_cutout_changed(self, event):
        self._update_component_safe_zone_ui()
        self.dialog.request_preview(immediate=True)
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
        self.Layout()
        self.content.FitInside()

    def _on_machine_code_changed(self, event):
        self._update_machine_code_ui()
        self.dialog.request_preview(immediate=True)
        event.Skip()

    def _font_names(self):
        font_dir = Path(__file__).resolve().parents[1] / "fonts"
        return tuple(sorted(path.stem for path in font_dir.iterdir() if path.suffix.lower() in (".ttf", ".otf")))

    def _build_typography(self, *, padding=True, subtitle=False, width=False):
        box = self._card("Typography & spacing")
        grid = self._grid(box)
        defaults = MODE_DEFAULTS[self.mode]
        self._add(grid, "FontComboBox", "Typeface", self.choice(self._font_names(), defaults.get("FontComboBox", "FreddySpark-Regular")))
        max_height = maximum_pin_label_height() if self.mode == "2.54 mm Pin Header" else 128
        self._add(grid, "HeightCtrl", "Text height (mm)", self.spin(0.1, max_height, defaults.get("HeightCtrl", 1.2), 0.1))
        self._add(grid, "AlignmentChoice", "Alignment", self.choice(("Left", "Center", "Right"), defaults.get("AlignmentChoice", "Center")))
        self._add(grid, "LineSpacingCtrl", "Line spacing", self.spin(0.1, 10, 1.5, 0.1))
        if width:
            self._add(grid, "WidthCtrl", "Minimum width (mm)", self.spin(0, 200, 0, 0.1))
        if subtitle:
            self._add(grid, "SubtitleFontChoice", "Subtitle typeface", self.choice((MATCH_MAIN_TYPEFACE,) + self._font_names(), MATCH_MAIN_TYPEFACE))
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
        if self.label == "Standard":
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
            self._add(grid, "inlineFormatTextbox", "Legacy inline markup", self.checkbox("Enable", False))
            self._add(grid, "lineoverStyleChoice", "Overline style", self.choice(("Square", "Rounded"), "Rounded"))
            lineover = self.integer_spin(1, 10, 1)
            self._add(grid, "lineoverThicknessCtrl", "Overline weight", lineover)
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
        elif self.label == "Header Overlay":
            content = self._card("2.54 mm header")
            self._build_content(content, multiline=True)
            grid = self._grid(content)
            pin_count = self._add(grid, "HeaderPinCountCtrl", "Pins", self.integer_spin(1, 40, 4))
            orientation = self._add(grid, "HeaderOrientationChoice", "Orientation", self.choice(("Vertical", "Horizontal"), "Vertical"))
            self._add(grid, "HeaderPinSideChoice", "Pins on", self.choice(("Left", "Right"), "Left"))
            self._add(grid, "HeaderPin1Choice", "Pin 1 end", self.choice(("Start", "End"), "Start"))
            self._add(grid, "HeaderPin1MarkerCheckbox", "Pin 1 marker", self.checkbox("Show marker", True))
            opening = self._card("Opening & spacing")
            grid = self._grid(opening)
            self._add(grid, "HeaderOpeningChoice", "Opening", self.choice(OPENING_LABELS, "Continuous plug opening"))
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
            self.controls["HeaderOpeningChoice"].Bind(
                wx.EVT_CHOICE, self._on_header_opening_changed
            )
            self._update_header_opening_ui()
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
            preset_choice = self._add(grid, "ComponentPresetChoice", "Package / envelope", self.choice(COMPONENT_PRESET_LABELS, component_default_label))
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
        else:
            barcode = self.label == "Barcode"
            code = self._card("Code 128 barcode" if barcode else "QR code")
            payload = self.text("KOBEE-001" if barcode else MODE_DEFAULTS["QR / Barcode"]["MultiLineText"], True)
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
                self._add(grid, "MachineCodeCaptionCtrl", "Footer text", self.text("SCAN ME"))
                self._add(grid, "MachineCodeCaptionHeightCtrl", "Footer height (mm)", self.spin(0.8, 10, 1.2, 0.1, 1))
            self._add(grid, "MachineCodeShowContentCheckbox", "Readable text", self.checkbox("Show text below code", False))
            self._add(grid, "MachineCodeContentCtrl", "Text below code", self.text("kobee.com.au" if not barcode else "KOBEE-001"))
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

    def _insert_character(self, value):
        control = self.controls["MultiLineText"]
        control.WriteText(value)
        control.SetFocus()

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

    def _on_component_preset_changed(self, event):
        preset = COMPONENT_PRESET_BY_LABEL.get(
            self.controls["ComponentPresetChoice"].GetStringSelection()
        )
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
                    self.dialog.request_preview(immediate=True)
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
                self.dialog.request_preview(immediate=True)
        finally:
            dialog.Destroy()

    def settings(self):
        settings = {key: _control_value(control) for key, control in self.controls.items()}
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
        saved_shape = str(settings.get("ShapeChoice", ""))
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


class StudioEditorDialog(wx.Dialog):
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
        self.project_path = _active_board_path(editor_session)
        self.global_asset_store = SvgAssetStore.global_store(self.data_root)
        self.global_label_store = QuickLabelStore.global_store(self.data_root)
        self.project_asset_store = (
            SvgAssetStore.project_store(self.project_path)
            if self.project_path is not None
            else None
        )
        self.project_label_store = (
            QuickLabelStore.project_store(self.project_path)
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
        self._loading = True
        self._family = "labels"
        self._tool = "Standard"
        self._editing_existing = False
        self._default_applied_tools = set()
        self._recalled_profile_ids = {}
        self.restart_requested = False
        self._output_layers = (FRONT_SILKSCREEN,)
        self._text_vectorizer = TextVectorizer(self.buzzard)
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_preview_timer, self._timer)
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
        self.request_preview(immediate=True)
        self.Centre(wx.BOTH)

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
        for family, label in (("labels", "Labels"), ("codes", "Codes")):
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
        self.tool_sizer = wx.BoxSizer(wx.HORIZONTAL)
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
        self.tool_sizer.AddStretchSpacer(1)
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
        placement_sizer = wx.BoxSizer(wx.HORIZONTAL)
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
        placement_sizer.AddStretchSpacer(1)
        root.Add(self.placement_bar, 0, wx.EXPAND | wx.BOTTOM, 6)

        workspace = wx.BoxSizer(wx.HORIZONTAL)
        self.pages = wx.Simplebook(self)
        self.pages.SetBackgroundColour(palette["controls"])
        self.page_by_tool = {}
        self.page_index_by_tool = {}
        for family, label, mode in TOOL_DEFINITIONS:
            page = ToolPage(self.pages, self, family, label, mode)
            self.pages.AddPage(page, label)
            self.page_by_tool[label] = page
            self.page_index_by_tool[label] = self.pages.GetPageCount() - 1
        self.pages.SetMinSize(wx.Size(500, 440))
        workspace.Add(self.pages, 1, wx.EXPAND | wx.RIGHT, 10)

        preview_panel = wx.Panel(self, style=wx.BORDER_NONE)
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
        preview_controls = wx.BoxSizer(wx.HORIZONTAL)
        preview_controls.Add(wx.StaticText(preview_panel, label="Preview layer"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.layer_choice = ThemedChoice(preview_panel, choices=tuple(PREVIEW_LAYER_LABELS[layer] for layer in self._output_layers))
        self.layer_choice.SetMinSize(wx.Size(140, 30))
        self.layer_choice.SetStringSelection(PREVIEW_LAYER_LABELS[FRONT_SILKSCREEN])
        self.layer_choice.Bind(wx.EVT_CHOICE, self.on_control_changed)
        preview_controls.Add(self.layer_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 7)
        for label, handler in (
            ("Fit", lambda: self.preview.fit()),
            ("−", lambda: self.preview.zoom(1 / 1.2)),
            ("+", lambda: self.preview.zoom(1.2)),
        ):
            button = KobeeAction(preview_panel, label, handler)
            preview_controls.Add(button, 0, wx.RIGHT, 4)
        toolbar.Add(preview_controls, 0, wx.EXPAND)
        preview_root.Add(toolbar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.preview = PreviewCanvas(preview_panel)
        self.preview.SetMinSize(wx.Size(300, 410))
        preview_root.Add(self.preview, 1, wx.EXPAND | wx.TOP, 8)
        self.preview_status = wx.StaticText(preview_panel, label="Front side · Front Silkscreen")
        preview_root.Add(self.preview_status, 0, wx.TOP, 7)
        self.preview_error = wx.StaticText(preview_panel, label="")
        self.preview_error.SetForegroundColour(wx.Colour(190, 55, 45))
        self.preview_error.SetMinSize(wx.Size(-1, 34))
        preview_root.Add(self.preview_error, 0, wx.EXPAND | wx.TOP, 4)
        preview_panel.SetMinSize(wx.Size(390, -1))
        workspace.Add(preview_panel, 1, wx.EXPAND)
        root.Add(workspace, 1, wx.EXPAND)

        root.Add(wx.StaticLine(self), 0, wx.EXPAND)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        shortcut = wx.StaticText(self, label="Ctrl/Shift + Enter places artwork")
        shortcut.SetForegroundColour(palette["muted"])
        footer.Add(shortcut, 1, wx.ALIGN_CENTER_VERTICAL)
        cancel = KobeeAction(self, "Cancel", self._cancel)
        self.place_button = KobeeAction(
            self,
            "Update artwork" if self.updateFootprint is not None else "Place artwork",
            lambda: self.OnOkClick(None),
            primary=True,
        )
        footer.Add(cancel, 0, wx.RIGHT, 7)
        footer.Add(self.place_button, 0)
        root.Add(footer, 0, wx.EXPAND | wx.ALL, 12)

        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        display = wx.GetClientDisplayRect()
        self.SetMinSize(wx.Size(min(980, display.width - 30), min(620, display.height - 30)))
        self.SetSize(wx.Size(min(1220, display.width - 50), min(780, display.height - 50)))

    def _profile_module(self):
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

    def _open_settings(self, initial_page=0):
        dialog = SettingsDialog(
            self,
            preferences_store=self.preferences_store,
            profile_store=self.profile_store,
            global_asset_store=self.global_asset_store,
            project_asset_store=self.project_asset_store,
            global_label_store=self.global_label_store,
            project_label_store=self.project_label_store,
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
            self._cancel()
            return
        self._refresh_symbol_catalog()
        self._refresh_profile_bar()
        self.request_preview(immediate=True)

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
        self.request_preview(immediate=True)

    def _on_preferences_changed(self, preferences):
        old_appearance = self.preferences.appearance
        self.preferences = preferences
        set_appearance_preference(preferences.appearance)
        requested_unit = preferences.measurement_unit
        if requested_unit is not self.measurement_unit:
            self._loading = True
            try:
                for page in self.page_by_tool.values():
                    page.set_measurement_unit(requested_unit)
                self.measurement_unit = requested_unit
            finally:
                self._loading = False
            self.request_preview(immediate=True)
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
        for page in self.page_by_tool.values():
            button = page.controls.get("IconChoice")
            if button is not None:
                button.symbol_catalog = self.symbol_catalog

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN and (event.ControlDown() or event.ShiftDown()):
            self.OnOkClick(event)
            return
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._cancel()
            return
        event.Skip()

    def _cancel(self):
        self._timer.Stop()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event):
        self._timer.Stop()
        event.Skip()

    def _select_family(self, family):
        if self._loading:
            return
        tools = [label for item_family, label, mode in TOOL_DEFINITIONS if item_family == family]
        self._family = family
        if self._tool not in tools:
            # Route through the normal tool selector so a default profile is
            # applied consistently when a family is first opened.
            self._select_tool(tools[0])
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
        self._tool = tool
        self._family = self.page_by_tool[tool].family
        if not self._editing_existing and tool not in self._default_applied_tools:
            try:
                profile = self.profile_store.load(profile_module_for_mode(self.page_by_tool[tool].mode))
                self.page_by_tool[tool].apply(profile.settings)
                self._recalled_profile_ids[profile.module] = profile.profile_id
                layer = profile.settings.get("LayerComboBox", FRONT_SILKSCREEN)
                layers = profile.settings.get("OutputLayers", (layer,))
                self._set_output_layers(layers if isinstance(layers, (tuple, list)) else (layer,), preview_layer=layer)
            except (LookupError, OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
        self._default_applied_tools.add(tool)
        self.Freeze()
        try:
            self._update_tab_state()
            self._show_active_page()
        finally:
            self.Thaw()
        self._refresh_profile_bar()
        self.request_preview()

    def _rebuild_tool_bar(self):
        for family, label, mode in TOOL_DEFINITIONS:
            button = self.tool_buttons[label]
            button.Show(family == self._family)
            button.set_active(label == self._tool)
        self.tool_bar.Layout()

    def _update_tab_state(self):
        for family, button in self.family_buttons.items():
            selected = family == self._family
            button.set_active(selected)
        self._rebuild_tool_bar()

    def _show_active_page(self):
        page = self.page_by_tool[self._tool]
        self.pages.ChangeSelection(self.page_index_by_tool[self._tool])
        page.Layout()
        page.content.Scroll(0, 0)

    def _route_settings(self, settings):
        mode = settings.get("StudioModeChoice", "Label")
        if mode == "QR / Barcode":
            tool = "Barcode" if settings.get("MachineCodeTypeChoice") == "Code 128 barcode" else "QR Code"
        else:
            tool = {
                "Label": "Standard",
                "2.54 mm Pin Header": "Header Overlay",
                "Component Callout": "Component Callout",
                "Component Array": "Component Array",
            }.get(mode, "Standard")
        self._tool = tool
        self._family = self.page_by_tool[tool].family
        self.page_by_tool[tool].apply(settings)
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
            self.request_preview(immediate=True)
        event.Skip()

    def CurrentSettings(self):
        settings = mode_defaults(self.active_page.mode)
        settings.update(self.active_page.settings())
        if hasattr(self.active_page, "_effective_shape_choice"):
            settings["ShapeChoice"] = self.active_page._effective_shape_choice()
        if hasattr(self.active_page, "_effective_end_caps"):
            settings["StartCapChoice"], settings["EndCapChoice"] = self.active_page._effective_end_caps()
        settings["StudioModeChoice"] = self.active_page.mode
        settings["MachineCodeTypeChoice"] = "Code 128 barcode" if self._tool == "Barcode" else settings.get("MachineCodeTypeChoice", "QR Code")
        settings["LayerComboBox"] = self.output_layer
        settings["OutputLayers"] = list(self.output_layers)
        settings["StudioDimensionsVersion"] = STUDIO_DIMENSIONS_VERSION
        settings["StudioDefaultsVersion"] = STUDIO_DEFAULTS_VERSION
        return settings

    def on_control_changed(self, event):
        if not self._loading:
            self.request_preview()
        event.Skip()

    def request_preview(self, immediate=False):
        self._timer.Stop()
        if immediate:
            self._pending_preview = False
            self._regenerate_preview()
        else:
            self._pending_preview = True
            self._timer.StartOnce(150)

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
        settings = self.CurrentSettings()
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
            if self._tool in ("QR Code", "Barcode"):
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
                    orientation=orientation,
                    pin1_end=str(settings.get("HeaderPin1Choice", "Start")).lower(),
                    label_side=PIN_SIDE_TO_LABEL_SIDE[side],
                    pad_clearance_mm=float(settings.get("HeaderPadClearanceCtrl", 2.0)),
                    opening_mode=OPENING_LABELS.get(settings.get("HeaderOpeningChoice"), "continuous"),
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
                preset = COMPONENT_PRESET_BY_LABEL.get(settings.get("ComponentPresetChoice"))
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
                    preset_id=COMPONENT_PRESET_LABELS.get(settings.get("ComponentPresetChoice"), "custom"),
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
                    icon_variant=icon_variant,
                    icon_renderer=icon_renderer,
                )
            self.polys = list(self.artwork.filled_polygons)
            self.stroke_polys = list(self.artwork.strokes)
            self.guide_polys = list(self.artwork.guides)
            self._last_valid = (self.artwork, tuple(self.polys), tuple(self.stroke_polys), tuple(self.guide_polys))
            self.preview.set_artwork(self.polys, self.stroke_polys, self.guide_polys, self.output_layer)
            self.preview_error.SetLabel("")
        except ValueError as error:
            self._show_preview_error(error)
        except Exception as error:
            traceback.print_exc()
            self._show_preview_error(error)
        side = "Bottom side · front-view mirror" if is_bottom(self.output_layer) else "Front side"
        self.preview_status.SetLabel("{} · {}".format(side, LAYER_LABELS[self.output_layer]))

    def _show_preview_error(self, error):
        self.error = str(error) or "Preview unavailable"
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

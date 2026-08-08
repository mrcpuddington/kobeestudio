"""Painted input controls for reliable light and dark editor surfaces.

wx's Cocoa choice and spin controls intentionally keep macOS' native field
appearance, ignoring background colours in a dark custom window.  These small
controls keep the compact editor interactions while drawing their closed state
with Kobee's own palette.
"""

from __future__ import annotations

import math

import wx

from .theme import is_dark_mode


def _colours():
    dark = is_dark_mode(wx)
    values = {
        "field": (71, 66, 58) if dark else (255, 255, 253),
        "border": (91, 86, 77) if dark else (191, 190, 185),
        "text": (245, 242, 236) if dark else (34, 33, 30),
        "muted": (179, 173, 163) if dark else (113, 108, 100),
        "hover": (86, 80, 70) if dark else (244, 242, 237),
        "accent": (235, 177, 20),
        "accent_text": (24, 22, 18),
    }
    return {name: wx.Colour(*value) for name, value in values.items()}


class ThemedChoice(wx.Control):
    """A dark-safe closed choice that uses a normal menu for its popup."""

    def __init__(self, parent, choices=()):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._choices = [str(choice) for choice in choices]
        self._selection = 0 if self._choices else wx.NOT_FOUND
        self._hovered = False
        self.SetMinSize(wx.Size(112, 30))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    def GetCount(self):
        return len(self._choices)

    def GetSelection(self):
        return self._selection

    def SetSelection(self, index):
        index = int(index)
        self._selection = index if 0 <= index < len(self._choices) else wx.NOT_FOUND
        self.Refresh(False)

    def GetStringSelection(self):
        return self._choices[self._selection] if 0 <= self._selection < len(self._choices) else ""

    def SetStringSelection(self, value):
        try:
            self._selection = self._choices.index(str(value))
        except ValueError:
            return False
        self.Refresh(False)
        return True

    def SetItems(self, choices):
        selected = self.GetStringSelection()
        self._choices = [str(choice) for choice in choices]
        self._selection = self._choices.index(selected) if selected in self._choices else (0 if self._choices else wx.NOT_FOUND)
        self.Refresh(False)

    def _emit_choice(self):
        event = wx.CommandEvent(wx.EVT_CHOICE.typeId, self.GetId())
        event.SetEventObject(self)
        self.ProcessWindowEvent(event)

    def _select(self, index):
        if not 0 <= index < len(self._choices) or index == self._selection:
            return
        self._selection = index
        self.Refresh(False)
        self._emit_choice()

    def _show_menu(self):
        if not self._choices or not self.IsEnabled():
            return
        menu = wx.Menu()
        try:
            for index, label in enumerate(self._choices):
                item = menu.AppendRadioItem(wx.ID_ANY, label)
                item.Check(index == self._selection)
                menu.Bind(wx.EVT_MENU, lambda event, item_index=index: self._select(item_index), item)
            self.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _on_click(self, event):
        self._show_menu()
        event.Skip()

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_SPACE, wx.WXK_RETURN):
            self._show_menu()
        elif key in (wx.WXK_UP, wx.WXK_LEFT):
            self._select(max(0, self._selection - 1))
        elif key in (wx.WXK_DOWN, wx.WXK_RIGHT):
            self._select(min(len(self._choices) - 1, self._selection + 1))
        else:
            event.Skip()

    def _on_enter(self, event):
        self._hovered = True
        self.Refresh(False)

    def _on_leave(self, event):
        self._hovered = False
        self.Refresh(False)

    def _on_paint(self, event):
        colours = _colours()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        rect = self.GetClientRect().Deflate(1)
        fill = colours["hover"] if self._hovered and self.IsEnabled() else colours["field"]
        dc.SetPen(wx.Pen(colours["border"]))
        dc.SetBrush(wx.Brush(fill))
        dc.DrawRoundedRectangle(rect, 5)
        dc.SetTextForeground(colours["text"] if self.IsEnabled() else colours["muted"])
        dc.DrawLabel(
            self.GetStringSelection(),
            wx.Rect(rect.x + 8, rect.y, max(1, rect.width - 28), rect.height),
            wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL,
        )
        arrow_x = rect.GetRight() - 11
        arrow_y = rect.y + rect.height // 2
        dc.SetPen(wx.Pen(colours["muted"]))
        dc.SetBrush(wx.Brush(colours["muted"]))
        dc.DrawPolygon(
            [
                wx.Point(arrow_x - 4, arrow_y - 2),
                wx.Point(arrow_x + 4, arrow_y - 2),
                wx.Point(arrow_x, arrow_y + 3),
            ]
        )


class ThemedSpinCtrlDouble(wx.Control):
    """Text-editable floating field with Kobee-painted increment arrows."""

    arrow_width = 19

    def __init__(self, parent, value="0", min=0.0, max=100.0, initial=0.0, inc=0.1):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._minimum = float(min)
        self._maximum = float(max)
        self._increment = float(inc)
        self._digits = 2
        self._value = float(initial)
        self.editor = wx.TextCtrl(self, value=str(value), style=wx.BORDER_NONE | wx.TE_PROCESS_ENTER)
        self._apply_colours()
        self.SetMinSize(wx.Size(84, 30))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.editor.Bind(wx.EVT_TEXT, self._on_text)
        self.editor.Bind(wx.EVT_TEXT_ENTER, self._on_text_enter)
        self.SetValue(initial)

    def _apply_colours(self):
        colours = _colours()
        self.editor.SetOwnBackgroundColour(colours["field"])
        self.editor.SetBackgroundColour(colours["field"])
        self.editor.SetOwnForegroundColour(colours["text"])
        self.editor.SetForegroundColour(colours["text"])

    def _on_size(self, event):
        size = self.GetClientSize()
        self.editor.SetPosition(wx.Point(5, 3))
        self.editor.SetSize(wx.Size(max(1, size.width - self.arrow_width - 7), max(1, size.height - 6)))
        event.Skip()

    def _finite(self, value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("A numeric value is required")
        return result

    def _clamp(self, value):
        return max(self._minimum, min(self._maximum, self._finite(value)))

    def GetValue(self):
        try:
            return self._clamp(self.editor.GetValue())
        except ValueError:
            return self._value

    def SetValue(self, value):
        self._value = self._clamp(value)
        self.editor.ChangeValue("{value:.{digits}f}".format(value=self._value, digits=self._digits))
        self.Refresh(False)

    def SetRange(self, minimum, maximum):
        minimum, maximum = self._finite(minimum), self._finite(maximum)
        if minimum > maximum:
            raise ValueError("Minimum cannot exceed maximum")
        self._minimum, self._maximum = minimum, maximum
        self.SetValue(self.GetValue())

    def SetIncrement(self, increment):
        increment = self._finite(increment)
        if increment <= 0:
            raise ValueError("Increment must be greater than zero")
        self._increment = increment

    def SetDigits(self, digits):
        digits = int(digits)
        if not 0 <= digits <= 9:
            raise ValueError("Digits must be between 0 and 9")
        self._digits = digits
        self.SetValue(self.GetValue())

    def Enable(self, enable=True):
        self.editor.Enable(enable)
        result = super().Enable(enable)
        self.Refresh(False)
        return result

    def _notify(self, event_type):
        event = wx.CommandEvent(event_type.typeId, self.GetId())
        event.SetEventObject(self)
        self.ProcessWindowEvent(event)

    def _on_text(self, event):
        try:
            self._value = self._clamp(self.editor.GetValue())
        except ValueError:
            pass
        self._notify(wx.EVT_TEXT)

    def _on_text_enter(self, event):
        self.SetValue(self.GetValue())
        self._notify(wx.EVT_SPINCTRLDOUBLE)

    def _on_click(self, event):
        if not self.IsEnabled() or event.GetPosition().x < self.GetClientSize().width - self.arrow_width:
            event.Skip()
            return
        # A zero-valued symbol size means "automatic" in the editor. Promote
        # it to the current text height on the first arrow press rather than
        # making a user climb up from an invisible 0.10 mm override.
        auto_value = getattr(self, "_kobee_auto_value_resolver", None)
        if self.GetValue() == 0 and callable(auto_value):
            self.SetValue(auto_value())
            self._notify(wx.EVT_SPINCTRLDOUBLE)
            return
        amount = self._increment if event.GetPosition().y < self.GetClientSize().height / 2 else -self._increment
        self.SetValue(self.GetValue() + amount)
        self._notify(wx.EVT_SPINCTRLDOUBLE)

    def _on_paint(self, event):
        colours = _colours()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        rect = self.GetClientRect().Deflate(1)
        dc.SetPen(wx.Pen(colours["border"]))
        dc.SetBrush(wx.Brush(colours["field"]))
        dc.DrawRoundedRectangle(rect, 5)
        divider = rect.GetRight() - self.arrow_width + 1
        dc.DrawLine(divider, rect.y + 1, divider, rect.GetBottom() - 1)
        dc.DrawLine(divider, rect.y + rect.height // 2, rect.GetRight() - 1, rect.y + rect.height // 2)
        dc.SetPen(wx.Pen(colours["muted"]))
        dc.SetBrush(wx.Brush(colours["muted"]))
        centre_x = divider + self.arrow_width // 2
        centre_y = rect.y + rect.height // 4 + 1
        dc.DrawPolygon([wx.Point(centre_x - 3, centre_y + 2), wx.Point(centre_x + 3, centre_y + 2), wx.Point(centre_x, centre_y - 2)])
        centre_y = rect.y + rect.height * 3 // 4 - 1
        dc.DrawPolygon([wx.Point(centre_x - 3, centre_y - 2), wx.Point(centre_x + 3, centre_y - 2), wx.Point(centre_x, centre_y + 2)])


class ThemedSpinCtrl(ThemedSpinCtrlDouble):
    """Integer counterpart for pin/component count controls."""

    def __init__(self, parent, min=0, max=100, initial=0):
        super().__init__(parent, value=str(initial), min=min, max=max, initial=initial, inc=1)
        self.SetDigits(0)

    def GetValue(self):
        return int(round(super().GetValue()))

    def SetValue(self, value):
        super().SetValue(int(round(float(value))))


class ThemedTextField(wx.Panel):
    """A compact text field with an application-painted dark surface."""

    def __init__(self, parent, value="", hint=""):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.editor = wx.TextCtrl(self, value=str(value), style=wx.BORDER_NONE | wx.TE_PROCESS_ENTER)
        self._apply_colours()
        if hint:
            self.SetDescriptiveText(hint)
        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)
        root.Add(self.editor, 1, wx.EXPAND | wx.ALL, 6)
        self.SetMinSize(wx.Size(180, 30))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.editor.Bind(wx.EVT_TEXT, self._relay_text)

    def _apply_colours(self):
        colours = _colours()
        self.editor.SetOwnBackgroundColour(colours["field"])
        self.editor.SetBackgroundColour(colours["field"])
        self.editor.SetOwnForegroundColour(colours["text"])
        self.editor.SetForegroundColour(colours["text"])

    def GetValue(self):
        return self.editor.GetValue()

    def SetValue(self, value):
        self.editor.SetValue(str(value))

    def ChangeValue(self, value):
        self.editor.ChangeValue(str(value))

    def SetDescriptiveText(self, text):
        if hasattr(self.editor, "SetHint"):
            self.editor.SetHint(str(text))
        elif hasattr(self.editor, "SetDescriptiveText"):
            self.editor.SetDescriptiveText(str(text))

    def ShowCancelButton(self, _show=True):
        """SearchCtrl compatibility; the filter remains editable without chrome."""

    def SetFocus(self):
        return self.editor.SetFocus()

    def _relay_text(self, event):
        command = wx.CommandEvent(wx.EVT_TEXT.typeId, self.GetId())
        command.SetEventObject(self)
        self.ProcessWindowEvent(command)

    def _on_paint(self, event):
        colours = _colours()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        dc.SetPen(wx.Pen(colours["border"]))
        dc.SetBrush(wx.Brush(colours["field"]))
        dc.DrawRoundedRectangle(self.GetClientRect().Deflate(1), 5)


class ThemedActionButton(wx.Control):
    """A small dialog action that does not revert to a native white button."""

    def __init__(self, parent, label, callback, primary=False):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetLabel(label)
        self.callback = callback
        self.primary = bool(primary)
        self.hovered = False
        width, _height = parent.GetTextExtent(label)
        self.SetMinSize(wx.Size(width + 28, 32))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    def _on_click(self, event):
        if self.IsEnabled():
            self.callback()

    def Enable(self, enable=True):
        result = super().Enable(enable)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND if enable else wx.CURSOR_ARROW))
        self.Refresh(False)
        return result

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN) and self.IsEnabled():
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
        colours = _colours()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        rect = self.GetClientRect().Deflate(1)
        enabled = self.IsEnabled()
        fill = colours["accent"] if self.primary and enabled else colours["field"]
        if self.hovered and enabled:
            fill = wx.Colour(246, 189, 32) if self.primary else colours["hover"]
        dc.SetPen(wx.Pen(wx.Colour(204, 146, 0) if self.primary and enabled else colours["border"]))
        dc.SetBrush(wx.Brush(fill))
        dc.DrawRoundedRectangle(rect, 7)
        dc.SetFont(self.GetFont().Bold())
        dc.SetTextForeground(colours["accent_text"] if self.primary and enabled else (colours["text"] if enabled else colours["muted"]))
        dc.DrawLabel(self.GetLabel(), self.GetClientRect(), wx.ALIGN_CENTER)


class ThemedListBox(wx.Control):
    """A small painted list used where Cocoa's native list stays light."""

    row_height = 32

    def __init__(self, parent, choices=()):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._items = [str(item) for item in choices]
        self._visibility = None
        self._selection = wx.NOT_FOUND
        self._hover = wx.NOT_FOUND
        self._scroll_offset = 0
        self.SetMinSize(wx.Size(180, 120))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)

    def Set(self, choices):
        self._items = [str(item) for item in choices]
        self._visibility = None
        if self._selection >= len(self._items):
            self._selection = wx.NOT_FOUND
        self._scroll_offset = min(self._scroll_offset, self._max_scroll())
        self.Refresh(False)

    def SetVisibilityRows(self, choices, visible):
        """Set rows with a painted open/closed-eye state at the leading edge."""
        self._items = [str(item) for item in choices]
        self._visibility = [bool(value) for value in visible]
        if len(self._visibility) != len(self._items):
            raise ValueError("Visibility state must be provided for every row")
        if self._selection >= len(self._items):
            self._selection = wx.NOT_FOUND
        self._scroll_offset = min(self._scroll_offset, self._max_scroll())
        self.Refresh(False)

    def GetSelection(self):
        return self._selection

    def SetSelection(self, selection):
        selection = int(selection)
        self._selection = selection if 0 <= selection < len(self._items) else wx.NOT_FOUND
        if self._selection != wx.NOT_FOUND:
            visible = self._visible_rows()
            if self._selection < self._scroll_offset:
                self._scroll_offset = self._selection
            elif self._selection >= self._scroll_offset + visible:
                self._scroll_offset = self._selection - visible + 1
        self.Refresh(False)

    def _visible_rows(self):
        return max(1, (max(1, self.GetClientSize().height) - 10) // self.row_height)

    def _max_scroll(self):
        return max(0, len(self._items) - self._visible_rows())

    def _index_at(self, point):
        index = (point.y - 5) // self.row_height + self._scroll_offset
        return index if 0 <= index < len(self._items) else wx.NOT_FOUND

    def _on_click(self, event):
        index = self._index_at(event.GetPosition())
        if index == wx.NOT_FOUND:
            return
        self.SetSelection(index)
        changed = wx.CommandEvent(wx.EVT_LISTBOX.typeId, self.GetId())
        changed.SetEventObject(self)
        changed.SetInt(index)
        self.ProcessWindowEvent(changed)

    def _on_motion(self, event):
        index = self._index_at(event.GetPosition())
        if index != self._hover:
            self._hover = index
            self.Refresh(False)

    def _on_leave(self, event):
        if self._hover != wx.NOT_FOUND:
            self._hover = wx.NOT_FOUND
            self.Refresh(False)

    def _on_wheel(self, event):
        rotation = event.GetWheelRotation()
        if rotation:
            step = max(1, event.GetWheelDelta())
            amount = max(1, abs(rotation) // step)
            offset = self._scroll_offset - amount if rotation > 0 else self._scroll_offset + amount
            offset = max(0, min(self._max_scroll(), offset))
            if offset != self._scroll_offset:
                self._scroll_offset = offset
                self.Refresh(False)

    def _on_paint(self, event):
        colours = _colours()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        rect = self.GetClientRect().Deflate(1)
        dc.SetPen(wx.Pen(colours["border"]))
        dc.SetBrush(wx.Brush(colours["field"]))
        dc.DrawRoundedRectangle(rect, 6)
        for index, item in enumerate(self._items):
            y = 5 + (index - self._scroll_offset) * self.row_height
            if y + self.row_height < 5:
                continue
            if y >= rect.height:
                break
            row = wx.Rect(5, y, max(1, rect.width - 10), self.row_height - 2)
            if index == self._selection:
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.SetBrush(wx.Brush(colours["accent"]))
                dc.DrawRoundedRectangle(row, 4)
                colour = colours["accent_text"]
            elif index == self._hover:
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.SetBrush(wx.Brush(colours["hover"]))
                dc.DrawRoundedRectangle(row, 4)
                colour = colours["text"]
            else:
                colour = colours["text"]
            dc.SetTextForeground(colour)
            if self._visibility is not None:
                self._draw_visibility_icon(dc, row.x + 10, row.y + row.height // 2, self._visibility[index], colour)
                label_rect = wx.Rect(row.x + 34, row.y, max(1, row.width - 42), row.height)
            else:
                label_rect = row.Deflate(9, 0)
            dc.DrawLabel(item, label_rect, wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL)
        if self._max_scroll():
            rail = wx.Rect(rect.GetRight() - 5, 6, 3, max(1, rect.height - 10))
            thumb_height = max(18, rail.height * self._visible_rows() // len(self._items))
            thumb_y = rail.y + (rail.height - thumb_height) * self._scroll_offset // self._max_scroll()
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(colours["muted"]))
            dc.DrawRoundedRectangle(wx.Rect(rail.x, thumb_y, rail.width, thumb_height), 2)

    @staticmethod
    def _draw_visibility_icon(dc, x, y, visible, colour):
        """Draw a theme-coloured eye without relying on an emoji font."""
        rect = wx.Rect(x, y - 6, 16, 12)
        dc.SetPen(wx.Pen(colour, 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawEllipse(rect)
        if visible:
            dc.SetBrush(wx.Brush(colour))
            dc.DrawCircle(x + 8, y, 3)
        else:
            dc.DrawLine(x + 1, y + 7, x + 15, y - 7)


class ThemedCheckBox(wx.Control):
    """Checkbox with legible text and a non-native dark checked state."""

    def __init__(self, parent, label="", value=False):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetLabel(str(label))
        self._value = bool(value)
        width, _height = parent.GetTextExtent(self.GetLabel())
        self.SetMinSize(wx.Size(width + 30, 28))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = bool(value)
        self.Refresh(False)

    def _toggle(self):
        self._value = not self._value
        self.Refresh(False)
        event = wx.CommandEvent(wx.EVT_CHECKBOX.typeId, self.GetId())
        event.SetEventObject(self)
        event.SetInt(int(self._value))
        self.ProcessWindowEvent(event)

    def _on_click(self, event):
        if self.IsEnabled():
            self._toggle()

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN) and self.IsEnabled():
            self._toggle()
        else:
            event.Skip()

    def _on_paint(self, event):
        colours = _colours()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        box = wx.Rect(1, max(1, (self.GetClientSize().height - 16) // 2), 16, 16)
        dc.SetPen(wx.Pen(colours["accent"] if self._value else colours["border"]))
        dc.SetBrush(wx.Brush(colours["accent"] if self._value else colours["field"]))
        dc.DrawRoundedRectangle(box, 3)
        if self._value:
            dc.SetPen(wx.Pen(colours["accent_text"], 2))
            dc.DrawLine(box.x + 3, box.y + 8, box.x + 7, box.y + 12)
            dc.DrawLine(box.x + 7, box.y + 12, box.x + 14, box.y + 4)
        dc.SetTextForeground(colours["text"] if self.IsEnabled() else colours["muted"])
        dc.DrawLabel(self.GetLabel(), wx.Rect(23, 0, max(1, self.GetClientSize().width - 23), self.GetClientSize().height), wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL)


class ThemedTextButton(wx.Control):
    """A compact utility action for glyph insertion and similar controls."""

    def __init__(self, parent, label, callback):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetLabel(str(label))
        self.callback = callback
        width, _height = parent.GetTextExtent(self.GetLabel())
        self.SetMinSize(wx.Size(max(28, width + 14), 26))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_UP, self._on_click)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def _on_click(self, event):
        if self.IsEnabled():
            self.callback()

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN) and self.IsEnabled():
            self.callback()
        else:
            event.Skip()

    def _on_paint(self, event):
        colours = _colours()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        rect = self.GetClientRect().Deflate(1)
        dc.SetPen(wx.Pen(colours["border"]))
        dc.SetBrush(wx.Brush(colours["field"]))
        dc.DrawRoundedRectangle(rect, 5)
        dc.SetTextForeground(colours["text"])
        dc.DrawLabel(self.GetLabel(), self.GetClientRect(), wx.ALIGN_CENTER)

"""Searchable visual pickers for Kobee Studio labels and symbols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

import wx

from ..core.icon_catalog import BUILTIN_ICONS, ICON_BY_ID, LABEL_PRESETS, render_builtin_icon
from ..core.shape_geometry import polygon_bounds


@dataclass(frozen=True)
class PickerItem:
    asset_id: str
    title: str
    category: str
    icon_id: str = ""
    preview_text: str = ""

    @property
    def search_text(self) -> str:
        return "{} {} {}".format(self.title, self.category, self.asset_id).lower()


def label_picker_items() -> Tuple[PickerItem, ...]:
    return (PickerItem("", "Custom text", "Custom"),) + tuple(
        PickerItem(
            preset.preset_id,
            preset.text,
            preset.category,
            preset.icon_id,
            preset.text,
        )
        for preset in LABEL_PRESETS
    )


def icon_picker_items() -> Tuple[PickerItem, ...]:
    return (PickerItem("", "No symbol", "None"),) + tuple(
        PickerItem(icon.asset_id, icon.name, icon.category, icon.asset_id)
        for icon in BUILTIN_ICONS
    )


def filter_picker_items(
    items: Iterable[PickerItem], query: str = "", category: str = "All"
) -> Tuple[PickerItem, ...]:
    words = tuple(word for word in query.lower().split() if word)
    return tuple(
        item
        for item in items
        if (category == "All" or item.category == category)
        and all(word in item.search_text for word in words)
    )


class AssetPickerDialog(wx.Dialog):
    """Searchable, multi-column visual browser for labels and symbols."""

    THUMBNAIL_SIZE = (202, 78)
    GRID_COLUMNS = 3

    def __init__(self, parent, title: str, items: Iterable[PickerItem], selected_id: str = ""):
        super(AssetPickerDialog, self).__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=wx.Size(720, 520),
        )
        self._all_items = tuple(items)
        self._visible_items = ()
        self._selected_id = selected_id
        self._cards = {}

        root = wx.BoxSizer(wx.VERTICAL)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.m_SearchCtrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.m_SearchCtrl.SetDescriptiveText("Search names and categories…")
        self.m_SearchCtrl.ShowCancelButton(True)
        categories = ("All",) + tuple(sorted({item.category for item in self._all_items}))
        self.m_CategoryChoice = wx.Choice(self, choices=categories)
        self.m_CategoryChoice.SetSelection(0)
        filters.Add(self.m_SearchCtrl, 1, wx.RIGHT, 8)
        filters.Add(self.m_CategoryChoice, 0)
        root.Add(filters, 0, wx.EXPAND | wx.ALL, 12)

        self.m_AssetScroller = wx.ScrolledWindow(self, style=wx.BORDER_THEME)
        self.m_AssetScroller.SetBackgroundColour("#14181C")
        self.m_AssetScroller.SetScrollRate(0, 14)
        self.m_AssetGrid = wx.GridSizer(0, self.GRID_COLUMNS, 8, 8)
        self.m_AssetScroller.SetSizer(self.m_AssetGrid)
        root.Add(self.m_AssetScroller, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(560, 380))

        self.m_SearchCtrl.Bind(wx.EVT_TEXT, self._on_filter_changed)
        self.m_CategoryChoice.Bind(wx.EVT_CHOICE, self._on_filter_changed)
        self._rebuild()
        self.m_SearchCtrl.SetFocus()

    @property
    def selected_id(self) -> str:
        return self._selected_id

    def _on_filter_changed(self, event):
        self._rebuild()
        event.Skip()

    def _on_selected(self, event, asset_id):
        # Never destroy/rebuild the clicked native button from inside its own
        # Cocoa event callback.  Doing so causes a use-after-free in wxWidgets
        # and can take the whole KiCad process down.  Updating bitmaps in place
        # gives the same selected-state feedback without changing lifetimes.
        self._selected_id = asset_id
        for visible_id, (card, item) in self._cards.items():
            card.SetBitmap(self._thumbnail(item, visible_id == asset_id))
            card.Refresh(False)
        event.Skip()

    def _on_activated(self, event, asset_id):
        self._selected_id = asset_id
        self.EndModal(wx.ID_OK)

    def _rebuild(self, reset_scroll=True):
        query = self.m_SearchCtrl.GetValue()
        category = self.m_CategoryChoice.GetStringSelection() or "All"
        self._visible_items = filter_picker_items(self._all_items, query, category)
        self.m_AssetGrid.Clear(delete_windows=True)
        self._cards = {}
        for item in self._visible_items:
            selected = item.asset_id == self._selected_id
            card = wx.BitmapButton(
                self.m_AssetScroller,
                bitmap=self._thumbnail(item, selected),
                style=wx.BU_EXACTFIT | wx.BORDER_NONE,
                size=wx.Size(*self.THUMBNAIL_SIZE),
            )
            card.SetToolTip("{} — {}".format(item.title, item.category))
            card.Bind(
                wx.EVT_BUTTON,
                lambda event, asset_id=item.asset_id: self._on_selected(event, asset_id),
            )
            card.Bind(
                wx.EVT_LEFT_DCLICK,
                lambda event, asset_id=item.asset_id: self._on_activated(event, asset_id),
            )
            self.m_AssetGrid.Add(card, 0, wx.EXPAND)
            self._cards[item.asset_id] = (card, item)
        self.m_AssetScroller.Layout()
        self.m_AssetScroller.FitInside()
        if reset_scroll:
            self.m_AssetScroller.Scroll(0, 0)

    def _thumbnail(self, item: PickerItem, selected: bool = False) -> wx.Bitmap:
        width, height = self.THUMBNAIL_SIZE
        bitmap = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush("#14181C"))
        dc.Clear()
        dc.SetPen(wx.Pen("#72A9C9" if selected else "#607180", width=2 if selected else 1))
        dc.SetBrush(wx.Brush("#3C596D" if selected else "#25313B"))
        dc.DrawRoundedRectangle(3, 3, width - 6, height - 6, 8)
        if item.preview_text:
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush("#496B81" if selected else "#354B5A"))
            dc.DrawRoundedRectangle(9, 8, width - 18, 37, 8)
            icon_box = (16, 14, 22, 25) if item.icon_id else None
            if icon_box:
                self._draw_icon(dc, item.icon_id, icon_box, "#FFFFFF")
            text_left = 45 if item.icon_id else 17
            self._draw_fitted_text(
                dc,
                item.preview_text,
                (text_left, 10, width - text_left - 17, 33),
                "#FFFFFF",
            )
        elif item.icon_id:
            self._draw_icon(dc, item.icon_id, (17, 10, 39, 39), "#FFFFFF")
            self._draw_fitted_text(
                dc,
                item.title,
                (66, 10, width - 82, 39),
                "#FFFFFF",
                align="left",
            )
        else:
            self._draw_fitted_text(
                dc,
                item.title,
                (18, 10, width - 36, 39),
                "#FFFFFF",
                align="left",
            )
        self._draw_fitted_text(
            dc,
            item.category,
            (16, 51, width - 32, 18),
            "#E0E8ED",
            align="left",
            bold=False,
        )
        dc.SelectObject(wx.NullBitmap)
        return bitmap

    @staticmethod
    def _draw_fitted_text(dc, text, bounds, colour, align="center", bold=True):
        x, y, width, height = bounds
        point_size = 11
        while point_size > 7:
            font = wx.Font(
                point_size,
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL,
            )
            dc.SetFont(font)
            text_width, text_height = dc.GetTextExtent(text)
            if text_width <= width and text_height <= height:
                break
            point_size -= 1
        dc.SetTextForeground(colour)
        if align == "left":
            text_x = x
        elif align == "right":
            text_x = x + max(0, width - text_width)
        else:
            text_x = x + max(0, (width - text_width) // 2)
        dc.DrawText(text, text_x, y + max(0, (height - text_height) // 2))

    @staticmethod
    def _draw_icon(dc, icon_id, bounds, colour):
        if icon_id not in ICON_BY_ID:
            return
        x, y, width, height = bounds
        vectors = render_builtin_icon(icon_id, 1.0)
        minimum, maximum = polygon_bounds(vectors.polygons)
        natural_width = max(0.001, maximum.x - minimum.x)
        natural_height = max(0.001, maximum.y - minimum.y)
        scale = min(width / natural_width, height / natural_height)
        centre_x = (minimum.x + maximum.x) / 2.0
        centre_y = (minimum.y + maximum.y) / 2.0
        target_x = x + width / 2.0
        target_y = y + height / 2.0
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(colour))
        for polygon in vectors.polygons:
            points = [
                wx.Point(
                    round(target_x + (point.x - centre_x) * scale),
                    round(target_y + (point.y - centre_y) * scale),
                )
                for point in polygon
            ]
            if len(points) >= 3:
                dc.DrawPolygon(points)

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
    """Compact vertical asset browser with search and category filtering."""

    THUMBNAIL_SIZE = (480, 48)

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

        self.m_AssetList = wx.ListCtrl(
            self,
            style=(
                wx.LC_REPORT
                | wx.LC_NO_HEADER
                | wx.LC_SINGLE_SEL
                | wx.BORDER_THEME
            ),
        )
        self.m_AssetList.SetBackgroundColour("#14181C")
        root.Add(self.m_AssetList, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(560, 380))

        self.m_SearchCtrl.Bind(wx.EVT_TEXT, self._on_filter_changed)
        self.m_CategoryChoice.Bind(wx.EVT_CHOICE, self._on_filter_changed)
        self.m_AssetList.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selected)
        self.m_AssetList.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activated)
        self._rebuild()
        self.m_SearchCtrl.SetFocus()

    @property
    def selected_id(self) -> str:
        return self._selected_id

    def _on_filter_changed(self, event):
        self._rebuild()
        event.Skip()

    def _on_selected(self, event):
        index = event.GetIndex()
        if 0 <= index < len(self._visible_items):
            self._selected_id = self._visible_items[index].asset_id
        event.Skip()

    def _on_activated(self, event):
        self._on_selected(event)
        self.EndModal(wx.ID_OK)

    def _rebuild(self):
        query = self.m_SearchCtrl.GetValue()
        category = self.m_CategoryChoice.GetStringSelection() or "All"
        self._visible_items = filter_picker_items(self._all_items, query, category)
        self.m_AssetList.ClearAll()
        self.m_AssetList.InsertColumn(0, "Asset")
        self.m_AssetList.SetColumnWidth(0, self.THUMBNAIL_SIZE[0] + 4)
        image_list = wx.ImageList(*self.THUMBNAIL_SIZE)
        selected_index = -1
        for index, item in enumerate(self._visible_items):
            image_index = image_list.Add(self._thumbnail(item))
            self.m_AssetList.InsertItem(index, "", image_index)
            if item.asset_id == self._selected_id:
                selected_index = index
        self.m_AssetList.AssignImageList(image_list, wx.IMAGE_LIST_SMALL)
        self._image_list = image_list
        if selected_index >= 0:
            self.m_AssetList.SetItemState(
                selected_index,
                wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
            )
        if self._visible_items:
            self.m_AssetList.EnsureVisible(0)

    def _thumbnail(self, item: PickerItem) -> wx.Bitmap:
        width, height = self.THUMBNAIL_SIZE
        bitmap = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush("#14181C"))
        dc.Clear()
        dc.SetPen(wx.Pen("#607180", width=1))
        dc.SetBrush(wx.Brush("#25313B"))
        dc.DrawRoundedRectangle(3, 3, width - 6, height - 6, 8)
        if item.preview_text:
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush("#3C596D"))
            dc.DrawRoundedRectangle(9, 7, 302, height - 14, 10)
            icon_box = (18, 13, 24, height - 26) if item.icon_id else None
            if icon_box:
                self._draw_icon(dc, item.icon_id, icon_box, "#FFFFFF")
            text_left = 50 if item.icon_id else 17
            self._draw_fitted_text(
                dc,
                item.preview_text,
                (text_left, 9, 300 - text_left, height - 18),
                "#FFFFFF",
            )
        elif item.icon_id:
            self._draw_icon(dc, item.icon_id, (18, 10, 30, height - 20), "#FFFFFF")
            self._draw_fitted_text(
                dc,
                item.title,
                (62, 7, 245, height - 14),
                "#FFFFFF",
                align="left",
            )
        else:
            self._draw_fitted_text(
                dc,
                item.title,
                (18, 7, 289, height - 14),
                "#FFFFFF",
                align="left",
            )
        self._draw_fitted_text(
            dc,
            item.category,
            (327, 7, width - 345, height - 14),
            "#C8D0D6",
            align="right",
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

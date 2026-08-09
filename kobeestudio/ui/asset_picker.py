"""Searchable visual pickers for Kobee Studio labels and symbols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

import wx

from ..core.icon_catalog import BUILTIN_ICONS, LABEL_PRESETS, render_symbol
from ..core.shape_geometry import polygon_bounds
from ..core.svg_symbols import format_symbol_reference, parse_symbol_reference
from .theme import apply_native_theme, is_dark_mode
from .themed_controls import ThemedActionButton, ThemedChoice, ThemedTextField


@dataclass(frozen=True)
class PickerItem:
    asset_id: str
    title: str
    category: str
    icon_id: str = ""
    preview_text: str = ""
    source: str = "Bundled"
    variant: str = "default"

    @property
    def search_text(self) -> str:
        return "{} {} {} {} {}".format(self.title, self.category, self.asset_id, self.source, self.variant).lower()


def _symbol_source(symbol) -> str:
    if symbol.source == "bundle":
        return "Bundled"
    return "This project" if symbol.scope == "project" else "My library"


def _label_source(label) -> str:
    if getattr(label, "source", "bundle") == "bundle":
        return "Bundled"
    return "This project" if getattr(label, "scope", "global") == "project" else "My library"


def label_picker_items(catalog=None) -> Tuple[PickerItem, ...]:
    if catalog is not None:
        return (PickerItem("", "Custom text", "Custom", source="Bundled"),) + tuple(
            PickerItem(
                label.preset_id,
                label.text,
                label.category,
                format_symbol_reference(label.symbol_id, label.symbol_variant)
                if label.symbol_id
                else "",
                label.text,
                _label_source(label),
                label.symbol_variant,
            )
            for label in catalog.labels
        )
    return (PickerItem("", "Custom text", "Custom", source="Bundled"),) + tuple(
        PickerItem(
            preset.preset_id,
            preset.text,
            preset.category,
            preset.icon_id,
            preset.text,
            "Bundled",
        )
        for preset in LABEL_PRESETS
    )


def icon_picker_items(catalog=None) -> Tuple[PickerItem, ...]:
    if catalog is not None:
        return (PickerItem("", "No symbol", "None", source="Bundled"),) + tuple(
            PickerItem(
                format_symbol_reference(symbol.asset_id, symbol.variant),
                symbol.name,
                symbol.category,
                format_symbol_reference(symbol.asset_id, symbol.variant),
                "",
                _symbol_source(symbol),
                symbol.variant,
            )
            for symbol in catalog.symbols
        )
    return (PickerItem("", "No symbol", "None", source="Bundled"),) + tuple(
        PickerItem(icon.asset_id, icon.name, icon.category, icon.asset_id, source="Bundled")
        for icon in BUILTIN_ICONS
    )


def filter_picker_items(
    items: Iterable[PickerItem], query: str = "", category: str = "All", source: str = "All sources", variant: str = "All variants"
) -> Tuple[PickerItem, ...]:
    words = tuple(word for word in query.lower().split() if word)
    return tuple(
        item
        for item in items
        if (category == "All" or item.category == category)
        and (source == "All sources" or item.source == source)
        and (variant == "All variants" or item.variant == variant)
        and all(word in item.search_text for word in words)
    )


def _picker_palette():
    """Shared neutral palette for the in-editor Kobee libraries."""
    dark = is_dark_mode(wx)
    values = {
        "window": (27, 26, 24) if dark else (239, 239, 237),
        "surface": (39, 37, 34) if dark else (248, 248, 246),
        "card": (47, 44, 40) if dark else (255, 255, 253),
        "border": (76, 71, 63) if dark else (217, 216, 211),
        "text": (245, 242, 236) if dark else (34, 33, 30),
        "muted": (181, 175, 165) if dark else (113, 108, 100),
        "accent": (235, 177, 20),
    }
    return {key: wx.Colour(*value) for key, value in values.items()}


class AssetPickerDialog(wx.Dialog):
    """Searchable, multi-column visual browser for labels and symbols."""

    THUMBNAIL_SIZE = (160, 64)

    def __init__(
        self, parent, title: str, items: Iterable[PickerItem], selected_id: str = "", symbol_catalog=None,
        one_variant_per_family: bool = False,
    ):
        super(AssetPickerDialog, self).__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=wx.Size(720, 520),
        )
        self._all_items = tuple(items)
        self._selected_id = selected_id
        self._symbol_catalog = symbol_catalog
        self._one_variant_per_family = bool(one_variant_per_family)
        self._cards = {}
        self._category_headers = []
        palette = _picker_palette()
        self.SetBackgroundColour(palette["window"])

        root = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label=title)
        heading_font = heading.GetFont().Bold()
        heading_font.SetPointSize(heading_font.GetPointSize() + 3)
        heading.SetFont(heading_font)
        heading.SetForegroundColour(palette["text"])
        header.Add(heading)
        helper = wx.StaticText(self, label="Search the Kobee library, then choose an item to keep editing in place.")
        helper.SetForegroundColour(palette["muted"])
        header.Add(helper, 0, wx.TOP, 3)
        root.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.m_SearchCtrl = ThemedTextField(self)
        self.m_SearchCtrl.SetDescriptiveText("Search names and categories…")
        categories = ("All",) + tuple(sorted({item.category for item in self._all_items}))
        self.m_CategoryChoice = ThemedChoice(self, choices=categories)
        self.m_CategoryChoice.SetSelection(0)
        filters.Add(self.m_SearchCtrl, 1, wx.RIGHT, 8)
        filters.Add(self.m_CategoryChoice, 0)
        root.Add(filters, 0, wx.EXPAND | wx.ALL, 12)

        facets = wx.BoxSizer(wx.HORIZONTAL)
        facets.Add(wx.StaticText(self, label="Source"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        sources = ("All sources",) + tuple(
            source for source in ("Bundled", "My library", "This project")
            if any(item.source == source for item in self._all_items)
        )
        self.m_SourceChoice = ThemedChoice(self, choices=sources)
        self.m_SourceChoice.SetSelection(0)
        self.m_SourceChoice.SetMinSize(wx.Size(142, 30))
        facets.Add(self.m_SourceChoice, 0, wx.RIGHT, 16)
        facets.Add(wx.StaticText(self, label="Variant"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        variant_values = tuple(sorted({item.variant for item in self._all_items if item.variant}))
        variants = variant_values if self._one_variant_per_family else ("All variants",) + variant_values
        self.m_VariantChoice = ThemedChoice(self, choices=variants)
        if self._one_variant_per_family:
            selected_variant = "default"
            if selected_id and "@@" in selected_id:
                selected_variant = selected_id.rsplit("@@", 1)[-1]
            self.m_VariantChoice.SetStringSelection(selected_variant)
            if not self.m_VariantChoice.GetStringSelection():
                self.m_VariantChoice.SetSelection(0)
        else:
            self.m_VariantChoice.SetSelection(0)
        self.m_VariantChoice.SetMinSize(wx.Size(142, 30))
        facets.Add(self.m_VariantChoice, 0)
        root.Add(facets, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.m_AssetScroller = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.BORDER_NONE)
        self.m_AssetScroller.SetBackgroundColour(palette["window"])
        self.m_AssetScroller.SetScrollRate(0, 14)
        if hasattr(self.m_AssetScroller, "ShowScrollbars"):
            never = getattr(wx, "SHOW_SB_NEVER", 0)
            # The library is still wheel/trackpad scrollable. Hiding the
            # native rail avoids a bright Cocoa scrollbar in dark mode.
            self.m_AssetScroller.ShowScrollbars(never, never)
        # wx's wrapping and grid sizers both compress fixed-size BitmapButtons
        # on Cocoa when the scroll viewport changes. This content panel owns
        # the card coordinates explicitly, keeping every 214 × 92 thumbnail
        # in a stable cell.
        self.m_AssetContent = wx.Panel(self.m_AssetScroller)
        self.m_AssetContent.SetBackgroundColour(palette["window"])
        self._grid_columns = 3
        self.m_AssetScroller.Bind(wx.EVT_SIZE, self._on_scroller_size)
        root.Add(self.m_AssetScroller, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.m_ResultHint = wx.StaticText(self, label="")
        self.m_ResultHint.SetForegroundColour(palette["muted"])
        buttons.Add(self.m_ResultHint, 0, wx.ALIGN_CENTER_VERTICAL)
        buttons.AddStretchSpacer(1)
        buttons.Add(ThemedActionButton(self, "Cancel", lambda: self.EndModal(wx.ID_CANCEL)), 0, wx.RIGHT, 8)
        buttons.Add(ThemedActionButton(self, "Use selection", lambda: self.EndModal(wx.ID_OK), primary=True), 0)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(root)
        self.SetMinSize(wx.Size(560, 380))

        self.m_SearchCtrl.Bind(wx.EVT_TEXT, self._on_filter_changed)
        self.m_CategoryChoice.Bind(wx.EVT_CHOICE, self._on_filter_changed)
        self.m_SourceChoice.Bind(wx.EVT_CHOICE, self._on_filter_changed)
        self.m_VariantChoice.Bind(wx.EVT_CHOICE, self._on_filter_changed)
        self._create_cards()
        self._apply_filter()
        apply_native_theme(self, wx, palette)
        self.m_SearchCtrl.SetFocus()

    @property
    def selected_id(self) -> str:
        return self._selected_id

    def _on_filter_changed(self, event):
        self._apply_filter()
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

    def _create_cards(self):
        for item in self._all_items:
            selected = item.asset_id == self._selected_id
            card = wx.BitmapButton(
                self.m_AssetContent,
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
            self._cards[item.asset_id] = (card, item)

    def _apply_filter(self, reset_scroll=True):
        query = self.m_SearchCtrl.GetValue()
        category = self.m_CategoryChoice.GetStringSelection() or "All"
        source = self.m_SourceChoice.GetStringSelection() or "All sources"
        variant = self.m_VariantChoice.GetStringSelection() or "All variants"
        # In symbol mode the Variant selector never has an "all" option, so
        # this filter yields exactly one card per family for the chosen style.
        visible_items = filter_picker_items(self._all_items, query, category, source, variant)
        visible_ids = {item.asset_id for item in visible_items}
        for asset_id, (card, item) in self._cards.items():
            card.Show(asset_id in visible_ids)
        self.m_ResultHint.SetLabel(
            "{} result{}{}".format(
                len(visible_ids), "" if len(visible_ids) == 1 else "s",
                " · scroll to browse" if len(visible_ids) > 9 else "",
            )
        )
        self._relayout_cards()
        if reset_scroll:
            self.m_AssetScroller.Scroll(0, 0)

    def _on_scroller_size(self, event):
        # Defer until the sizer receives its final Cocoa client width.
        wx.CallAfter(self._relayout_cards)
        event.Skip()

    def _relayout_cards(self):
        if not self or self.IsBeingDeleted():
            return
        width = self.m_AssetScroller.GetClientSize().width
        card_width, card_height = self.THUMBNAIL_SIZE
        gap = 8
        columns = 4 if width >= 4 * (card_width + gap) else 3 if width >= 3 * (card_width + gap) else 2
        self._grid_columns = columns
        visible_items = [item for _card, item in self._cards.values() if _card.IsShown()]
        grid_width = columns * card_width + (columns - 1) * gap
        left = max(4, (width - grid_width) // 2)
        for header in self._category_headers:
            header.Destroy()
        self._category_headers = []
        by_category = {}
        for item in visible_items:
            by_category.setdefault(item.category, []).append(item)
        y = 4
        palette = _picker_palette()
        for category in sorted(by_category, key=str.casefold):
            heading = wx.StaticText(self.m_AssetContent, label=category.upper())
            heading.SetForegroundColour(palette["muted"])
            heading.SetPosition(wx.Point(left, y))
            heading.SetSize(wx.Size(grid_width, 20))
            self._category_headers.append(heading)
            y += 23
            for index, item in enumerate(by_category[category]):
                card, _item = self._cards[item.asset_id]
                row, column = divmod(index, columns)
                card.SetPosition(wx.Point(left + column * (card_width + gap), y + row * (card_height + gap)))
                card.SetSize(wx.Size(card_width, card_height))
            rows = (len(by_category[category]) + columns - 1) // columns
            y += rows * card_height + max(0, rows - 1) * gap + 12
        content_height = max(self.m_AssetScroller.GetClientSize().height, y)
        content_size = wx.Size(max(width, grid_width + 8), content_height)
        # Do not put this explicitly positioned panel in a sizer. Cocoa then
        # shrinks it back to the viewport and silently clips all later cards.
        self.m_AssetContent.SetMinSize(content_size)
        self.m_AssetContent.SetSize(content_size)
        self.m_AssetScroller.SetVirtualSize(content_size)

    def _thumbnail(self, item: PickerItem, selected: bool = False) -> wx.Bitmap:
        palette = _picker_palette()
        width, height = self.THUMBNAIL_SIZE
        bitmap = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush(palette["window"]))
        dc.Clear()
        dc.SetPen(wx.Pen(palette["accent"] if selected else palette["border"], width=2 if selected else 1))
        dc.SetBrush(wx.Brush(palette["card"] if selected else palette["surface"]))
        dc.DrawRoundedRectangle(3, 3, width - 6, height - 6, 10)
        if item.icon_id:
            # White artwork is correct against the dark picker, but disappears
            # entirely on the light surface. Draw symbols in the same
            # foreground colour as their title instead.
            self._draw_icon(dc, item.icon_id, (12, 12, 34, 34), palette["text"], self._symbol_catalog)
            self._draw_fitted_text(
                dc,
                item.title,
                (55, 10, width - 66, 40),
                palette["text"],
                align="left",
            )
        else:
            self._draw_fitted_text(
                dc,
                item.title,
                (14, 10, width - 28, 40),
                palette["text"],
                align="left",
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
    def _draw_icon(dc, icon_id, bounds, colour, catalog=None):
        x, y, width, height = bounds
        try:
            if catalog is not None:
                polygons, size = catalog.render_reference(icon_id, 1.0)
            else:
                asset_id, variant = parse_symbol_reference(icon_id)
                vectors = render_symbol(asset_id, 1.0, variant)
                polygons, size = vectors.polygons, vectors.size
        except (OSError, ValueError):
            # A hidden bundled symbol must not make its linked quick label
            # disappear.  The legacy geometry is a safe thumbnail fallback;
            # custom hidden assets deliberately remain icon-less here.
            try:
                asset_id, variant = parse_symbol_reference(icon_id)
                if not asset_id.startswith("builtin."):
                    return
                vectors = render_symbol(asset_id, 1.0, variant)
                polygons, size = vectors.polygons, vectors.size
            except (OSError, ValueError):
                return
        minimum, maximum = polygon_bounds(polygons)
        natural_width = max(0.001, maximum.x - minimum.x)
        natural_height = max(0.001, maximum.y - minimum.y)
        scale = min(width / natural_width, height / natural_height)
        centre_x = (minimum.x + maximum.x) / 2.0
        centre_y = (minimum.y + maximum.y) / 2.0
        target_x = x + width / 2.0
        target_y = y + height / 2.0
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(colour))
        for polygon in polygons:
            points = [
                wx.Point(
                    round(target_x + (point.x - centre_x) * scale),
                    round(target_y + (point.y - centre_y) * scale),
                )
                for point in polygon
            ]
            if len(points) >= 3:
                dc.DrawPolygon(points)

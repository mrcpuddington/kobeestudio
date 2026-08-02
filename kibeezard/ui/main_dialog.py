"""Kobee Studio presentation built on the retained base dialog layout."""

from __future__ import annotations

import traceback

import wx

from .base.dialog import Dialog as UpstreamDialog

from ..core.composition import DocumentStyle, Padding, ShapeStyle, TypographyStyle
from ..core.icon_catalog import BUILTIN_ICONS, LABEL_PRESETS, PRESET_BY_ID
from ..core.pin_header import PinHeaderSpec
from ..core.studio_artwork import TextVectorizer, render_header_artwork, render_label_artwork
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


LAYER_LABELS = {
    FRONT_SILKSCREEN: "Front Silkscreen (F.SilkS)",
    BOTTOM_SILKSCREEN: "Bottom Silkscreen (B.SilkS)",
    FRONT_COPPER: "Front Copper (F.Cu)",
    BOTTOM_COPPER: "Bottom Copper (B.Cu)",
    FRONT_MASK: "Front Solder Mask (F.Mask)",
    BOTTOM_MASK: "Bottom Solder Mask (B.Mask)",
}
LABEL_TO_LAYER = {label: layer for layer, label in LAYER_LABELS.items()}
LAYER_ORDER = (
    FRONT_SILKSCREEN,
    BOTTOM_SILKSCREEN,
    FRONT_COPPER,
    BOTTOM_COPPER,
    FRONT_MASK,
    BOTTOM_MASK,
)
LAYER_SELECTOR_LABELS = (
    "Front Silk",
    "Bottom Silk",
    "Front Copper",
    "Bottom Copper",
    "Front Mask",
    "Bottom Mask",
)
PIN_SIDE_TO_LABEL_SIDE = {
    "Top": "below",
    "Bottom": "above",
    "Left": "right",
    "Right": "left",
}

LABEL_SHAPE_LABELS = {
    "No container": None,
    "Rectangle": "rectangle",
    "Rounded rectangle": "rounded_rectangle",
    "Pill": "pill",
    "Independent ends": "custom_ends",
    "Pointer": "pointer",
    "Flag": "flag",
    "Tab": "tab",
    "Chamfer": "chamfer",
    "Hexagon": "hexagon",
}
HEADER_SHAPE_LABELS = dict(LABEL_SHAPE_LABELS)
del HEADER_SHAPE_LABELS["No container"]
del HEADER_SHAPE_LABELS["Independent ends"]
header_shapes = list(HEADER_SHAPE_LABELS.items())
header_shapes.insert(3, ("Independent long edges", "custom_long_edges"))
HEADER_SHAPE_LABELS = dict(header_shapes)
VARIANT_LABELS = ("Inverted fill", "Outline")
CAP_LABELS = ("Square", "Rounded", "Chamfered", "Point", "Notch")
HEADER_CAP_LABELS = ("Square", "Rounded")
OPENING_LABELS = {
    "None": "none",
    "Continuous plug opening": "continuous",
    "Individual pin openings": "individual",
}
PRESET_LABELS = {"Custom label": None}
PRESET_LABELS.update({preset.display_name: preset for preset in LABEL_PRESETS})
PRESET_ID_TO_LABEL = {preset.preset_id: preset.display_name for preset in LABEL_PRESETS}
ICON_LABELS = {"No icon": ""}
ICON_LABELS.update({icon.name: icon.asset_id for icon in BUILTIN_ICONS})
ICON_ID_TO_LABEL = {asset_id: label for label, asset_id in ICON_LABELS.items()}
ICON_POSITION_LABELS = {
    "Left of text": "left",
    "Right of text": "right",
    "Icon only": "only",
}
STUDIO_DIMENSIONS_VERSION = 2
DEFAULT_LABEL_DIMENSIONS = {
    "HeightCtrl": 1.2,
    "PaddingTopCtrl": 0.5,
    "PaddingLeftCtrl": 1.2,
    "PaddingRightCtrl": 1.2,
    "PaddingBottomCtrl": 0.5,
}
STUDIO_DEFAULTS = {
    "StudioModeChoice": "Label",
    "ShapeChoice": "Rounded rectangle",
    "ShapeVariantChoice": "Inverted fill",
    "BorderThicknessCtrl": 0.2,
    "CornerRadiusCtrl": 0.6,
    "FeatureSizeCtrl": 0.75,
    "ShapeDirectionChoice": "Right",
    "StartCapChoice": "Square",
    "EndCapChoice": "Rounded",
    "PresetLabelChoice": "Custom label",
    "IconChoice": "No icon",
    "IconPositionChoice": "Left of text",
    "IconHeightCtrl": 0.0,
    "IconGapCtrl": 0.3,
    "HeaderPinCountCtrl": 4,
    "HeaderOrientationChoice": "Horizontal",
    "HeaderPin1Choice": "Start",
    "HeaderPinSideChoice": "Top",
    "HeaderPadClearanceCtrl": 2.0,
    "HeaderOpeningChoice": "None",
    "HeaderOpeningEndPaddingCtrl": 0.0,
    "HeaderLeadingPaddingCtrl": 1.27,
    "HeaderTrailingPaddingCtrl": 1.27,
    "HeaderLabelPaddingCtrl": 0.3,
    "HeaderPin1MarkerCheckbox": True,
}


class MainDialog(UpstreamDialog):
    """Preserve the proven KiBuzzard UI with explicit PCB layer choices."""

    config_defaults = dict(UpstreamDialog.config_defaults)
    config_defaults.update(
        {
            "HeightCtrl": "1.2",
            "PaddingTopCtrl": "0.5",
            "PaddingLeftCtrl": "1.2",
            "PaddingRightCtrl": "1.2",
            "PaddingBottomCtrl": "0.5",
        }
    )

    def __init__(self, parent, config, buzzard, func):
        self._loaded_output_layer = FRONT_SILKSCREEN
        self._loaded_studio_settings = dict(STUDIO_DEFAULTS)
        self._studio_controls_ready = False
        self._applying_label_preset = False
        self.artwork = None
        self.stroke_polys = []
        self.guide_polys = []
        super(MainDialog, self).__init__(parent, config, buzzard, func)
        self.SetTitle("Kobee Studio")
        self._build_studio_controls()
        self._build_layer_selector()
        self._studio_controls_ready = True
        self._apply_studio_settings(self._loaded_studio_settings)
        self._hide_legacy_cap_controls()
        self.m_PaddingLabel.SetLabel("Padding (mm):")
        self.m_LayerComboBox1.SetLabel("Output layer:")
        self.m_LayerComboBox.Clear()
        self.m_LayerComboBox.AppendItems(list(LAYER_LABELS.values()))
        self.set_output_layer(self._loaded_output_layer)
        self.m_LayerComboBox.Bind(wx.EVT_COMBOBOX, self._on_layer_changed)
        self.m_LayerComboBox.Hide()
        self.m_LayerComboBox1.Hide()
        # Reuse the generated preview label.  Adding a new root-sizer item and
        # fitting the dialog again was the first source of the macOS reflow.
        self.m_PreviewLabel.SetLabel("Preview:   Kobee Studio {}".format(__version__))
        self.m_PreviewPanel.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._update_mode_ui(refit=False)
        self._stabilise_dialog_layout()

    def _build_studio_controls(self):
        root_sizer = self.GetSizer()

        panel = wx.Panel(self)
        box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Label style"), wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 6, 4, 6)
        grid.AddGrowableCol(1)
        grid.AddGrowableCol(3)
        grid.AddGrowableCol(5)

        self.m_StudioModeChoice = wx.Choice(panel, choices=("Label", "2.54 mm Pin Header"))
        self.m_ShapeChoice = wx.Choice(panel, choices=tuple(LABEL_SHAPE_LABELS.keys()))
        self.m_ShapeVariantChoice = wx.Choice(panel, choices=VARIANT_LABELS)
        self.m_BorderThicknessCtrl = self._double_control(panel, 0.0, 10.0, 0.2, 0.05, 2)
        self.m_CornerRadiusCtrl = self._double_control(panel, 0.0, 100.0, 0.6, 0.1, 2)
        self.m_FeatureSizeCtrl = self._double_control(panel, 0.0, 100.0, 0.75, 0.1, 2)
        self.m_ShapeDirectionChoice = wx.Choice(panel, choices=("Left", "Right"))
        self.m_StartCapChoice = wx.Choice(panel, choices=CAP_LABELS)
        self.m_EndCapChoice = wx.Choice(panel, choices=CAP_LABELS)

        self._add_control(grid, panel, "Tool:", self.m_StudioModeChoice)
        self._add_control(grid, panel, "Shape:", self.m_ShapeChoice)
        self._add_control(grid, panel, "Appearance:", self.m_ShapeVariantChoice)
        self.m_BorderThicknessLabel = self._add_control(
            grid, panel, "Border:", self.m_BorderThicknessCtrl
        )
        self.m_CornerRadiusLabel = self._add_control(
            grid, panel, "Radius:", self.m_CornerRadiusCtrl
        )
        self.m_FeatureSizeLabel = self._add_control(
            grid, panel, "Feature size:", self.m_FeatureSizeCtrl
        )
        self.m_ShapeDirectionLabel = self._add_control(
            grid, panel, "Direction:", self.m_ShapeDirectionChoice
        )
        self.m_StartCapLabel = self._add_control(grid, panel, "Left end:", self.m_StartCapChoice)
        self.m_EndCapLabel = self._add_control(grid, panel, "Right end:", self.m_EndCapChoice)
        box.Add(grid, 1, wx.EXPAND | wx.ALL, 5)

        asset_grid = wx.FlexGridSizer(0, 6, 4, 6)
        asset_grid.AddGrowableCol(1)
        asset_grid.AddGrowableCol(3)
        asset_grid.AddGrowableCol(5)
        self.m_PresetLabelChoice = wx.Choice(panel, choices=tuple(PRESET_LABELS.keys()))
        self.m_IconChoice = wx.Choice(panel, choices=tuple(ICON_LABELS.keys()))
        self.m_PresetLabelChoice.Hide()
        self.m_IconChoice.Hide()
        self.m_PresetPickerButton = wx.Button(panel, label="Choose quick label…")
        self.m_IconPickerButton = wx.Button(panel, label="Choose symbol…")
        self.m_IconPositionChoice = wx.Choice(panel, choices=tuple(ICON_POSITION_LABELS.keys()))
        self.m_IconHeightCtrl = self._double_control(panel, 0.0, 20.0, 0.0, 0.1, 2)
        self.m_IconGapCtrl = self._double_control(panel, 0.0, 20.0, 0.3, 0.1, 2)
        self._add_control(asset_grid, panel, "Quick labels:", self.m_PresetPickerButton)
        self._add_control(asset_grid, panel, "Symbols:", self.m_IconPickerButton)
        self.m_IconPositionLabel = self._add_control(
            asset_grid, panel, "Position:", self.m_IconPositionChoice
        )
        self.m_IconHeightLabel = self._add_control(
            asset_grid, panel, "Icon height (mm):", self.m_IconHeightCtrl
        )
        self.m_IconGapLabel = self._add_control(
            asset_grid, panel, "Icon gap (mm):", self.m_IconGapCtrl
        )
        self.m_IconHeightCtrl.SetToolTip("0 matches the current text height; otherwise this is millimetres.")
        self.m_IconGapCtrl.SetToolTip("Space between the icon and text in millimetres.")
        self.m_FeatureSizeCtrl.SetToolTip(
            "Controls the depth of the point, notch, tab, chamfer, or hexagon end."
        )
        box.Add(asset_grid, 0, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(box)
        root_sizer.Insert(2, panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.m_StudioPanel = panel

        header_panel = wx.Panel(self)
        header_box = wx.StaticBoxSizer(wx.StaticBox(header_panel, label="2.54 mm header block"), wx.VERTICAL)
        header_grid = wx.GridSizer(0, 4, 4, 8)
        self.m_HeaderPinCountCtrl = wx.SpinCtrl(header_panel, min=1, max=40, initial=4)
        self.m_HeaderOrientationChoice = wx.Choice(header_panel, choices=("Horizontal", "Vertical"))
        self.m_HeaderPin1Choice = wx.Choice(header_panel, choices=("Start", "End"))
        self.m_HeaderPinSideChoice = wx.Choice(header_panel, choices=("Top", "Bottom"))
        self.m_HeaderPadClearanceCtrl = self._double_control(header_panel, 0.1, 100.0, 2.0, 0.1, 2)
        self.m_HeaderOpeningChoice = wx.Choice(header_panel, choices=tuple(OPENING_LABELS.keys()))
        self.m_HeaderOpeningEndPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 0.0, 0.1, 2)
        self.m_HeaderLabelPaddingCtrl = self._double_control(header_panel, 0.0, 20.0, 0.3, 0.1, 2)
        self.m_HeaderLeadingPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 1.27, 0.1, 2)
        self.m_HeaderTrailingPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 1.27, 0.1, 2)
        self.m_HeaderFillLabelsButton = wx.Button(header_panel, label="Fill labels 1…N")
        self.m_HeaderPin1MarkerCheckbox = wx.CheckBox(header_panel, label="Pin 1 marker")
        self.m_HeaderPin1MarkerCheckbox.SetValue(True)

        for label, control in (
            ("Pins", self.m_HeaderPinCountCtrl),
            ("Orientation", self.m_HeaderOrientationChoice),
            ("Pin 1 end", self.m_HeaderPin1Choice),
            ("Pins on", self.m_HeaderPinSideChoice),
            ("Opening", self.m_HeaderOpeningChoice),
            ("Pin / opening width (mm)", self.m_HeaderPadClearanceCtrl),
            ("Opening end pad (mm)", self.m_HeaderOpeningEndPaddingCtrl),
            ("Gap + outer pad (mm)", self.m_HeaderLabelPaddingCtrl),
            ("Pin 1 end pad (mm)", self.m_HeaderLeadingPaddingCtrl),
            ("Far end pad (mm)", self.m_HeaderTrailingPaddingCtrl),
        ):
            self._add_vertical_control(header_grid, header_panel, label, control)
        self.m_HeaderPadClearanceCtrl.SetToolTip(
            "Reserved connector width; also the cut width when an opening is enabled."
        )
        self.m_HeaderOpeningEndPaddingCtrl.SetToolTip(
            "Extend a continuous opening this far beyond the first and last pin."
        )
        self.m_HeaderLabelPaddingCtrl.SetToolTip(
            "Used before the pin area, between the pins and labels, and after the aligned labels."
        )
        header_box.Add(header_grid, 1, wx.EXPAND | wx.ALL, 5)
        help_row = wx.BoxSizer(wx.HORIZONTAL)
        help_row.Add(
            wx.StaticText(header_panel, label="Enter one label per pin."),
            1,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        help_row.Add(self.m_HeaderPin1MarkerCheckbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        help_row.Add(self.m_HeaderFillLabelsButton, 0)
        header_box.Add(help_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        header_panel.SetSizer(header_box)
        root_sizer.Insert(3, header_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.m_HeaderPanel = header_panel
        # Header mode has its own label padding, so the ordinary four-sided
        # padding grid and its dividers can disappear and return as one unit.
        self._ordinary_padding_items = (
            root_sizer.GetItem(5),
            root_sizer.GetItem(6),
            root_sizer.GetItem(7),
        )

        self._studio_controls = {
            "StudioModeChoice": self.m_StudioModeChoice,
            "ShapeChoice": self.m_ShapeChoice,
            "ShapeVariantChoice": self.m_ShapeVariantChoice,
            "BorderThicknessCtrl": self.m_BorderThicknessCtrl,
            "CornerRadiusCtrl": self.m_CornerRadiusCtrl,
            "FeatureSizeCtrl": self.m_FeatureSizeCtrl,
            "ShapeDirectionChoice": self.m_ShapeDirectionChoice,
            "StartCapChoice": self.m_StartCapChoice,
            "EndCapChoice": self.m_EndCapChoice,
            "PresetLabelChoice": self.m_PresetLabelChoice,
            "IconChoice": self.m_IconChoice,
            "IconPositionChoice": self.m_IconPositionChoice,
            "IconHeightCtrl": self.m_IconHeightCtrl,
            "IconGapCtrl": self.m_IconGapCtrl,
            "HeaderPinCountCtrl": self.m_HeaderPinCountCtrl,
            "HeaderOrientationChoice": self.m_HeaderOrientationChoice,
            "HeaderPin1Choice": self.m_HeaderPin1Choice,
            "HeaderPinSideChoice": self.m_HeaderPinSideChoice,
            "HeaderPadClearanceCtrl": self.m_HeaderPadClearanceCtrl,
            "HeaderOpeningChoice": self.m_HeaderOpeningChoice,
            "HeaderOpeningEndPaddingCtrl": self.m_HeaderOpeningEndPaddingCtrl,
            "HeaderLeadingPaddingCtrl": self.m_HeaderLeadingPaddingCtrl,
            "HeaderTrailingPaddingCtrl": self.m_HeaderTrailingPaddingCtrl,
            "HeaderLabelPaddingCtrl": self.m_HeaderLabelPaddingCtrl,
            "HeaderPin1MarkerCheckbox": self.m_HeaderPin1MarkerCheckbox,
        }
        self.m_StudioModeChoice.Bind(wx.EVT_CHOICE, self._on_mode_changed)
        self.m_HeaderOrientationChoice.Bind(wx.EVT_CHOICE, self._on_header_orientation_changed)
        self.m_HeaderOpeningChoice.Bind(wx.EVT_CHOICE, self._on_header_opening_changed)
        self.m_ShapeChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_ShapeVariantChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_StartCapChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_EndCapChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_PresetPickerButton.Bind(wx.EVT_BUTTON, self._open_label_picker)
        self.m_IconPickerButton.Bind(wx.EVT_BUTTON, self._open_icon_picker)
        self.m_IconPositionChoice.Bind(wx.EVT_CHOICE, self._on_icon_changed)
        self.m_MultiLineText.Bind(wx.EVT_TEXT, self._on_label_text_edited)
        self.m_HeaderFillLabelsButton.Bind(wx.EVT_BUTTON, self._fill_header_labels)

    def _build_layer_selector(self):
        self.m_LayerSelector = wx.RadioBox(
            self,
            label="Output layer",
            choices=LAYER_SELECTOR_LABELS,
            majorDimension=6,
            style=wx.RA_SPECIFY_COLS,
        )
        self.m_LayerSelector.SetToolTip(
            "Choose the one KiCad layer that will receive this artwork."
        )
        self.GetSizer().Insert(0, self.m_LayerSelector, 0, wx.EXPAND | wx.ALL, 10)
        self.m_LayerSelector.Bind(wx.EVT_RADIOBOX, self._on_layer_changed)

    @staticmethod
    def _double_control(parent, minimum, maximum, initial, increment, digits):
        control = wx.SpinCtrlDouble(
            parent,
            value=str(initial),
            min=minimum,
            max=maximum,
            initial=initial,
            inc=increment,
        )
        control.SetDigits(digits)
        return control

    @staticmethod
    def _add_control(sizer, parent, label, control):
        label_control = wx.StaticText(parent, label=label)
        sizer.Add(label_control, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
        sizer.Add(control, 1, wx.EXPAND)
        return label_control

    @staticmethod
    def _add_vertical_control(sizer, parent, label, control):
        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(wx.StaticText(parent, label=label), 0, wx.BOTTOM, 1)
        column.Add(control, 0, wx.EXPAND)
        sizer.Add(column, 1, wx.EXPAND)

    def _hide_legacy_cap_controls(self):
        for control in (
            self.m_CapLeftLabel,
            self.m_CapLeftChoice,
            self.m_CapRightLabel,
            self.m_CapRightChoice,
        ):
            control.Hide()

    def _apply_studio_settings(self, settings):
        if not self._studio_controls_ready:
            return
        # Orientation must be applied before the side list is rebuilt.
        ordered_keys = ("HeaderOrientationChoice",) + tuple(
            key for key in self._studio_controls if key != "HeaderOrientationChoice"
        )
        for key in ordered_keys:
            control = self._studio_controls[key]
            value = settings.get(key, STUDIO_DEFAULTS[key])
            if key == "ShapeChoice":
                header_mode = (
                    self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header"
                )
                self._sync_shape_choices(header_mode)
                if value == "Plain text":
                    value = "No container" if not header_mode else "Rectangle"
                if header_mode and value == "Independent ends":
                    value = "Independent long edges"
                elif not header_mode and value == "Independent long edges":
                    value = "Independent ends"
            if isinstance(control, wx.Choice):
                if not control.SetStringSelection(str(value)) and control.GetCount():
                    control.SetSelection(0)
                if key == "HeaderOrientationChoice":
                    self._sync_header_sides(str(settings.get("HeaderPinSideChoice", "Top")))
            else:
                control.SetValue(value)
        self._update_asset_button_labels()

    def _sync_header_sides(self, requested=None):
        orientation = self.m_HeaderOrientationChoice.GetStringSelection()
        choices = ("Top", "Bottom") if orientation == "Horizontal" else ("Left", "Right")
        current = requested or self.m_HeaderPinSideChoice.GetStringSelection()
        self.m_HeaderPinSideChoice.Clear()
        self.m_HeaderPinSideChoice.AppendItems(choices)
        if not self.m_HeaderPinSideChoice.SetStringSelection(current):
            self.m_HeaderPinSideChoice.SetSelection(0)

    def _on_mode_changed(self, event):
        self._update_mode_ui(refit=True)
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_header_orientation_changed(self, event):
        self._sync_header_sides()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_header_opening_changed(self, event):
        self._update_opening_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_shape_changed(self, event):
        self._update_shape_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_preset_changed(self, event):
        preset = PRESET_LABELS.get(self.m_PresetLabelChoice.GetStringSelection())
        if preset is not None:
            self._applying_label_preset = True
            try:
                self.m_MultiLineText.SetValue(preset.text)
            finally:
                self._applying_label_preset = False
            self.m_IconChoice.SetStringSelection(
                ICON_ID_TO_LABEL.get(preset.icon_id, "No icon")
            )
            self._update_icon_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _open_label_picker(self, event):
        selected = PRESET_LABELS.get(self.m_PresetLabelChoice.GetStringSelection())
        dialog = AssetPickerDialog(
            self,
            "Choose a quick label",
            label_picker_items(),
            selected.preset_id if selected is not None else "",
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                preset = PRESET_BY_ID.get(dialog.selected_id)
                self.m_PresetLabelChoice.SetStringSelection(
                    PRESET_ID_TO_LABEL.get(dialog.selected_id, "Custom label")
                )
                if preset is not None:
                    self._applying_label_preset = True
                    try:
                        self.m_MultiLineText.SetValue(preset.text)
                    finally:
                        self._applying_label_preset = False
                    self.m_IconChoice.SetStringSelection(
                        ICON_ID_TO_LABEL.get(preset.icon_id, "No icon")
                    )
                self._update_icon_ui()
                self.ReGenerateFlag(event)
                self.ReGeneratePreview()
        finally:
            dialog.Destroy()

    def _open_icon_picker(self, event):
        current_id = ICON_LABELS.get(self.m_IconChoice.GetStringSelection(), "")
        dialog = AssetPickerDialog(
            self,
            "Choose a symbol",
            icon_picker_items(),
            current_id,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self.m_IconChoice.SetStringSelection(
                    ICON_ID_TO_LABEL.get(dialog.selected_id, "No icon")
                )
                self._update_icon_ui()
                self.ReGenerateFlag(event)
                self.ReGeneratePreview()
        finally:
            dialog.Destroy()

    def _on_icon_changed(self, event):
        self._update_icon_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_label_text_edited(self, event):
        if (
            self._studio_controls_ready
            and not self._applying_label_preset
            and self.m_StudioModeChoice.GetStringSelection() == "Label"
        ):
            self.m_PresetLabelChoice.SetStringSelection("Custom label")
            self._update_asset_button_labels()
        event.Skip()

    def _update_opening_ui(self):
        mode = OPENING_LABELS.get(self.m_HeaderOpeningChoice.GetStringSelection(), "none")
        if mode == "none" and self.output_layer in (FRONT_COPPER, BOTTOM_COPPER):
            self.m_HeaderOpeningChoice.SetStringSelection("Continuous plug opening")
            mode = "continuous"
        # The connector width still controls the reserved pin/plug envelope
        # when no artwork opening is cut.
        self.m_HeaderPadClearanceCtrl.Enable(True)
        self.m_HeaderOpeningEndPaddingCtrl.Enable(mode == "continuous")

    def _update_shape_ui(self):
        header_mode = self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header"
        custom = self.m_ShapeChoice.GetStringSelection() in (
            "Independent ends",
            "Independent long edges",
        )
        self._sync_cap_choices(header_mode)
        for control in (
            self.m_StartCapChoice,
            self.m_EndCapChoice,
            self.m_StartCapLabel,
            self.m_EndCapLabel,
        ):
            control.Show(custom)
        self.m_StartCapLabel.SetLabel("Pin-side edge:" if header_mode else "Left end:")
        self.m_EndCapLabel.SetLabel("Label-side edge:" if header_mode else "Right end:")
        shape = self.m_ShapeChoice.GetStringSelection()
        feature_labels = {
            "Pointer": "Point depth:",
            "Flag": "Point / notch depth:",
            "Tab": "Tab size:",
            "Chamfer": "Chamfer size:",
            "Hexagon": "End depth:",
        }
        uses_feature = shape in feature_labels
        self.m_FeatureSizeLabel.SetLabel(feature_labels.get(shape, "Feature size:"))
        self.m_FeatureSizeLabel.Show(uses_feature)
        self.m_FeatureSizeCtrl.Show(uses_feature)
        uses_direction = shape in ("Pointer", "Flag")
        self.m_ShapeDirectionLabel.Show(uses_direction)
        self.m_ShapeDirectionChoice.Show(uses_direction)
        uses_border = self.m_ShapeVariantChoice.GetStringSelection() == "Outline"
        self.m_BorderThicknessLabel.Show(uses_border)
        self.m_BorderThicknessCtrl.Show(uses_border)
        uses_radius = shape == "Rounded rectangle" or (
            header_mode
            and shape == "Independent long edges"
            and (
                self.m_StartCapChoice.GetStringSelection() == "Rounded"
                or self.m_EndCapChoice.GetStringSelection() == "Rounded"
            )
        )
        self.m_CornerRadiusLabel.Show(uses_radius)
        self.m_CornerRadiusCtrl.Show(uses_radius)
        self.m_StudioPanel.Layout()

    def _sync_cap_choices(self, header_mode):
        choices = HEADER_CAP_LABELS if header_mode else CAP_LABELS
        for control in (self.m_StartCapChoice, self.m_EndCapChoice):
            current = control.GetStringSelection()
            if tuple(control.GetStrings()) != choices:
                control.Clear()
                control.AppendItems(choices)
            if not control.SetStringSelection(current):
                control.SetStringSelection("Square")

    def _update_icon_ui(self):
        header_mode = self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header"
        icon_id = ICON_LABELS.get(self.m_IconChoice.GetStringSelection(), "")
        icon_only = self.m_IconPositionChoice.GetStringSelection() == "Icon only"
        self.m_PresetLabelChoice.Enable(not header_mode)
        self.m_IconChoice.Enable(not header_mode)
        self.m_PresetPickerButton.Enable(not header_mode)
        self.m_IconPickerButton.Enable(not header_mode)
        show_icon_options = not header_mode and bool(icon_id)
        show_icon_gap = show_icon_options and not icon_only
        for control in (
            self.m_IconPositionLabel,
            self.m_IconPositionChoice,
            self.m_IconHeightLabel,
            self.m_IconHeightCtrl,
        ):
            control.Show(show_icon_options)
        self.m_IconGapLabel.Show(show_icon_gap)
        self.m_IconGapCtrl.Show(show_icon_gap)
        self._update_asset_button_labels()
        self.m_StudioPanel.Layout()

    def _update_asset_button_labels(self):
        if not hasattr(self, "m_PresetPickerButton"):
            return
        preset = PRESET_LABELS.get(self.m_PresetLabelChoice.GetStringSelection())
        self.m_PresetPickerButton.SetLabel(
            "{}  ▾".format(preset.text) if preset is not None else "Choose quick label…"
        )
        icon_label = self.m_IconChoice.GetStringSelection()
        self.m_IconPickerButton.SetLabel(
            "{}  ▾".format(icon_label)
            if icon_label and icon_label != "No icon"
            else "Choose symbol…"
        )

    def _sync_shape_choices(self, header_mode):
        choices = HEADER_SHAPE_LABELS if header_mode else LABEL_SHAPE_LABELS
        current = self.m_ShapeChoice.GetStringSelection()
        if current == "Independent ends" and header_mode:
            current = "Independent long edges"
        elif current == "Independent long edges" and not header_mode:
            current = "Independent ends"
        elif current == "Plain text":
            current = "Rectangle" if header_mode else "No container"
        self.m_ShapeChoice.Clear()
        self.m_ShapeChoice.AppendItems(tuple(choices.keys()))
        if not self.m_ShapeChoice.SetStringSelection(current):
            self.m_ShapeChoice.SetStringSelection("Rounded rectangle")

    def _selected_shape(self):
        choices = (
            HEADER_SHAPE_LABELS
            if self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header"
            else LABEL_SHAPE_LABELS
        )
        return choices[self.m_ShapeChoice.GetStringSelection()]

    def _fill_header_labels(self, event):
        count = self.m_HeaderPinCountCtrl.GetValue()
        self.m_MultiLineText.SetValue("\n".join(str(index + 1) for index in range(count)))
        self.ReGenerateFlag(event)

    def _update_mode_ui(self, refit=True):
        header_mode = self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header"
        self._sync_shape_choices(header_mode)
        self._sync_cap_choices(header_mode)
        self.m_HeaderPanel.Show(header_mode)
        for item in self._ordinary_padding_items:
            item.Show(not header_mode)
        self.textLabel.SetLabel("Pin labels (one per line):" if header_mode else "Text:")
        self.m_WidthCtrl.Enable(not header_mode)
        self.m_WidthLabel.Enable(not header_mode)
        self.m_WidthUnits.Enable(not header_mode)
        self.m_AlignmentChoice.Enable(not header_mode)
        self.m_AlignmentLabel.Enable(not header_mode)
        self._update_opening_ui()
        self._update_shape_ui()
        self._update_icon_ui()
        if header_mode and not self.m_MultiLineText.GetValue().strip():
            self._fill_header_labels(wx.CommandEvent())
        if refit:
            self.SetMinSize(wx.DefaultSize)
            self.Fit()
            self.GetSizer().SetSizeHints(self)
            self.Layout()

    def _stabilise_dialog_layout(self):
        """Reserve space for the settings section on macOS.

        The legacy generated layout assigns weight 20 to both the text editor
        and preview.  KiCad 10's Cocoa wx build also caches their large initial
        sizes in the nested sizer items, allowing them to push fixed controls
        below the modal dialog.  Give both live areas explicit stable sizes so
        the settings always retain their required space.
        """
        root_sizer = self.GetSizer()
        text_group = root_sizer.GetItem(1)
        preview_group = root_sizer.GetItem(2)
        text_group.SetProportion(0)
        preview_group.SetProportion(0)

        # wx caches the original child size in SizerItem.  Changing only the
        # window min-size leaves that cached value untouched, which is why the
        # preview still occupied hundreds of pixels after the first fix.
        text_item = text_group.GetSizer().GetItem(1)
        preview_item = preview_group.GetSizer().GetItem(1)
        text_item.SetMinSize(wx.Size(1, 78))
        preview_item.SetMinSize(wx.Size(1, 118))

        # This happens once, after all controls are present—not while typing.
        self.SetMinSize(wx.DefaultSize)
        self.Fit()
        root_sizer.SetSizeHints(self)
        self.Layout()

    def _normalise_layer(self, value):
        return value if value in LAYER_LABELS else FRONT_SILKSCREEN

    def set_output_layer(self, layer):
        layer = self._normalise_layer(layer)
        self.m_LayerComboBox.SetStringSelection(LAYER_LABELS[layer])
        if hasattr(self, "m_LayerSelector"):
            self.m_LayerSelector.SetSelection(LAYER_ORDER.index(layer))

    @property
    def output_layer(self):
        if hasattr(self, "m_LayerSelector"):
            selection = self.m_LayerSelector.GetSelection()
            if 0 <= selection < len(LAYER_ORDER):
                return LAYER_ORDER[selection]
        return LABEL_TO_LAYER.get(self.m_LayerComboBox.GetValue(), FRONT_SILKSCREEN)

    def _on_layer_changed(self, event):
        if (
            self.output_layer in (FRONT_COPPER, BOTTOM_COPPER)
            and OPENING_LABELS.get(self.m_HeaderOpeningChoice.GetStringSelection(), "none") == "none"
        ):
            self.m_HeaderOpeningChoice.SetStringSelection("Continuous plug opening")
            self._update_opening_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def LoadSettings(self, params):
        params = dict(params)
        # Before Studio dimensions were versioned, the inherited padding
        # controls could contain KiBuzzard source-font units or early 0.3-dev
        # test values such as 3.2.  Neither is a sensible millimetre default.
        # Reset the local saved configuration once; placed footprints retain
        # their own embedded dimensions when edited.
        try:
            dimensions_version = int(params.get("StudioDimensionsVersion", 0) or 0)
        except (TypeError, ValueError):
            dimensions_version = 0
        if not params.get("_LoadedFootprintSettings") and dimensions_version < STUDIO_DIMENSIONS_VERSION:
            params.update(DEFAULT_LABEL_DIMENSIONS)
        # 0.3.0-dev briefly stored the side occupied by the labels.  The UI now
        # asks the much clearer question "Pins on", while the pure layout model
        # continues to receive the opposite label side.
        if "HeaderPinSideChoice" not in params and "HeaderLabelSideChoice" in params:
            params["HeaderPinSideChoice"] = {
                "Above": "Bottom",
                "Below": "Top",
                "Left": "Right",
                "Right": "Left",
            }.get(str(params["HeaderLabelSideChoice"]), "Top")
        if (
            params.get("_LoadedFootprintSettings")
            and params.get("StudioModeChoice") == "2.54 mm Pin Header"
            and "HeaderOpeningChoice" not in params
        ):
            params["HeaderOpeningChoice"] = "Continuous plug opening"
        for key in STUDIO_DEFAULTS:
            if key in params:
                self._loaded_studio_settings[key] = params[key]
        if "ShapeChoice" not in params and params.get("_LoadedFootprintSettings"):
            left = params.get("CapLeftChoice", "")
            right = params.get("CapRightChoice", "")
            if left == "(" and right == ")":
                self._loaded_studio_settings["ShapeChoice"] = "Pill"
            elif left or right:
                self._loaded_studio_settings["ShapeChoice"] = "Independent ends"
                self._loaded_studio_settings["StartCapChoice"] = "Rounded" if left == "(" else "Square"
                self._loaded_studio_settings["EndCapChoice"] = "Rounded" if right == ")" else "Square"
            else:
                self._loaded_studio_settings["ShapeChoice"] = "No container"
        self._loaded_output_layer = self._normalise_layer(params.get("LayerComboBox", FRONT_SILKSCREEN))
        params["LayerComboBox"] = LAYER_LABELS.get(
            self._loaded_output_layer,
            LAYER_LABELS[FRONT_SILKSCREEN],
        )
        result = super(MainDialog, self).LoadSettings(params)
        if self._studio_controls_ready:
            self._apply_studio_settings(self._loaded_studio_settings)
            self._update_mode_ui(refit=False)
        return result

    def CurrentSettings(self):
        settings = super(MainDialog, self).CurrentSettings()
        settings["LayerComboBox"] = self.output_layer
        settings["StudioDimensionsVersion"] = STUDIO_DIMENSIONS_VERSION
        if self._studio_controls_ready:
            for key, control in self._studio_controls.items():
                if isinstance(control, wx.Choice):
                    settings[key] = control.GetStringSelection()
                else:
                    settings[key] = control.GetValue()
        return settings

    def ReGeneratePreview(self, event=None):
        if not self._studio_controls_ready:
            return super(MainDialog, self).ReGeneratePreview(event)

        self.polys = []
        self.stroke_polys = []
        self.guide_polys = []
        self.artwork = None
        self.error = None
        self.buzzard.layer = self.output_layer
        try:
            style = self._document_style()
            vectorizer = TextVectorizer(self.buzzard)
            text = self.m_MultiLineText.GetValue()
            if self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header":
                labels = tuple(text.splitlines())
                pin_count = self.m_HeaderPinCountCtrl.GetValue()
                if len(labels) != pin_count:
                    raise ValueError("Enter exactly {} pin labels, one per line".format(pin_count))
                if any(not label.strip() for label in labels):
                    raise ValueError("Every pin needs a label")
                spec = PinHeaderSpec(
                    pin_count=pin_count,
                    pin_labels=labels,
                    orientation=self.m_HeaderOrientationChoice.GetStringSelection().lower(),
                    pin1_end=self.m_HeaderPin1Choice.GetStringSelection().lower(),
                    label_side=PIN_SIDE_TO_LABEL_SIDE[
                        self.m_HeaderPinSideChoice.GetStringSelection()
                    ],
                    pad_clearance_mm=self.m_HeaderPadClearanceCtrl.GetValue(),
                    opening_mode=OPENING_LABELS[
                        self.m_HeaderOpeningChoice.GetStringSelection()
                    ],
                    opening_end_padding_mm=self.m_HeaderOpeningEndPaddingCtrl.GetValue(),
                    leading_padding_mm=self.m_HeaderLeadingPaddingCtrl.GetValue(),
                    trailing_padding_mm=self.m_HeaderTrailingPaddingCtrl.GetValue(),
                    label_padding_mm=self.m_HeaderLabelPaddingCtrl.GetValue(),
                    pin1_marker=self.m_HeaderPin1MarkerCheckbox.IsChecked(),
                    shape=self._selected_shape() or "rectangle",
                    output_layer=self.output_layer,
                    style=style,
                )
                self.artwork = render_header_artwork(vectorizer, spec)
            else:
                icon_id = ICON_LABELS.get(self.m_IconChoice.GetStringSelection(), "")
                if not text and not icon_id:
                    self.RePaint()
                    return
                if len(text) > 512:
                    raise ValueError("Text input is too long")
                self.artwork = render_label_artwork(
                    vectorizer,
                    text,
                    style,
                    self.output_layer,
                    shape=self._selected_shape(),
                    minimum_width_mm=self.m_WidthCtrl.GetValue(),
                    inline_format=self.m_inlineFormatTextbox.IsChecked(),
                    lineover_style=self.m_lineoverStyleChoice.GetStringSelection(),
                    lineover_thickness=self.m_lineoverThicknessCtrl.GetValue(),
                    icon_id=icon_id,
                    icon_position=ICON_POSITION_LABELS[
                        self.m_IconPositionChoice.GetStringSelection()
                    ],
                    icon_height_mm=self.m_IconHeightCtrl.GetValue(),
                    icon_gap_mm=self.m_IconGapCtrl.GetValue(),
                )
            self.polys = list(self.artwork.filled_polygons)
            self.stroke_polys = list(self.artwork.strokes)
            self.guide_polys = list(self.artwork.guides)
        except Exception as error:
            traceback.print_exc()
            self.error = str(error) or "Error generating artwork"
        self.RePaint()

    def _document_style(self):
        shape_name = self.m_ShapeChoice.GetStringSelection()
        variant = self.m_ShapeVariantChoice.GetStringSelection()
        filled = variant == "Inverted fill" and shape_name != "No container"
        border = max(0.01, self.m_BorderThicknessCtrl.GetValue())
        if self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header":
            padding = Padding.symmetric(self.m_HeaderLabelPaddingCtrl.GetValue(), self.m_HeaderLabelPaddingCtrl.GetValue())
        else:
            padding = Padding(
                top=self.m_PaddingTopCtrl.GetValue(),
                right=self.m_PaddingRightCtrl.GetValue(),
                bottom=self.m_PaddingBottomCtrl.GetValue(),
                left=self.m_PaddingLeftCtrl.GetValue(),
            )
        return DocumentStyle(
            typography=TypographyStyle(
                font_name=self.m_FontComboBox.GetValue(),
                height_mm=max(0.01, self.m_HeightCtrl.GetValue()),
                width_mm=max(0.0, self.m_WidthCtrl.GetValue()),
                line_spacing=max(0.1, self.m_LineSpacingCtrl.GetValue()),
                alignment=self.m_AlignmentChoice.GetStringSelection().lower(),
            ),
            shape=ShapeStyle(
                padding=padding,
                border_thickness_mm=0.0 if filled else border,
                corner_radius_mm=self.m_CornerRadiusCtrl.GetValue(),
                feature_size_mm=self.m_FeatureSizeCtrl.GetValue(),
                filled=filled,
                inverted=filled,
                direction=self.m_ShapeDirectionChoice.GetStringSelection().lower(),
                start_cap=self.m_StartCapChoice.GetStringSelection().lower(),
                end_cap=self.m_EndCapChoice.GetStringSelection().lower(),
            ),
        )

    def RePaint(self, event=None):
        """Repaint live preview without asking macOS to re-layout the dialog.

        The inherited implementation calls ``self.Layout()``.  With KiCad's
        macOS wx build that progressively reallocates the two proportional
        preview sizers while text is being typed, eventually pushing the
        settings controls below the visible window.  Only the preview pixels
        change during normal editing, so invalidate that panel alone.
        """
        # ``Update`` forces a synchronous paint from inside KiCad's text
        # change event and can crash the macOS wx event loop.  Refresh queues
        # a normal paint safely after the event returns.
        self.m_PreviewPanel.Refresh(False)

    def advancedModeChange(self, event):
        """Keep the one deliberate layout pass needed when controls toggle."""
        super(MainDialog, self).advancedModeChange(event)
        self.SetMinSize(wx.DefaultSize)
        self.Fit()
        self.GetSizer().SetSizeHints(self)

    def OnPaint(self, event):
        dc = wx.AutoBufferedPaintDC(self.m_PreviewPanel)
        dc.SetBackground(wx.Brush(self.m_PreviewPanel.GetBackgroundColour()))
        dc.Clear()

        try:
            if self.error is not None:
                self._draw_preview_message(dc, self.error, "#CC0000")
                return

            size_x, size_y = self.m_PreviewPanel.GetClientSize()
            bottom_side = is_bottom(self.output_layer)
            caption_height = 20 if bottom_side else 0
            artwork_height = max(0, size_y - caption_height)
            source_polygons = list(self.polys)
            source_polygons.extend(stroke.points for stroke in self.stroke_polys)
            source_polygons.extend(self.guide_polys)
            polygons = preview_polygons(source_polygons, self.output_layer)
            polygons = fit_preview_polygons(polygons, size_x, artwork_height)
            if not polygons:
                return

            filled_count = len(self.polys)
            stroke_count = len(self.stroke_polys)
            filled_polygons = polygons[:filled_count]
            stroke_polygons = polygons[filled_count:filled_count + stroke_count]
            guide_polygons = polygons[filled_count + stroke_count:]

            dc.SetDeviceOrigin(int(size_x / 2), int(artwork_height / 2))
            dc.SetPen(wx.Pen("#000000", width=1))
            dc.SetBrush(wx.Brush("#000000"))
            if filled_polygons:
                dc.DrawPolygonList(filled_polygons)
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            for points in stroke_polygons:
                dc.SetPen(wx.Pen("#000000", width=2))
                dc.DrawLines(points + [points[0]])
            for index, points in enumerate(guide_polygons):
                colour = "#C18400" if index == 0 else "#999999"
                dc.SetPen(wx.Pen(colour, width=1, style=wx.PENSTYLE_SHORT_DASH))
                dc.DrawLines(points + [points[0]])

            if bottom_side:
                dc.SetDeviceOrigin(0, 0)
                dc.SetTextForeground("#555555")
                dc.DrawText("Bottom side — front-view mirror", 5, artwork_height + 2)
        except Exception:
            # Never let Python unwind through wx's native paint callback.  On
            # macOS that can invalidate PaintDC state and take KiCad down.
            traceback.print_exc()
            dc.SetDeviceOrigin(0, 0)
            dc.Clear()
            self._draw_preview_message(dc, "Preview unavailable", "#CC0000")

    def _draw_preview_message(self, dc, message, colour):
        dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        dc.SetTextForeground(colour)
        dc.DrawLabel(message, self.m_PreviewPanel.GetClientRect(), wx.ALIGN_LEFT | wx.ALIGN_TOP)

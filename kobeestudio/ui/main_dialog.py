"""Kobee Studio presentation built on the retained base dialog layout."""

from __future__ import annotations

import traceback

import wx

from .base.dialog import Dialog as UpstreamDialog

from ..core.composition import DocumentStyle, Padding, ShapeStyle, TypographyStyle
from ..core.icon_catalog import BUILTIN_ICONS, LABEL_PRESETS, PRESET_BY_ID
from ..core.machine_codes import (
    CODE128_DEFAULT_HEIGHT_MM,
    CODE128_DEFAULT_MODULE_MM,
    CODE128_MIN_HEIGHT_MM,
    CODE128_MIN_MODULE_MM,
    QR_MIN_MODULE_MM,
)
from ..core.pin_header import PinHeaderSpec, maximum_pin_label_height
from ..core.studio_artwork import (
    TextVectorizer,
    render_header_artwork,
    render_label_artwork,
    render_machine_code_artwork,
)
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
MACHINE_CODE_LABELS = {
    "QR Code": "qr",
    "Code 128 barcode": "code128",
}
QR_PRESENTATION_LABELS = {
    "Plain code": "plain",
    "Rounded frame": "rounded_frame",
    "Rounded frame + footer": "rounded_caption",
}

ICON_POSITION_LABELS = {
    "Left of text": "left",
    "Right of text": "right",
    "Icon only": "only",
}
STUDIO_DIMENSIONS_VERSION = 2
STUDIO_DEFAULTS_VERSION = 3
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
    "CornerRadiusCtrl": 0.2,
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
    "HeaderLeadingPaddingCtrl": 0.3,
    "HeaderTrailingPaddingCtrl": 0.3,
    "HeaderLabelPaddingCtrl": 0.3,
    "HeaderPinOuterPaddingCtrl": 0.3,
    "HeaderPinToLabelGapCtrl": 0.3,
    "HeaderLabelOuterPaddingCtrl": 0.3,
    "HeaderCrossSizeCtrl": 0.0,
    "HeaderPin1MarkerCheckbox": True,
    "MachineCodeTypeChoice": "QR Code",
    "MachineCodeModuleSizeCtrl": QR_MIN_MODULE_MM,
    "MachineCodeBarHeightCtrl": CODE128_DEFAULT_HEIGHT_MM,
    "MachineCodePresentationChoice": "Plain code",
    "MachineCodeCaptionCtrl": "SCAN ME",
    "MachineCodeCaptionHeightCtrl": 1.2,
    "MachineCodeFramePaddingCtrl": 0.2,
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
        self._dynamic_refit_pending = False
        self.artwork = None
        self.stroke_polys = []
        self.guide_polys = []
        super(MainDialog, self).__init__(parent, config, buzzard, func)
        self.SetTitle("Kobee Studio")
        self._build_studio_controls()
        self._build_machine_code_controls()
        self._build_layer_selector()
        self._studio_controls_ready = True
        self._apply_studio_settings(self._loaded_studio_settings)
        self._hide_legacy_cap_controls()
        self._polish_existing_controls()
        self.m_PaddingLabel.SetLabel("Container padding (mm):")
        self.m_LayerComboBox1.SetLabel("Output layer:")
        self.m_LayerComboBox.Clear()
        self.m_LayerComboBox.AppendItems(list(LAYER_LABELS.values()))
        self.set_output_layer(self._loaded_output_layer)
        self.m_LayerComboBox.Bind(wx.EVT_COMBOBOX, self._on_layer_changed)
        self.m_LayerComboBox.Hide()
        self.m_LayerComboBox1.Hide()
        # Reuse the generated preview label.  Adding a new root-sizer item and
        # fitting the dialog again was the first source of the macOS reflow.
        self.m_PreviewLabel.SetLabel("Live preview  ·  Kobee Studio {}".format(__version__))
        self.m_PreviewPanel.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._update_mode_ui(refit=False)
        self._stabilise_dialog_layout()
        # Reopening a placed icon is still an edit of its label.  Keeping the
        # text field focused avoids the surprising jump back into symbols.
        wx.CallAfter(self.m_MultiLineText.SetFocus)

    def _build_studio_controls(self):
        root_sizer = self.GetSizer()

        panel = wx.Panel(self)
        box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Design"), wx.VERTICAL)
        # Two label/control pairs per row remain legible on the 800 px-wide
        # KiCad dialog, including the independent long-edge controls.
        grid = wx.FlexGridSizer(0, 4, 4, 6)
        grid.AddGrowableCol(1)
        grid.AddGrowableCol(3)

        self.m_StudioModeChoice = wx.Choice(
            panel,
            choices=("Label", "2.54 mm Pin Header", "QR / Barcode"),
        )
        self.m_ShapeChoice = wx.Choice(panel, choices=tuple(LABEL_SHAPE_LABELS.keys()))
        self.m_ShapeVariantChoice = wx.Choice(panel, choices=VARIANT_LABELS)
        self.m_BorderThicknessCtrl = self._double_control(panel, 0.0, 10.0, 0.2, 0.05, 2)
        self.m_CornerRadiusCtrl = self._double_control(panel, 0.0, 100.0, 0.2, 0.1, 2)
        self.m_FeatureSizeCtrl = self._double_control(panel, 0.0, 100.0, 0.75, 0.1, 2)
        self.m_ShapeDirectionChoice = wx.Choice(panel, choices=("Left", "Right"))
        self.m_StartCapChoice = wx.Choice(panel, choices=CAP_LABELS)
        self.m_EndCapChoice = wx.Choice(panel, choices=CAP_LABELS)

        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_label = wx.StaticText(panel, label="Artwork type:")
        mode_row.Add(mode_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        mode_row.Add(self.m_StudioModeChoice, 1, wx.EXPAND)
        box.Add(mode_row, 0, wx.EXPAND | wx.ALL, 5)
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

        asset_grid = wx.FlexGridSizer(0, 4, 4, 6)
        asset_grid.AddGrowableCol(1)
        asset_grid.AddGrowableCol(3)
        self.m_PresetLabelChoice = wx.Choice(panel, choices=tuple(PRESET_LABELS.keys()))
        self.m_IconChoice = wx.Choice(panel, choices=tuple(ICON_LABELS.keys()))
        self.m_PresetLabelChoice.Hide()
        self.m_IconChoice.Hide()
        self.m_PresetPickerButton = wx.Button(panel, label="Choose quick label…")
        self.m_IconPickerButton = wx.Button(panel, label="Choose symbol…")
        self.m_IconPositionChoice = wx.Choice(panel, choices=tuple(ICON_POSITION_LABELS.keys()))
        self.m_IconHeightCtrl = self._double_control(panel, 0.0, 20.0, 0.0, 0.1, 2)
        self.m_IconGapCtrl = self._double_control(panel, 0.0, 20.0, 0.3, 0.1, 2)
        self._add_control(asset_grid, panel, "Text preset:", self.m_PresetPickerButton)
        self._add_control(asset_grid, panel, "Symbol:", self.m_IconPickerButton)
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
        content_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Content"), wx.VERTICAL)
        content_box.Add(asset_grid, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(content_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.m_ContentBox = content_box

        container_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Container"), wx.VERTICAL)
        container_box.Add(grid, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(container_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.m_ContainerBox = container_box
        panel.SetSizer(box)
        root_sizer.Insert(2, panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.m_StudioPanel = panel

        header_panel = wx.Panel(self)
        header_box = wx.StaticBoxSizer(wx.StaticBox(header_panel, label="Pin header layout"), wx.VERTICAL)
        header_grid = wx.GridSizer(0, 4, 4, 8)
        self.m_HeaderPinCountCtrl = wx.SpinCtrl(header_panel, min=1, max=40, initial=4)
        self.m_HeaderOrientationChoice = wx.Choice(header_panel, choices=("Horizontal", "Vertical"))
        self.m_HeaderPin1Choice = wx.Choice(header_panel, choices=("Start", "End"))
        self.m_HeaderPinSideChoice = wx.Choice(header_panel, choices=("Top", "Bottom"))
        self.m_HeaderPadClearanceCtrl = self._double_control(header_panel, 0.1, 100.0, 2.0, 0.1, 2)
        self.m_HeaderOpeningChoice = wx.Choice(header_panel, choices=tuple(OPENING_LABELS.keys()))
        self.m_HeaderOpeningEndPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 0.0, 0.1, 2)
        self.m_HeaderLabelPaddingCtrl = self._double_control(header_panel, 0.0, 20.0, 0.3, 0.1, 2)
        self.m_HeaderPinOuterPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderPinToLabelGapCtrl = self._double_control(header_panel, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderLabelOuterPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderCrossSizeCtrl = self._double_control(header_panel, 0.0, 100.0, 0.0, 0.1, 2)
        self.m_HeaderLeadingPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderTrailingPaddingCtrl = self._double_control(header_panel, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderFillLabelsButton = wx.Button(header_panel, label="Fill labels 1…N")
        self.m_HeaderPin1MarkerCheckbox = wx.CheckBox(header_panel, label="Pin 1 marker")
        self.m_HeaderPin1MarkerCheckbox.SetValue(True)

        for label, control in (
            ("Pin count", self.m_HeaderPinCountCtrl),
            ("Orientation", self.m_HeaderOrientationChoice),
            ("Pin 1 position", self.m_HeaderPin1Choice),
            ("Pins on", self.m_HeaderPinSideChoice),
            ("Artwork opening", self.m_HeaderOpeningChoice),
            ("Connector width (mm)", self.m_HeaderPadClearanceCtrl),
            ("Row start outer padding (mm)", self.m_HeaderLeadingPaddingCtrl),
            ("Row end outer padding (mm)", self.m_HeaderTrailingPaddingCtrl),
        ):
            self._add_vertical_control(header_grid, header_panel, label, control)

        header_detail_grid = wx.GridSizer(0, 4, 4, 8)
        for label, control in (
            ("Opening end extension (mm)", self.m_HeaderOpeningEndPaddingCtrl),
            ("Label row end padding (mm)", self.m_HeaderLabelPaddingCtrl),
            ("Pin-side outer padding (mm)", self.m_HeaderPinOuterPaddingCtrl),
            ("Pin-to-label gap (mm)", self.m_HeaderPinToLabelGapCtrl),
            ("Label-side outer padding (mm)", self.m_HeaderLabelOuterPaddingCtrl),
            ("Fixed rail width / height (mm)", self.m_HeaderCrossSizeCtrl),
        ):
            self._add_vertical_control(header_detail_grid, header_panel, label, control)

        self.m_HeaderPadClearanceCtrl.SetToolTip(
            "Reserved connector width; also the cut width when an opening is enabled."
        )
        self.m_HeaderOpeningEndPaddingCtrl.SetToolTip(
            "Extend a continuous opening this far beyond the first and last pin."
        )
        self.m_HeaderLabelPaddingCtrl.SetToolTip(
            "Padding past the first and last label along the pin row."
        )
        self.m_HeaderPinOuterPaddingCtrl.SetToolTip(
            "Clearance from the outside rail edge to the connector/pin envelope."
        )
        self.m_HeaderPinToLabelGapCtrl.SetToolTip(
            "Space from the connector/pin envelope to the nearest label edge."
        )
        self.m_HeaderLabelOuterPaddingCtrl.SetToolTip(
            "Clearance from the outer label edge to the rail."
        )
        self.m_HeaderCrossSizeCtrl.SetToolTip(
            "Optional total rail width (vertical header) or height (horizontal header). 0 follows content."
        )
        header_box.Add(header_grid, 0, wx.EXPAND | wx.ALL, 5)
        self.m_HeaderDetailsCheckbox = wx.CheckBox(
            header_panel, label="Show detailed spacing"
        )
        self.m_HeaderDetailsCheckbox.SetToolTip(
            "Show independent outer padding, label gap, rail size and end spacing."
        )
        header_box.Add(
            self.m_HeaderDetailsCheckbox,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            5,
        )
        header_detail_box = wx.StaticBoxSizer(
            wx.StaticBox(header_panel, label="Detailed spacing"), wx.VERTICAL
        )
        header_detail_box.Add(header_detail_grid, 0, wx.EXPAND | wx.ALL, 5)
        header_box.Add(
            header_detail_box,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            5,
        )
        self.m_HeaderDetailBox = header_detail_box
        self.m_HeaderDetailBox.GetStaticBox().Hide()
        self.m_HeaderDetailBox.ShowItems(False)
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
            "HeaderPinOuterPaddingCtrl": self.m_HeaderPinOuterPaddingCtrl,
            "HeaderPinToLabelGapCtrl": self.m_HeaderPinToLabelGapCtrl,
            "HeaderLabelOuterPaddingCtrl": self.m_HeaderLabelOuterPaddingCtrl,
            "HeaderCrossSizeCtrl": self.m_HeaderCrossSizeCtrl,
            "HeaderPin1MarkerCheckbox": self.m_HeaderPin1MarkerCheckbox,
        }
        self.m_StudioModeChoice.Bind(wx.EVT_CHOICE, self._on_mode_changed)
        self.m_HeaderOrientationChoice.Bind(wx.EVT_CHOICE, self._on_header_orientation_changed)
        self.m_HeaderOpeningChoice.Bind(wx.EVT_CHOICE, self._on_header_opening_changed)
        self.m_HeaderDetailsCheckbox.Bind(wx.EVT_CHECKBOX, self._on_header_details_changed)
        self.m_ShapeChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_ShapeVariantChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_StartCapChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_EndCapChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_PresetPickerButton.Bind(wx.EVT_BUTTON, self._open_label_picker)
        self.m_IconPickerButton.Bind(wx.EVT_BUTTON, self._open_icon_picker)
        self.m_IconPositionChoice.Bind(wx.EVT_CHOICE, self._on_icon_changed)
        self.m_MultiLineText.Bind(wx.EVT_TEXT, self._on_label_text_edited)
        self.m_HeaderFillLabelsButton.Bind(wx.EVT_BUTTON, self._fill_header_labels)

    def _build_machine_code_controls(self):
        root_sizer = self.GetSizer()
        panel = wx.Panel(self)
        box = wx.StaticBoxSizer(
            wx.StaticBox(panel, label="Machine-readable code"), wx.VERTICAL
        )
        grid = wx.FlexGridSizer(0, 4, 4, 8)
        grid.AddGrowableCol(1)
        grid.AddGrowableCol(3)

        self.m_MachineCodeTypeChoice = wx.Choice(
            panel, choices=tuple(MACHINE_CODE_LABELS.keys())
        )
        self.m_MachineCodeModuleSizeCtrl = self._double_control(
            panel, CODE128_MIN_MODULE_MM, 5.0, QR_MIN_MODULE_MM, 0.05, 2
        )
        self.m_MachineCodeBarHeightCtrl = self._double_control(
            panel,
            CODE128_MIN_HEIGHT_MM,
            100.0,
            CODE128_DEFAULT_HEIGHT_MM,
            0.5,
            1,
        )
        self.m_MachineCodePresentationChoice = wx.Choice(
            panel, choices=tuple(QR_PRESENTATION_LABELS.keys())
        )
        self.m_MachineCodeCaptionCtrl = wx.TextCtrl(panel, value="SCAN ME")
        self.m_MachineCodeCaptionCtrl.SetMaxLength(32)
        self.m_MachineCodeCaptionHeightCtrl = self._double_control(
            panel, 0.8, 10.0, 1.2, 0.1, 1
        )
        self.m_MachineCodeFramePaddingCtrl = self._double_control(
            panel, 0.0, 10.0, 0.2, 0.05, 2
        )
        self.m_MachineCodeFramePaddingCtrl.SetToolTip(
            "Extra space outside the required QR quiet zone. Zero still preserves the full quiet zone."
        )
        self._add_control(grid, panel, "Code type:", self.m_MachineCodeTypeChoice)
        self.m_MachineCodeModuleSizeLabel = self._add_control(
            grid, panel, "Module size (mm):", self.m_MachineCodeModuleSizeCtrl
        )
        self.m_MachineCodeBarHeightLabel = self._add_control(
            grid, panel, "Bar height (mm):", self.m_MachineCodeBarHeightCtrl
        )
        self.m_MachineCodePresentationLabel = self._add_control(
            grid, panel, "QR presentation:", self.m_MachineCodePresentationChoice
        )
        self.m_MachineCodeFramePaddingLabel = self._add_control(
            grid, panel, "Extra frame gap (mm):", self.m_MachineCodeFramePaddingCtrl
        )
        self.m_MachineCodeCaptionLabel = self._add_control(
            grid, panel, "Footer text:", self.m_MachineCodeCaptionCtrl
        )
        self.m_MachineCodeCaptionHeightLabel = self._add_control(
            grid, panel, "Footer height (mm):", self.m_MachineCodeCaptionHeightCtrl
        )
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 5)
        self.m_MachineCodeHelp = wx.StaticText(panel, label="")
        self.m_MachineCodeHelp.Wrap(720)
        box.Add(
            self.m_MachineCodeHelp,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            7,
        )
        panel.SetSizer(box)
        root_sizer.Insert(
            4,
            panel,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            10,
        )
        self.m_MachineCodePanel = panel
        self._studio_controls.update(
            {
                "MachineCodeTypeChoice": self.m_MachineCodeTypeChoice,
                "MachineCodeModuleSizeCtrl": self.m_MachineCodeModuleSizeCtrl,
                "MachineCodeBarHeightCtrl": self.m_MachineCodeBarHeightCtrl,
                "MachineCodePresentationChoice": self.m_MachineCodePresentationChoice,
                "MachineCodeCaptionCtrl": self.m_MachineCodeCaptionCtrl,
                "MachineCodeCaptionHeightCtrl": self.m_MachineCodeCaptionHeightCtrl,
                "MachineCodeFramePaddingCtrl": self.m_MachineCodeFramePaddingCtrl,
            }
        )
        self.m_MachineCodeTypeChoice.Bind(
            wx.EVT_CHOICE, self._on_machine_code_type_changed
        )
        self.m_MachineCodePresentationChoice.Bind(
            wx.EVT_CHOICE, self._on_machine_code_presentation_changed
        )

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

    def _polish_existing_controls(self):
        """Give inherited controls a Studio hierarchy without changing behaviour."""
        self.textLabel.SetLabel("Label text:")
        self.m_FontLabel.SetLabel("Typeface:")
        self.m_HeightLabel.SetLabel("Text height:")
        self.m_WidthLabel.SetLabel("Minimum width:")
        self.m_AlignmentLabel.SetLabel("Text alignment:")
        self.m_lineSpacingLabel.SetLabel("Line spacing:")
        self.m_PaddingLabel.SetLabel("Container padding (mm):")
        self.m_lineoverLabel.SetLabel("Overline:")
        self.m_spCharLabel.SetLabel("Insert character:")
        self.m_inlineFormatTextbox.SetLabel("Enable inline formatting")
        self.m_advancedCheckbox.SetLabel("Advanced typography")
        self.m_LayerSelector.SetLabel("Output layer")
        self.m_sdbSizerOK.SetLabel(
            "Update artwork" if self.updateFootprint is not None else "Place artwork"
        )

        self.m_StudioModeChoice.SetToolTip(
            "Choose a single label or a labelled 2.54 mm connector rail."
        )
        self.m_ShapeChoice.SetToolTip("Choose the outer container geometry.")
        self.m_ShapeVariantChoice.SetToolTip(
            "Use a solid reversed label or a stroked outline."
        )
        self.m_BorderThicknessCtrl.SetToolTip(
            "Outline stroke width in millimetres. Used only for Outline appearance."
        )
        self.m_CornerRadiusCtrl.SetToolTip("Corner radius in millimetres.")
        self.m_StartCapChoice.SetToolTip("Style for the first independent edge.")
        self.m_EndCapChoice.SetToolTip("Style for the second independent edge.")
        self.m_PresetPickerButton.SetToolTip("Browse searchable, ready-made label content.")
        self.m_IconPickerButton.SetToolTip("Browse searchable built-in PCB symbols.")
        self.m_advancedCheckbox.SetToolTip(
            "Show overline, special-character and inline-formatting controls."
        )
        self.m_WidthCtrl.SetToolTip(
            "Optional minimum container width. Leave at 0 to fit the content."
        )
        self.m_LineSpacingCtrl.SetToolTip("Spacing multiplier for multi-line label text.")

        for control, width in (
            (self.m_StudioModeChoice, 190),
            (self.m_ShapeChoice, 170),
            (self.m_ShapeVariantChoice, 140),
            (self.m_PresetPickerButton, 170),
            (self.m_IconPickerButton, 170),
        ):
            control.SetMinSize(wx.Size(width, -1))

        # The original dialog presents typography and padding as unrelated
        # grids divided by rules.  Keep the proven controls, but give them one
        # coherent section that can later absorb project-wide type settings.
        root_sizer = self.GetSizer()
        font_sizer = self.m_FontComboBox.GetContainingSizer()
        padding_sizer = self.m_PaddingTopCtrl.GetContainingSizer()
        font_index = next(
            (
                index
                for index in range(root_sizer.GetItemCount())
                if root_sizer.GetItem(index).GetSizer() is font_sizer
            ),
            -1,
        )
        if font_index >= 0 and padding_sizer is not None:
            root_sizer.Detach(font_sizer)
            root_sizer.Detach(padding_sizer)
            for divider in (self.m_staticline1, self.m_staticline11):
                root_sizer.Detach(divider)
                divider.Hide()
            typography_box = wx.StaticBoxSizer(
                wx.StaticBox(self, label="Typography & spacing"), wx.VERTICAL
            )
            typography_box.Add(font_sizer, 0, wx.EXPAND | wx.ALL, 5)
            typography_box.Add(padding_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
            root_sizer.Insert(
                font_index,
                typography_box,
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                10,
            )
            self._ordinary_padding_items = (typography_box.GetItem(1),)
            self.m_TypographyBox = typography_box

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

    def _on_header_details_changed(self, event):
        show_details = self.m_HeaderDetailsCheckbox.IsChecked()
        self.m_HeaderDetailBox.GetStaticBox().Show(show_details)
        self.m_HeaderDetailBox.ShowItems(show_details)
        self.m_HeaderPanel.Layout()
        self.SetMinSize(wx.DefaultSize)
        self.Fit()
        self.GetSizer().SetSizeHints(self)
        self.Layout()
        event.Skip()

    def _on_machine_code_type_changed(self, event):
        kind = MACHINE_CODE_LABELS.get(
            self.m_MachineCodeTypeChoice.GetStringSelection(), "qr"
        )
        if kind == "code128":
            if abs(self.m_MachineCodeModuleSizeCtrl.GetValue() - QR_MIN_MODULE_MM) < 0.0001:
                self.m_MachineCodeModuleSizeCtrl.SetValue(CODE128_DEFAULT_MODULE_MM)
            if self.m_MachineCodeBarHeightCtrl.GetValue() < CODE128_MIN_HEIGHT_MM:
                self.m_MachineCodeBarHeightCtrl.SetValue(CODE128_DEFAULT_HEIGHT_MM)
        self._update_machine_code_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_machine_code_presentation_changed(self, event):
        self._update_machine_code_ui()
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
        self._schedule_dynamic_refit()

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
        label_mode = self.m_StudioModeChoice.GetStringSelection() == "Label"
        icon_id = ICON_LABELS.get(self.m_IconChoice.GetStringSelection(), "")
        icon_only = self.m_IconPositionChoice.GetStringSelection() == "Icon only"
        self.m_PresetLabelChoice.Enable(label_mode)
        self.m_IconChoice.Enable(label_mode)
        self.m_PresetPickerButton.Enable(label_mode)
        self.m_IconPickerButton.Enable(label_mode)
        show_icon_options = label_mode and bool(icon_id)
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
        self._schedule_dynamic_refit()

    def _update_machine_code_ui(self):
        if not hasattr(self, "m_MachineCodePanel"):
            return
        kind = MACHINE_CODE_LABELS.get(
            self.m_MachineCodeTypeChoice.GetStringSelection(), "qr"
        )
        code128 = kind == "code128"
        minimum_module = CODE128_MIN_MODULE_MM if code128 else QR_MIN_MODULE_MM
        self.m_MachineCodeModuleSizeCtrl.SetRange(minimum_module, 5.0)
        if self.m_MachineCodeModuleSizeCtrl.GetValue() < minimum_module:
            self.m_MachineCodeModuleSizeCtrl.SetValue(minimum_module)
        self.m_MachineCodeBarHeightCtrl.SetRange(CODE128_MIN_HEIGHT_MM, 100.0)
        if self.m_MachineCodeBarHeightCtrl.GetValue() < CODE128_MIN_HEIGHT_MM:
            self.m_MachineCodeBarHeightCtrl.SetValue(CODE128_DEFAULT_HEIGHT_MM)

        self.m_MachineCodeBarHeightLabel.Show(code128)
        self.m_MachineCodeBarHeightCtrl.Show(code128)
        self.m_MachineCodePresentationLabel.Show(not code128)
        self.m_MachineCodePresentationChoice.Show(not code128)
        presentation = QR_PRESENTATION_LABELS.get(
            self.m_MachineCodePresentationChoice.GetStringSelection(), "plain"
        )
        framed_mode = not code128 and presentation != "plain"
        self.m_MachineCodeFramePaddingLabel.Show(framed_mode)
        self.m_MachineCodeFramePaddingCtrl.Show(framed_mode)
        caption_mode = not code128 and presentation == "rounded_caption"
        for control in (
            self.m_MachineCodeCaptionLabel,
            self.m_MachineCodeCaptionCtrl,
            self.m_MachineCodeCaptionHeightLabel,
            self.m_MachineCodeCaptionHeightCtrl,
        ):
            control.Show(caption_mode)

        if code128:
            self.m_MachineCodeHelp.SetLabel(
                "Printable ASCII, maximum 48 characters. Default 0.25 mm modules and 4.0 mm bars; "
                "minimum 0.20 mm and 3.0 mm. Check the finished board with your fabricator and scanner."
            )
        else:
            self.m_MachineCodeHelp.SetLabel(
                "UTF-8 payload, maximum 512 bytes. QR error correction M and the required four-module "
                "quiet zone are automatic. Rounded frames remain outside that protected area."
            )
        self.m_MachineCodePanel.Layout()
        self._schedule_dynamic_refit()

    def _schedule_dynamic_refit(self):
        """Grow the dialog once after dynamic controls become visible."""
        if not self._studio_controls_ready or self._dynamic_refit_pending:
            return
        self._dynamic_refit_pending = True
        wx.CallAfter(self._refit_dynamic_controls)

    def _refit_dynamic_controls(self):
        self._dynamic_refit_pending = False
        if not self:
            return
        panel_sizer = self.m_StudioPanel.GetSizer()
        self.m_StudioPanel.SetMinSize(wx.DefaultSize)
        panel_sizer.Layout()
        self.m_StudioPanel.SetMinSize(panel_sizer.CalcMin())
        root_sizer = self.GetSizer()
        root_sizer.Layout()
        needed = root_sizer.CalcMin()
        current = self.GetSize()
        target = wx.Size(max(current.width, needed.width), max(current.height, needed.height))
        if target != current:
            self.SetSize(target)
        self.SetMinSize(needed)
        self.Layout()

    @staticmethod
    def _set_picker_button(button, selected_label, empty_label, item_kind):
        """Keep selected asset names useful without letting them resize the UI."""
        selected_label = str(selected_label or "").replace("\n", " ").strip()
        if selected_label:
            visible = selected_label
            if len(visible) > 24:
                visible = visible[:23].rstrip() + "…"
            button.SetLabel("{}  ▾".format(visible))
            button.SetToolTip(
                "Selected {}: {}\nClick to browse or search.".format(
                    item_kind, selected_label
                )
            )
        else:
            button.SetLabel(empty_label)
            button.SetToolTip("Click to browse or search {}.".format(item_kind + "s"))

    def _update_asset_button_labels(self):
        if not hasattr(self, "m_PresetPickerButton"):
            return
        preset_label = self.m_PresetLabelChoice.GetStringSelection()
        self._set_picker_button(
            self.m_PresetPickerButton,
            "" if preset_label == "Custom label" else preset_label,
            "Browse text presets…",
            "text preset",
        )
        icon_label = self.m_IconChoice.GetStringSelection()
        self._set_picker_button(
            self.m_IconPickerButton,
            "" if icon_label == "No icon" else icon_label,
            "Browse symbols…",
            "symbol",
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
        selection = self.m_StudioModeChoice.GetStringSelection()
        label_mode = selection == "Label"
        header_mode = selection == "2.54 mm Pin Header"
        code_mode = selection == "QR / Barcode"
        self._sync_shape_choices(header_mode)
        if header_mode:
            height_limit = maximum_pin_label_height(2.54)
            self.m_HeightCtrl.SetRange(0.0, height_limit)
            if self.m_HeightCtrl.GetValue() > height_limit:
                self.m_HeightCtrl.SetValue(height_limit)
            self.m_HeightCtrl.SetToolTip(
                "Maximum {:.2f} mm in 2.54 mm header mode to keep adjacent pin labels separate.".format(
                    height_limit
                )
            )
        else:
            self.m_HeightCtrl.SetRange(0.0, 128.0)
            self.m_HeightCtrl.SetToolTip("Capital-letter height in millimetres.")
        self._sync_cap_choices(header_mode)
        self.m_HeaderPanel.Show(header_mode)
        self.m_MachineCodePanel.Show(code_mode)
        for group, show in (
            (self.m_ContentBox, label_mode),
            (self.m_ContainerBox, not code_mode),
            (self.m_TypographyBox, not code_mode),
        ):
            group.GetStaticBox().Show(show)
            group.ShowItems(show)
        for item in self._ordinary_padding_items:
            item.Show(label_mode)

        self.textLabel.SetLabel(
            "Pin labels (one per line):"
            if header_mode
            else "Payload:"
            if code_mode
            else "Label text:"
        )
        for control in (
            self.m_WidthCtrl,
            self.m_WidthLabel,
            self.m_WidthUnits,
            self.m_AlignmentChoice,
            self.m_AlignmentLabel,
        ):
            control.Enable(label_mode)
        self.m_advancedCheckbox.Show(not code_mode)
        if code_mode:
            self.m_lineoverPanel.Hide()
            self.m_spCharPanel.Hide()
            self.m_AdvancedDivider.Hide()
        elif self.m_advancedCheckbox.IsChecked():
            self.m_lineoverPanel.Show()
            self.m_spCharPanel.Show()
            self.m_AdvancedDivider.Show()
        else:
            self.m_lineoverPanel.Hide()
            self.m_spCharPanel.Hide()
            self.m_AdvancedDivider.Hide()

        self._update_opening_ui()
        self._update_shape_ui()
        self._update_icon_ui()
        self._update_machine_code_ui()
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
        try:
            defaults_version = int(params.get("StudioDefaultsVersion", 0) or 0)
        except (TypeError, ValueError):
            defaults_version = 0
        if not params.get("_LoadedFootprintSettings") and defaults_version < STUDIO_DEFAULTS_VERSION:
            params.update(
                {
                    "CornerRadiusCtrl": 0.2,
                    "HeaderLeadingPaddingCtrl": 0.3,
                    "HeaderTrailingPaddingCtrl": 0.3,
                    "MachineCodeModuleSizeCtrl": (
                        CODE128_DEFAULT_MODULE_MM
                        if params.get("MachineCodeTypeChoice") == "Code 128 barcode"
                        else QR_MIN_MODULE_MM
                    ),
                    "MachineCodeBarHeightCtrl": CODE128_DEFAULT_HEIGHT_MM,
                    "MachineCodeFramePaddingCtrl": 0.2,
                }
            )
        if not params.get("_LoadedFootprintSettings") and dimensions_version < STUDIO_DIMENSIONS_VERSION:
            params.update(DEFAULT_LABEL_DIMENSIONS)
        # A new invocation should begin with the everyday label tool.  Only an
        # explicitly selected, saved footprint is allowed to reopen in header mode.
        if not params.get("_LoadedFootprintSettings"):
            params["StudioModeChoice"] = "Label"
            params["PresetLabelChoice"] = "Custom label"
            params["IconChoice"] = "No icon"
            params["IconPositionChoice"] = "Left of text"
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
        settings["StudioDefaultsVersion"] = STUDIO_DEFAULTS_VERSION
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
            mode = self.m_StudioModeChoice.GetStringSelection()
            if mode == "QR / Barcode":
                kind = MACHINE_CODE_LABELS.get(
                    self.m_MachineCodeTypeChoice.GetStringSelection(), "qr"
                )
                presentation = (
                    "plain"
                    if kind == "code128"
                    else QR_PRESENTATION_LABELS.get(
                        self.m_MachineCodePresentationChoice.GetStringSelection(),
                        "plain",
                    )
                )
                self.artwork = render_machine_code_artwork(
                    payload=text,
                    kind=kind,
                    module_size_mm=self.m_MachineCodeModuleSizeCtrl.GetValue(),
                    bar_height_mm=self.m_MachineCodeBarHeightCtrl.GetValue(),
                    output_layer=self.output_layer,
                    vectorizer=vectorizer,
                    presentation=presentation,
                    caption_text=self.m_MachineCodeCaptionCtrl.GetValue(),
                    caption_height_mm=self.m_MachineCodeCaptionHeightCtrl.GetValue(),
                    frame_padding_mm=self.m_MachineCodeFramePaddingCtrl.GetValue(),
                )
            elif mode == "2.54 mm Pin Header":
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
                    pin_outer_padding_mm=self.m_HeaderPinOuterPaddingCtrl.GetValue(),
                    pin_to_label_gap_mm=self.m_HeaderPinToLabelGapCtrl.GetValue(),
                    label_outer_padding_mm=self.m_HeaderLabelOuterPaddingCtrl.GetValue(),
                    rail_cross_size_mm=self.m_HeaderCrossSizeCtrl.GetValue(),
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

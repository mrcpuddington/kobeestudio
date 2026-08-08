"""Kobee Studio presentation built on the retained base dialog layout."""

from __future__ import annotations

import traceback

import wx

from .base.dialog import Dialog as UpstreamDialog

from ..core.composition import DocumentStyle, Padding, ShapeStyle, TypographyStyle
from ..core.component_callout import (
    COMPONENT_PRESETS,
    ComponentCalloutSpec,
)
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
    render_component_callout_artwork,
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


KOBEE_STUDIO_DOCS_URL = "https://www.coreybusuttil.com/kobeestudio/docs/"


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
    "Circle": "circle",
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
del HEADER_SHAPE_LABELS["Circle"]
del HEADER_SHAPE_LABELS["Independent ends"]
header_shapes = list(HEADER_SHAPE_LABELS.items())
header_shapes.insert(3, ("Independent long edges", "custom_long_edges"))
HEADER_SHAPE_LABELS = dict(header_shapes)
COMPONENT_SHAPE_LABELS = dict(LABEL_SHAPE_LABELS)
del COMPONENT_SHAPE_LABELS["No container"]
VARIANT_LABELS = ("Inverted fill", "Outline")
CAP_LABELS = ("Square", "Rounded", "Chamfered", "Point", "Notch", "Skew /", "Skew " + chr(92))
CAP_STYLE_IDS = {"Skew /": "skew_forward", "Skew " + chr(92): "skew_back"}


def cap_style_id(value):
    """Map user-facing skew labels to stable geometry identifiers."""

    text = str(value)
    return CAP_STYLE_IDS.get(text, text.lower())
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
CONTENT_LAYOUT_LABELS = ("Single text", "Title + subtitle")
MATCH_MAIN_TYPEFACE = "Match main typeface"
COMPONENT_PRESET_LABELS = {"Custom dimensions": "custom"}
COMPONENT_PRESET_LABELS.update({item.label: item.preset_id for item in COMPONENT_PRESETS})
COMPONENT_PRESET_BY_LABEL = {item.label: item for item in COMPONENT_PRESETS}
COMPONENT_POSITION_LABELS = {
    "Left of text": "left",
    "Right of text": "right",
    "Above text": "above",
    "Below text": "below",
}
COMPONENT_CUTOUT_LABELS = {
    "Rectangle": "rectangle",
    "Rounded rectangle": "rounded_rectangle",
    "Pill / oval": "pill",
}
COMPONENT_CUTOUT_ID_TO_LABEL = {value: label for label, value in COMPONENT_CUTOUT_LABELS.items()}
# Compatibility for artwork made before the tactile-switch preset was simplified.
# Old items still reopen and render; new items use a plain rounded envelope.
COMPONENT_CUTOUT_ID_TO_LABEL["tactile_switch"] = "Rounded rectangle"
COMPONENT_ARRAY_ORIENTATION_LABELS = {
    "Vertical stack": "vertical",
    "Horizontal row": "horizontal",
}
COMPONENT_STYLE_DEFAULTS = {
    "font": "FreddySpark-Regular",
    "height_mm": 3.0,
    "alignment": "Right",
    "padding_mm": 1.0,
    "outer_radius_mm": 1.0,
    "cutout_radius_mm": 0.7,
    "component_text_gap_mm": 2.6,
}

ICON_POSITION_LABELS = {
    "Left of text": "left",
    "Right of text": "right",
    "Icon only": "only",
}
STUDIO_DIMENSIONS_VERSION = 2
STUDIO_DEFAULTS_VERSION = 7
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
    "ContentLayoutChoice": "Single text",
    "SubtitleCtrl": "",
    "SubtitleFontChoice": MATCH_MAIN_TYPEFACE,
    "SubtitleHeightCtrl": 0.8,
    "SubtitleLineSpacingCtrl": 1.2,
    "SubtitleGapCtrl": 0.25,
    "UnderlineCheckbox": False,
    "UnderlineThicknessCtrl": 0.15,
    "UnderlineGapCtrl": 0.12,
    "HeaderPinCountCtrl": 4,
    "HeaderOrientationChoice": "Vertical",
    "HeaderPin1Choice": "Start",
    "HeaderPinSideChoice": "Left",
    "HeaderPadClearanceCtrl": 2.0,
    "HeaderOpeningChoice": "Continuous plug opening",
    "HeaderOpeningEndPaddingCtrl": 0.0,
    "HeaderLeadingPaddingCtrl": 0.3,
    "HeaderTrailingPaddingCtrl": 0.3,
    "HeaderLabelPaddingCtrl": 0.3,
    "HeaderPinOuterPaddingCtrl": 0.3,
    "HeaderPinToLabelGapCtrl": 0.3,
    "HeaderLabelOuterPaddingCtrl": 0.3,
    "HeaderCrossSizeCtrl": 0.0,
    "HeaderPin1MarkerCheckbox": True,
    "ComponentPresetChoice": "0603 / 1608 metric",
    "ComponentPositionChoice": "Left of text",
    "ComponentCutoutChoice": "Rounded rectangle",
    "ComponentWidthCtrl": 2.2,
    "ComponentHeightCtrl": 1.1,
    "ComponentClearanceCtrl": 0.3,
    "ComponentCutoutRadiusCtrl": 0.2,
    "ComponentTextGapCtrl": 2.6,
    "ComponentMinWidthCtrl": 0.0,
    "ComponentMinHeightCtrl": 0.0,
    "ComponentArrayCountCtrl": 3,
    "ComponentArrayOrientationChoice": "Vertical stack",
    "ComponentArrayPitchCtrl": 5.0,
    "MachineCodeTypeChoice": "QR Code",
    "MachineCodeModuleSizeCtrl": QR_MIN_MODULE_MM,
    "MachineCodeBarHeightCtrl": CODE128_DEFAULT_HEIGHT_MM,
    "MachineCodePresentationChoice": "Plain code",
    "MachineCodeCaptionCtrl": "SCAN ME",
    "MachineCodeCaptionHeightCtrl": 1.2,
    "MachineCodeFramePaddingCtrl": 0.2,
    "MachineCodeShowContentCheckbox": False,
    "MachineCodeContentCtrl": "",
    "MachineCodeContentHeightCtrl": 0.9,
    "MachineCodeContentGapCtrl": 0.5,
}


MODE_DEFAULTS = {
    "Label": {
        "MultiLineText": "LABEL",
        "FontComboBox": "FreddySpark-Regular",
        "HeightCtrl": 1.2,
        "AlignmentChoice": "Center",
    },
    "Component Callout": {
        "MultiLineText": "COMPONENT",
        "FontComboBox": COMPONENT_STYLE_DEFAULTS["font"],
        "HeightCtrl": COMPONENT_STYLE_DEFAULTS["height_mm"],
        "AlignmentChoice": COMPONENT_STYLE_DEFAULTS["alignment"],
        "ShapeChoice": "Rounded rectangle",
        "CornerRadiusCtrl": COMPONENT_STYLE_DEFAULTS["outer_radius_mm"],
    },
    "Component Array": {
        "MultiLineText": "LED 1\nLED 2\nLED 3",
        "FontComboBox": COMPONENT_STYLE_DEFAULTS["font"],
        "HeightCtrl": COMPONENT_STYLE_DEFAULTS["height_mm"],
        "AlignmentChoice": COMPONENT_STYLE_DEFAULTS["alignment"],
        "ShapeChoice": "Rounded rectangle",
        "CornerRadiusCtrl": COMPONENT_STYLE_DEFAULTS["outer_radius_mm"],
        "ComponentArrayCountCtrl": 3,
        "ComponentArrayOrientationChoice": "Vertical stack",
    },
    "2.54 mm Pin Header": {
        "MultiLineText": "Pin 1\nPin 2\nPin 3\nPin 4",
        "HeightCtrl": 1.2,
        "AlignmentChoice": "Right",
        "HeaderPinCountCtrl": 4,
        "HeaderOrientationChoice": "Vertical",
        "HeaderPin1Choice": "Start",
        "HeaderPinSideChoice": "Left",
        "HeaderOpeningChoice": "Continuous plug opening",
        "ShapeChoice": "Rounded rectangle",
    },
    "QR / Barcode": {
        "MultiLineText": "https://github.com/mrcpuddington/kobeestudio",
        "MachineCodeTypeChoice": "QR Code",
        "MachineCodePresentationChoice": "Rounded frame + footer",
        "MachineCodeCaptionCtrl": "SCAN ME",
        "MachineCodeContentCtrl": "kobee.com.au",
    },
}


def mode_defaults(mode):
    """Return an independent, renderable first-use profile for an artwork mode."""
    settings = dict(STUDIO_DEFAULTS)
    settings.update(MODE_DEFAULTS.get(mode, MODE_DEFAULTS["Label"]))
    settings["StudioModeChoice"] = mode if mode in MODE_DEFAULTS else "Label"
    settings["PresetLabelChoice"] = "Custom label"
    settings["IconChoice"] = "No icon"
    settings["IconPositionChoice"] = "Left of text"
    settings["ContentLayoutChoice"] = "Single text"
    settings["SubtitleCtrl"] = ""
    settings["advancedCheckbox"] = False
    return settings


def _subtitle_font_name(selection, main_font):
    """Resolve the optional subtitle override to a concrete typeface."""
    return main_font if not selection or selection == MATCH_MAIN_TYPEFACE else selection


def _launch_settings(params, config_defaults):
    """Return isolated launch settings and whether this is an artwork edit."""
    incoming = dict(params)
    editing_existing = bool(incoming.get("_LoadedFootprintSettings"))
    if editing_existing:
        return incoming, True

    # Session state is intentionally ignored until named presets exist.
    # A fresh command invocation always starts from the factory label profile.
    fresh = dict(config_defaults)
    fresh["MultiLineText"] = MODE_DEFAULTS["Label"]["MultiLineText"]
    fresh["LayerComboBox"] = FRONT_SILKSCREEN
    fresh["advancedCheckbox"] = False
    return fresh, False


class MainDialog(UpstreamDialog):
    """Kobee Studio's responsive, mode-aware artwork editor."""

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

    def __init__(
        self,
        parent,
        config,
        buzzard,
        func,
        editor_session=None,
        build_label="",
    ):
        self._build_label = str(build_label or "").strip()
        self._loaded_output_layer = FRONT_SILKSCREEN
        self._loaded_studio_settings = dict(STUDIO_DEFAULTS)
        self._studio_controls_ready = False
        self._applying_label_preset = False
        self._applying_mode_defaults = False
        self._dynamic_refit_pending = False
        self._preview_pending = False
        self._updating_machine_code_content = False
        self._editing_existing_artwork = False
        self._component_defaults_applied = False
        self.artwork = None
        self.stroke_polys = []
        self.guide_polys = []
        super(MainDialog, self).__init__(
            parent, config, buzzard, func, editor_session=editor_session
        )
        # Typography is independent from container radius and padding. Reuse
        # its immutable vectors so spinner edits only rebuild cheap shape geometry.
        self._text_vectorizer = TextVectorizer(self.buzzard)
        title = "Kobee Studio"
        if self._build_label:
            title = "{} — {}".format(title, self._build_label)
        self.SetTitle(title)
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
        preview_label = "Live preview  ·  Kobee Studio {}".format(__version__)
        if self._build_label:
            preview_label = "{}  ·  {}".format(preview_label, self._build_label)
        self.m_PreviewLabel.SetLabel(preview_label)
        self.m_PreviewPanel.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._rebuild_studio_layout()
        self._bind_live_artwork_controls()
        if self._editing_existing_artwork:
            self._update_mode_ui(refit=False)
        else:
            self._apply_mode_defaults("Label", refit=False)
        self._stabilise_dialog_layout()
        # Let the modal window paint before building its first preview.
        wx.CallAfter(self._request_preview)
        # Reopening a placed icon is still an edit of its label. Keeping the
        # main field focused avoids jumping back into symbol selection.
        wx.CallAfter(self.m_MultiLineText.SetFocus)

    def _build_studio_controls(self):
        root_sizer = self.GetSizer()

        panel = wx.Panel(self)
        box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Design"), wx.VERTICAL)
        design_parent = box.GetStaticBox()
        content_box = wx.StaticBoxSizer(
            wx.StaticBox(design_parent, label="Content"), wx.VERTICAL
        )
        content_parent = content_box.GetStaticBox()
        container_box = wx.StaticBoxSizer(
            wx.StaticBox(design_parent, label="Container"), wx.VERTICAL
        )
        container_parent = container_box.GetStaticBox()
        # Two label/control pairs per row remain legible on the 800 px-wide
        # KiCad dialog, including the independent long-edge controls.
        grid = wx.FlexGridSizer(0, 4, 4, 6)
        grid.AddGrowableCol(1)
        grid.AddGrowableCol(3)

        self.m_StudioModeChoice = wx.Choice(
            design_parent,
            choices=(
                "Label",
                "Component Callout",
                "Component Array",
                "2.54 mm Pin Header",
                "QR / Barcode",
            ),
        )
        self.m_ShapeChoice = wx.Choice(container_parent, choices=tuple(LABEL_SHAPE_LABELS.keys()))
        self.m_ShapeVariantChoice = wx.Choice(container_parent, choices=VARIANT_LABELS)
        self.m_BorderThicknessCtrl = self._double_control(container_parent, 0.0, 10.0, 0.2, 0.05, 2)
        self.m_CornerRadiusCtrl = self._double_control(container_parent, 0.0, 100.0, 0.2, 0.1, 2)
        self.m_FeatureSizeCtrl = self._double_control(container_parent, 0.0, 100.0, 0.75, 0.1, 2)
        self.m_ShapeDirectionChoice = wx.Choice(container_parent, choices=("Left", "Right"))
        self.m_StartCapChoice = wx.Choice(container_parent, choices=CAP_LABELS)
        self.m_EndCapChoice = wx.Choice(container_parent, choices=CAP_LABELS)

        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_label = wx.StaticText(design_parent, label="Artwork type:")
        mode_row.Add(mode_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        mode_row.Add(self.m_StudioModeChoice, 1, wx.EXPAND)
        box.Add(mode_row, 0, wx.EXPAND | wx.ALL, 5)
        self.m_ArtworkTypeLabel = mode_label
        self.m_ArtworkTypeRow = mode_row
        self._add_control(grid, container_parent, "Shape:", self.m_ShapeChoice)
        self._add_control(grid, container_parent, "Appearance:", self.m_ShapeVariantChoice)
        self.m_BorderThicknessLabel = self._add_control(
            grid, container_parent, "Border:", self.m_BorderThicknessCtrl
        )
        self.m_CornerRadiusLabel = self._add_control(
            grid, container_parent, "Radius:", self.m_CornerRadiusCtrl
        )
        self.m_FeatureSizeLabel = self._add_control(
            grid, container_parent, "Feature size:", self.m_FeatureSizeCtrl
        )
        self.m_ShapeDirectionLabel = self._add_control(
            grid, container_parent, "Direction:", self.m_ShapeDirectionChoice
        )
        self.m_StartCapLabel = self._add_control(grid, container_parent, "Left end:", self.m_StartCapChoice)
        self.m_EndCapLabel = self._add_control(grid, container_parent, "Right end:", self.m_EndCapChoice)

        asset_grid = wx.FlexGridSizer(0, 4, 4, 6)
        asset_grid.AddGrowableCol(1)
        asset_grid.AddGrowableCol(3)
        self.m_PresetLabelChoice = wx.Choice(content_parent, choices=tuple(PRESET_LABELS.keys()))
        self.m_IconChoice = wx.Choice(content_parent, choices=tuple(ICON_LABELS.keys()))
        self.m_PresetLabelChoice.Hide()
        self.m_IconChoice.Hide()
        self.m_PresetPickerButton = wx.Button(content_parent, label="Choose quick label…")
        self.m_IconPickerButton = wx.Button(content_parent, label="Choose symbol…")
        self.m_IconPositionChoice = wx.Choice(content_parent, choices=tuple(ICON_POSITION_LABELS.keys()))
        self.m_IconHeightCtrl = self._double_control(content_parent, 0.0, 20.0, 0.0, 0.1, 2)
        self.m_IconGapCtrl = self._double_control(content_parent, 0.0, 20.0, 0.3, 0.1, 2)
        self.m_ContentLayoutChoice = wx.Choice(content_parent, choices=CONTENT_LAYOUT_LABELS)
        self.m_SubtitleCtrl = wx.TextCtrl(content_parent, value="")
        self.m_SubtitleCtrl.SetMaxLength(256)
        self.m_SubtitleFontChoice = wx.Choice(
            content_parent,
            choices=(MATCH_MAIN_TYPEFACE,) + tuple(self.m_FontComboBox.GetItems()),
        )
        self.m_SubtitleHeightCtrl = self._double_control(content_parent, 0.1, 128.0, 0.8, 0.1, 2)
        self.m_SubtitleLineSpacingCtrl = self._double_control(content_parent, 0.1, 10.0, 1.2, 0.1, 2)
        self.m_SubtitleGapCtrl = self._double_control(content_parent, 0.0, 20.0, 0.25, 0.05, 2)
        self.m_UnderlineCheckbox = wx.CheckBox(content_parent, label="Underline main text")
        self.m_UnderlineThicknessCtrl = self._double_control(content_parent, 0.05, 5.0, 0.15, 0.05, 2)
        self.m_UnderlineGapCtrl = self._double_control(content_parent, 0.0, 10.0, 0.12, 0.05, 2)
        self.m_ContentLayoutLabel = self._add_control(
            asset_grid, content_parent, "Text layout:", self.m_ContentLayoutChoice
        )
        self._add_control(asset_grid, content_parent, "Text preset:", self.m_PresetPickerButton)
        self._add_control(asset_grid, content_parent, "Symbol:", self.m_IconPickerButton)
        self.m_IconPositionLabel = self._add_control(
            asset_grid, content_parent, "Position:", self.m_IconPositionChoice
        )
        self.m_IconHeightLabel = self._add_control(
            asset_grid, content_parent, "Icon height (mm):", self.m_IconHeightCtrl
        )
        self.m_IconGapLabel = self._add_control(
            asset_grid, content_parent, "Icon gap (mm):", self.m_IconGapCtrl
        )
        self.m_SubtitleLabel = self._add_control(
            asset_grid, content_parent, "Subtitle text:", self.m_SubtitleCtrl
        )
        self.m_SubtitleFontLabel = self._add_control(
            asset_grid, content_parent, "Subtitle typeface:", self.m_SubtitleFontChoice
        )
        self.m_SubtitleHeightLabel = self._add_control(
            asset_grid, content_parent, "Subtitle height (mm):", self.m_SubtitleHeightCtrl
        )
        self.m_SubtitleLineSpacingLabel = self._add_control(
            asset_grid, content_parent, "Subtitle line spacing:", self.m_SubtitleLineSpacingCtrl
        )
        self.m_SubtitleGapLabel = self._add_control(
            asset_grid, content_parent, "Title/subtitle gap (mm):", self.m_SubtitleGapCtrl
        )
        asset_grid.Add(self.m_UnderlineCheckbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
        asset_grid.Add((0, 0), 1, wx.EXPAND)
        self.m_UnderlineThicknessLabel = self._add_control(
            asset_grid, content_parent, "Underline thickness (mm):", self.m_UnderlineThicknessCtrl
        )
        self.m_UnderlineGapLabel = self._add_control(
            asset_grid, content_parent, "Underline gap (mm):", self.m_UnderlineGapCtrl
        )
        self.m_IconHeightCtrl.SetToolTip("0 matches the current text height; otherwise this is millimetres.")
        self.m_IconGapCtrl.SetToolTip("Space between the icon and text in millimetres.")
        self.m_ContentLayoutChoice.SetToolTip(
            "Use the main text alone, or add an independently sized subtitle beneath it."
        )
        self.m_SubtitleCtrl.SetToolTip(
            "Secondary text beneath the main label. Its typeface matches the main text by default."
        )
        self.m_FeatureSizeCtrl.SetToolTip(
            "Controls the depth of the point, notch, tab, chamfer, or hexagon end."
        )
        content_box.Add(asset_grid, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(content_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.m_ContentBox = content_box

        container_box.Add(grid, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(container_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.m_ContainerBox = container_box
        panel.SetSizer(box)
        root_sizer.Insert(2, panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.m_StudioPanel = panel

        header_panel = wx.Panel(self)
        header_box = wx.StaticBoxSizer(wx.StaticBox(header_panel, label="Pin header layout"), wx.VERTICAL)
        header_parent = header_box.GetStaticBox()
        header_detail_box = wx.StaticBoxSizer(
            wx.StaticBox(header_parent, label="Detailed spacing"), wx.VERTICAL
        )
        header_detail_parent = header_detail_box.GetStaticBox()
        header_grid = wx.GridSizer(0, 4, 4, 8)
        self.m_HeaderPinCountCtrl = wx.SpinCtrl(header_parent, min=1, max=40, initial=4)
        self.m_HeaderOrientationChoice = wx.Choice(header_parent, choices=("Horizontal", "Vertical"))
        self.m_HeaderPin1Choice = wx.Choice(header_parent, choices=("Start", "End"))
        self.m_HeaderPinSideChoice = wx.Choice(header_parent, choices=("Top", "Bottom"))
        self.m_HeaderPadClearanceCtrl = self._double_control(header_parent, 0.1, 100.0, 2.0, 0.1, 2)
        self.m_HeaderOpeningChoice = wx.Choice(header_parent, choices=tuple(OPENING_LABELS.keys()))
        self.m_HeaderOpeningEndPaddingCtrl = self._double_control(header_detail_parent, 0.0, 100.0, 0.0, 0.1, 2)
        self.m_HeaderLabelPaddingCtrl = self._double_control(header_detail_parent, 0.0, 20.0, 0.3, 0.1, 2)
        self.m_HeaderPinOuterPaddingCtrl = self._double_control(header_detail_parent, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderPinToLabelGapCtrl = self._double_control(header_detail_parent, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderLabelOuterPaddingCtrl = self._double_control(header_detail_parent, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderCrossSizeCtrl = self._double_control(header_detail_parent, 0.0, 100.0, 0.0, 0.1, 2)
        self.m_HeaderLeadingPaddingCtrl = self._double_control(header_parent, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderTrailingPaddingCtrl = self._double_control(header_parent, 0.0, 100.0, 0.3, 0.1, 2)
        self.m_HeaderFillLabelsButton = wx.Button(header_parent, label="Fill labels 1…N")
        self.m_HeaderPin1MarkerCheckbox = wx.CheckBox(header_parent, label="Pin 1 marker")
        self.m_HeaderPin1MarkerCheckbox.SetValue(True)

        for label, control in (
            ("Pin count", self.m_HeaderPinCountCtrl),
            ("Orientation", self.m_HeaderOrientationChoice),
            ("Pin 1 position", self.m_HeaderPin1Choice),
            ("Pins on", self.m_HeaderPinSideChoice),
            ("Artwork opening", self.m_HeaderOpeningChoice),
            ("Connector width (mm)", self.m_HeaderPadClearanceCtrl),
            ("Pin 1 end outer padding (mm)", self.m_HeaderLeadingPaddingCtrl),
            ("Far end outer padding (mm)", self.m_HeaderTrailingPaddingCtrl),
        ):
            self._add_vertical_control(header_grid, header_parent, label, control)

        header_detail_grid = wx.GridSizer(0, 4, 4, 8)
        for label, control in (
            ("Opening end extension (mm)", self.m_HeaderOpeningEndPaddingCtrl),
            ("Label row end padding (mm)", self.m_HeaderLabelPaddingCtrl),
            ("Pin-side outer padding (mm)", self.m_HeaderPinOuterPaddingCtrl),
            ("Pin-to-label gap (mm)", self.m_HeaderPinToLabelGapCtrl),
            ("Label-side outer padding (mm)", self.m_HeaderLabelOuterPaddingCtrl),
            ("Minimum rail width / height (mm)", self.m_HeaderCrossSizeCtrl),
        ):
            self._add_vertical_control(header_detail_grid, header_detail_parent, label, control)

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
            "Minimum total rail width (vertical header) or height (horizontal header). "
            "The rail still grows if its connector and labels need more room; 0 follows content."
        )
        header_box.Add(header_grid, 0, wx.EXPAND | wx.ALL, 5)
        self.m_HeaderDetailsCheckbox = wx.CheckBox(
            header_parent, label="Show detailed spacing"
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
            wx.StaticText(header_parent, label="Enter one label per pin."),
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

        component_panel = wx.Panel(self)
        component_box = wx.StaticBoxSizer(
            wx.StaticBox(component_panel, label="Component safe zone"), wx.VERTICAL
        )
        component_parent = component_box.GetStaticBox()
        component_grid = wx.FlexGridSizer(0, 4, 4, 8)
        component_grid.AddGrowableCol(1)
        component_grid.AddGrowableCol(3)
        self.m_ComponentPresetChoice = wx.Choice(
            component_parent, choices=tuple(COMPONENT_PRESET_LABELS.keys())
        )
        self.m_ComponentPositionChoice = wx.Choice(
            component_parent, choices=tuple(COMPONENT_POSITION_LABELS.keys())
        )
        self.m_ComponentCutoutChoice = wx.Choice(
            component_parent, choices=tuple(COMPONENT_CUTOUT_LABELS.keys())
        )
        self.m_ComponentWidthCtrl = self._double_control(component_parent, 0.1, 100.0, 2.2, 0.1, 2)
        self.m_ComponentHeightCtrl = self._double_control(component_parent, 0.1, 100.0, 1.1, 0.1, 2)
        self.m_ComponentClearanceCtrl = self._double_control(component_parent, 0.0, 50.0, 0.3, 0.05, 2)
        self.m_ComponentCutoutRadiusCtrl = self._double_control(component_parent, 0.0, 50.0, 0.7, 0.05, 2)
        self.m_ComponentTextGapCtrl = self._double_control(component_parent, 0.0, 100.0, 2.6, 0.1, 2)
        self.m_ComponentMinWidthCtrl = self._double_control(component_parent, 0.0, 200.0, 0.0, 0.5, 2)
        self.m_ComponentMinHeightCtrl = self._double_control(component_parent, 0.0, 200.0, 0.0, 0.5, 2)
        for attribute, label, control in (
            ("m_ComponentPresetLabel", "Package / envelope:", self.m_ComponentPresetChoice),
            ("m_ComponentPositionLabel", "Component position:", self.m_ComponentPositionChoice),
            ("m_ComponentCutoutLabel", "Safe-zone shape:", self.m_ComponentCutoutChoice),
            ("m_ComponentWidthLabel", "Envelope width (mm):", self.m_ComponentWidthCtrl),
            ("m_ComponentHeightLabel", "Envelope height (mm):", self.m_ComponentHeightCtrl),
            (
                "m_ComponentClearanceLabel",
                "Extra clearance (mm):",
                self.m_ComponentClearanceCtrl,
            ),
        ):
            setattr(
                self,
                attribute,
                self._add_control(component_grid, component_parent, label, control),
            )
        self.m_ComponentCutoutRadiusLabel = self._add_control(
            component_grid,
            component_parent,
            "Safe-zone radius (mm):",
            self.m_ComponentCutoutRadiusCtrl,
        )
        self.m_ComponentTextGapLabel = self._add_control(
            component_grid,
            component_parent,
            "Component-to-text gap (mm):",
            self.m_ComponentTextGapCtrl,
        )
        self.m_ComponentMinWidthLabel = self._add_control(
            component_grid, component_parent, "Minimum width (mm):", self.m_ComponentMinWidthCtrl
        )
        self.m_ComponentMinHeightLabel = self._add_control(
            component_grid, component_parent, "Minimum height (mm):", self.m_ComponentMinHeightCtrl
        )
        component_box.Add(component_grid, 0, wx.EXPAND | wx.ALL, 5)
        component_help = wx.StaticText(
            component_parent,
            label=(
                "Preset sizes are editable footprint envelopes. The preview guide and placement origin "
                "mark the real component centre; guide geometry is never exported."
            ),
        )
        component_help.Wrap(720)
        component_box.Add(component_help, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 7)
        component_panel.SetSizer(component_box)
        root_sizer.Insert(
            4,
            component_panel,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            10,
        )
        self.m_ComponentPanel = component_panel

        array_panel = wx.Panel(self)
        array_box = wx.StaticBoxSizer(
            wx.StaticBox(array_panel, label="Component array"), wx.VERTICAL
        )
        array_parent = array_box.GetStaticBox()
        array_grid = wx.FlexGridSizer(0, 4, 4, 8)
        array_grid.AddGrowableCol(1)
        array_grid.AddGrowableCol(3)
        self.m_ComponentArrayCountCtrl = wx.SpinCtrl(
            array_parent, min=2, max=16, initial=3
        )
        self.m_ComponentArrayOrientationChoice = wx.Choice(
            array_parent, choices=tuple(COMPONENT_ARRAY_ORIENTATION_LABELS.keys())
        )
        self.m_ComponentArrayPitchCtrl = self._double_control(
            array_parent, 0.1, 100.0, 5.0, 0.1, 2
        )
        self.m_ComponentArrayFillButton = wx.Button(
            array_parent, label="Fill labels 1…N"
        )
        self._add_control(
            array_grid, array_parent, "Component count:", self.m_ComponentArrayCountCtrl
        )
        self._add_control(
            array_grid,
            array_parent,
            "Array direction:",
            self.m_ComponentArrayOrientationChoice,
        )
        self._add_control(
            array_grid,
            array_parent,
            "Centre spacing (mm):",
            self.m_ComponentArrayPitchCtrl,
        )
        array_grid.Add(self.m_ComponentArrayFillButton, 0, wx.EXPAND)
        array_box.Add(array_grid, 0, wx.EXPAND | wx.ALL, 5)
        array_help = wx.StaticText(
            array_parent,
            label=(
                "Enter one label per component. Centre spacing is checked against "
                "the selected opening and rendered text so rows cannot overlap."
            ),
        )
        array_help.Wrap(720)
        array_box.Add(array_help, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 7)
        array_panel.SetSizer(array_box)
        root_sizer.Insert(
            5,
            array_panel,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            10,
        )
        self.m_ComponentArrayPanel = array_panel
        # Header mode has its own label padding, so the ordinary four-sided
        # padding grid and its dividers can disappear and return as one unit.
        self._ordinary_padding_items = (
            root_sizer.GetItem(6),
            root_sizer.GetItem(7),
            root_sizer.GetItem(8),
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
            "ContentLayoutChoice": self.m_ContentLayoutChoice,
            "SubtitleCtrl": self.m_SubtitleCtrl,
            "SubtitleFontChoice": self.m_SubtitleFontChoice,
            "SubtitleHeightCtrl": self.m_SubtitleHeightCtrl,
            "SubtitleLineSpacingCtrl": self.m_SubtitleLineSpacingCtrl,
            "SubtitleGapCtrl": self.m_SubtitleGapCtrl,
            "UnderlineCheckbox": self.m_UnderlineCheckbox,
            "UnderlineThicknessCtrl": self.m_UnderlineThicknessCtrl,
            "UnderlineGapCtrl": self.m_UnderlineGapCtrl,
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
            "ComponentPresetChoice": self.m_ComponentPresetChoice,
            "ComponentPositionChoice": self.m_ComponentPositionChoice,
            "ComponentCutoutChoice": self.m_ComponentCutoutChoice,
            "ComponentWidthCtrl": self.m_ComponentWidthCtrl,
            "ComponentHeightCtrl": self.m_ComponentHeightCtrl,
            "ComponentClearanceCtrl": self.m_ComponentClearanceCtrl,
            "ComponentCutoutRadiusCtrl": self.m_ComponentCutoutRadiusCtrl,
            "ComponentTextGapCtrl": self.m_ComponentTextGapCtrl,
            "ComponentMinWidthCtrl": self.m_ComponentMinWidthCtrl,
            "ComponentMinHeightCtrl": self.m_ComponentMinHeightCtrl,
            "ComponentArrayCountCtrl": self.m_ComponentArrayCountCtrl,
            "ComponentArrayOrientationChoice": self.m_ComponentArrayOrientationChoice,
            "ComponentArrayPitchCtrl": self.m_ComponentArrayPitchCtrl,
        }
        self.m_StudioModeChoice.Bind(wx.EVT_CHOICE, self._on_mode_changed)
        self.m_HeaderOrientationChoice.Bind(wx.EVT_CHOICE, self._on_header_orientation_changed)
        self.m_HeaderOpeningChoice.Bind(wx.EVT_CHOICE, self._on_header_opening_changed)
        self.m_HeaderDetailsCheckbox.Bind(wx.EVT_CHECKBOX, self._on_header_details_changed)
        self.m_HeaderPinCountCtrl.Bind(wx.EVT_SPINCTRL, self._on_header_pin_count_changed)
        self.m_HeaderPinCountCtrl.Bind(wx.EVT_TEXT, self._on_header_pin_count_changed)
        self.m_HeaderPin1Choice.Bind(wx.EVT_CHOICE, self._on_live_artwork_changed)
        self.m_HeaderPinSideChoice.Bind(wx.EVT_CHOICE, self._on_live_artwork_changed)
        self.m_HeaderPin1MarkerCheckbox.Bind(wx.EVT_CHECKBOX, self._on_live_artwork_changed)
        self.m_ShapeChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_ShapeVariantChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_StartCapChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_EndCapChoice.Bind(wx.EVT_CHOICE, self._on_shape_changed)
        self.m_PresetPickerButton.Bind(wx.EVT_BUTTON, self._open_label_picker)
        self.m_IconPickerButton.Bind(wx.EVT_BUTTON, self._open_icon_picker)
        self.m_IconPositionChoice.Bind(wx.EVT_CHOICE, self._on_icon_changed)
        self.m_ContentLayoutChoice.Bind(wx.EVT_CHOICE, self._on_content_layout_changed)
        self.m_ComponentPresetChoice.Bind(wx.EVT_CHOICE, self._on_component_preset_changed)
        self.m_ComponentCutoutChoice.Bind(wx.EVT_CHOICE, self._on_component_cutout_changed)
        self.m_ComponentArrayOrientationChoice.Bind(
            wx.EVT_CHOICE, self._on_component_array_orientation_changed
        )
        self.m_MultiLineText.Bind(wx.EVT_TEXT, self._on_label_text_edited)
        self.m_SubtitleCtrl.Bind(wx.EVT_TEXT, self._on_label_text_edited)
        self.m_UnderlineCheckbox.Bind(wx.EVT_CHECKBOX, self._on_underline_changed)
        self.m_HeaderFillLabelsButton.Bind(wx.EVT_BUTTON, self._fill_header_labels)
        self.m_ComponentArrayFillButton.Bind(wx.EVT_BUTTON, self._fill_component_labels)

    def _build_machine_code_controls(self):
        root_sizer = self.GetSizer()
        panel = wx.Panel(self)
        box = wx.StaticBoxSizer(
            wx.StaticBox(panel, label="Machine-readable code"), wx.VERTICAL
        )
        machine_parent = box.GetStaticBox()
        grid = wx.FlexGridSizer(0, 4, 4, 8)
        grid.AddGrowableCol(1)
        grid.AddGrowableCol(3)

        self.m_MachineCodeTypeChoice = wx.Choice(
            machine_parent, choices=tuple(MACHINE_CODE_LABELS.keys())
        )
        self.m_MachineCodeModuleSizeCtrl = self._double_control(
            machine_parent, CODE128_MIN_MODULE_MM, 5.0, QR_MIN_MODULE_MM, 0.05, 2
        )
        self.m_MachineCodeBarHeightCtrl = self._double_control(
            machine_parent,
            CODE128_MIN_HEIGHT_MM,
            100.0,
            CODE128_DEFAULT_HEIGHT_MM,
            0.5,
            1,
        )
        self.m_MachineCodePresentationChoice = wx.Choice(
            machine_parent, choices=tuple(QR_PRESENTATION_LABELS.keys())
        )
        self.m_MachineCodeCaptionCtrl = wx.TextCtrl(machine_parent, value="SCAN ME")
        self.m_MachineCodeCaptionCtrl.SetMaxLength(32)
        self.m_MachineCodeCaptionHeightCtrl = self._double_control(
            machine_parent, 0.8, 10.0, 1.2, 0.1, 1
        )
        self.m_MachineCodeFramePaddingCtrl = self._double_control(
            machine_parent, 0.0, 10.0, 0.2, 0.05, 2
        )
        self.m_MachineCodeShowContentCheckbox = wx.CheckBox(
            machine_parent, label="Show editable text below code"
        )
        self.m_MachineCodeContentCtrl = wx.TextCtrl(machine_parent, value="")
        self.m_MachineCodeContentCtrl.SetMaxLength(96)
        self.m_MachineCodeContentHeightCtrl = self._double_control(
            machine_parent, 0.6, 10.0, 0.9, 0.1, 1
        )
        self.m_MachineCodeContentGapCtrl = self._double_control(
            machine_parent, 0.0, 10.0, 0.5, 0.1, 1
        )
        self.m_MachineCodeFramePaddingCtrl.SetToolTip(
            "Extra space outside the required QR quiet zone. Zero still preserves the full quiet zone."
        )
        self._add_control(grid, machine_parent, "Code type:", self.m_MachineCodeTypeChoice)
        self.m_MachineCodeModuleSizeLabel = self._add_control(
            grid, machine_parent, "Module size (mm):", self.m_MachineCodeModuleSizeCtrl
        )
        self.m_MachineCodeBarHeightLabel = self._add_control(
            grid, machine_parent, "Bar height (mm):", self.m_MachineCodeBarHeightCtrl
        )
        self.m_MachineCodePresentationLabel = self._add_control(
            grid, machine_parent, "QR presentation:", self.m_MachineCodePresentationChoice
        )
        self.m_MachineCodeFramePaddingLabel = self._add_control(
            grid, machine_parent, "Extra frame gap (mm):", self.m_MachineCodeFramePaddingCtrl
        )
        self.m_MachineCodeCaptionLabel = self._add_control(
            grid, machine_parent, "Footer text:", self.m_MachineCodeCaptionCtrl
        )
        self.m_MachineCodeCaptionHeightLabel = self._add_control(
            grid, machine_parent, "Footer height (mm):", self.m_MachineCodeCaptionHeightCtrl
        )
        grid.Add(self.m_MachineCodeShowContentCheckbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
        grid.Add((0, 0), 1, wx.EXPAND)
        self.m_MachineCodeContentLabel = self._add_control(
            grid, machine_parent, "Text below code:", self.m_MachineCodeContentCtrl
        )
        self.m_MachineCodeContentHeightLabel = self._add_control(
            grid, machine_parent, "Text height (mm):", self.m_MachineCodeContentHeightCtrl
        )
        self.m_MachineCodeContentGapLabel = self._add_control(
            grid, machine_parent, "Text gap (mm):", self.m_MachineCodeContentGapCtrl
        )
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 5)
        self.m_MachineCodeHelp = wx.StaticText(machine_parent, label="")
        self.m_MachineCodeHelp.Wrap(720)
        box.Add(
            self.m_MachineCodeHelp,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            7,
        )
        panel.SetSizer(box)
        root_sizer.Insert(
            6,
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
                "MachineCodeShowContentCheckbox": self.m_MachineCodeShowContentCheckbox,
                "MachineCodeContentCtrl": self.m_MachineCodeContentCtrl,
                "MachineCodeContentHeightCtrl": self.m_MachineCodeContentHeightCtrl,
                "MachineCodeContentGapCtrl": self.m_MachineCodeContentGapCtrl,
            }
        )
        self.m_MachineCodeTypeChoice.Bind(
            wx.EVT_CHOICE, self._on_machine_code_type_changed
        )
        self.m_MachineCodePresentationChoice.Bind(
            wx.EVT_CHOICE, self._on_machine_code_presentation_changed
        )
        self.m_MachineCodeShowContentCheckbox.Bind(
            wx.EVT_CHECKBOX, self._on_machine_code_content_changed
        )
        self.m_MachineCodeContentCtrl.Bind(wx.EVT_TEXT, self._on_live_artwork_changed)

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
        self.m_spCharSlash = wx.Button(
            self.m_spCharPanel, label=" / ", style=wx.BU_EXACTFIT
        )
        self.m_spCharBackslash = wx.Button(
            self.m_spCharPanel, label=" \\ ", style=wx.BU_EXACTFIT
        )
        for button, character in (
            (self.m_spCharSlash, "/"),
            (self.m_spCharBackslash, "\\"),
        ):
            button.SetMinSize(wx.Size(52, -1))
            button.Bind(
                wx.EVT_BUTTON,
                lambda event, value=character: self._append_text_character(value),
            )
            self.m_spCharPanel.GetSizer().Add(button, 0, wx.ALIGN_CENTER_VERTICAL)
        self.m_inlineFormatTextbox.SetLabel("Enable inline formatting")
        self.m_advancedCheckbox.SetLabel("Advanced typography")
        self.m_LayerSelector.SetLabel("Output layer")
        self.m_sdbSizerOK.SetLabel(
            "Update artwork" if self.updateFootprint is not None else "Place artwork"
        )

        self.m_StudioModeChoice.SetToolTip(
            "Choose labels, component callouts, connector rails, QR codes, or barcodes."
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
        self.m_AlignmentChoice.SetToolTip(
            "Align text and symbols within their available label space. For an auto-fit label, "
            "set a minimum width to create visible extra space; header labels use their shared lane."
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

    @staticmethod
    def _sizer_contains_window(sizer, target):
        if sizer is None:
            return False
        for item in sizer.GetChildren():
            if item.GetWindow() is target:
                return True
            if item.GetSizer() is not None and MainDialog._sizer_contains_window(
                item.GetSizer(), target
            ):
                return True
        return False

    def _take_root_item_containing(self, root_sizer, target):
        """Detach and return the top-level sizer item containing a window."""
        for index in range(root_sizer.GetItemCount()):
            item = root_sizer.GetItem(index)
            nested = item.GetSizer()
            if item.GetWindow() is target or self._sizer_contains_window(nested, target):
                payload = nested or item.GetWindow()
                root_sizer.Detach(index)
                return payload
        return None

    def _reparent_sizer_windows(self, sizer, parent):
        """Move one complete settings tree to its final content panel.

        wxWidgets keeps both a native parent relationship and a separate
        ``containing sizer`` relationship.  Moving the generated controls
        through the dialog and then into a scroller left a short-lived,
        invalid ownership tree on Windows.  Windows validates that tree on a
        later layout (often the first numeric spinner edit) and aborts KiCad
        with ``SetContainingSizer(): window already in a sizer``.

        The generated tree is now moved exactly once, into a normal panel
        owned by the scroller.  Static-box children remain children of their
        static box throughout the move, as wxWidgets requires.
        """
        content_parent = parent
        if isinstance(sizer, wx.StaticBoxSizer):
            static_box = sizer.GetStaticBox()
            if static_box.GetParent() is not parent:
                static_box.Reparent(parent)
            content_parent = static_box
        for item in sizer.GetChildren():
            window = item.GetWindow()
            nested = item.GetSizer()
            if window is not None:
                if window.GetParent() is not content_parent:
                    window.Reparent(content_parent)
                child_sizer = window.GetSizer()
                if child_sizer is not None:
                    self._reparent_sizer_windows(child_sizer, window)
            elif nested is not None:
                self._reparent_sizer_windows(nested, content_parent)

    def _rebuild_studio_layout(self):
        """Replace the legacy growing form with a fixed workspace and scroller."""
        legacy_root = self.GetSizer()
        self._take_root_item_containing(legacy_root, self.m_LayerSelector)
        text_sizer = self._take_root_item_containing(legacy_root, self.m_MultiLineText)
        preview_sizer = self._take_root_item_containing(legacy_root, self.m_PreviewPanel)
        self._take_root_item_containing(legacy_root, self.m_sdbSizerOK)
        if text_sizer is None or preview_sizer is None:
            raise RuntimeError("Could not rebuild the Kobee Studio workspace")

        for button in (self.m_sdbSizerCancel, self.m_sdbSizerOK):
            containing = button.GetContainingSizer()
            if containing is not None:
                containing.Detach(button)
        advanced_sizer = self.m_advancedCheckbox.GetContainingSizer()
        if advanced_sizer is not None:
            advanced_sizer.Detach(self.m_advancedCheckbox)

        # Subtitle entry belongs with the main text, not among geometry controls.
        for control in (self.m_SubtitleLabel, self.m_SubtitleCtrl):
            containing = control.GetContainingSizer()
            if containing is not None:
                containing.Detach(control)
            control.Reparent(self)
        # Match the main multiline field across macOS, Windows, and Linux.
        # The generated subtitle control otherwise inherits the panel colour
        # after reparenting, which makes it look disabled in dark themes.
        self.m_SubtitleCtrl.SetBackgroundColour(self.m_MultiLineText.GetBackgroundColour())
        self.m_SubtitleCtrl.SetForegroundColour(self.m_MultiLineText.GetForegroundColour())

        # The generated sizer becomes the content of a normal panel inside
        # the scroller.  Do not set it directly on wx.ScrolledWindow: some
        # Windows wx builds defer their sizer ownership validation until a
        # later relayout, which made an innocent text-height edit fatal.
        self.SetSizer(None, deleteOld=False)
        scroller = wx.ScrolledWindow(
            self,
            style=wx.VSCROLL | wx.TAB_TRAVERSAL | wx.BORDER_NONE,
        )
        scroller.SetBackgroundColour(self.GetBackgroundColour())
        scroller.SetScrollRate(0, 12)
        scroller.SetMinSize(wx.Size(1, 180))
        settings_content = wx.Panel(scroller)
        settings_content.SetBackgroundColour(self.GetBackgroundColour())
        self._reparent_sizer_windows(legacy_root, settings_content)
        settings_content.SetSizer(legacy_root)
        settings_content.Layout()
        settings_content.Fit()
        scroller_sizer = wx.BoxSizer(wx.VERTICAL)
        scroller_sizer.Add(settings_content, 0, wx.EXPAND)
        scroller.SetSizer(scroller_sizer)
        self.m_advancedCheckbox.Reparent(self)
        self.m_advancedCheckbox.SetLabel("Show advanced settings")
        self.m_advancedCheckbox.SetToolTip(
            "Reveal exact geometry, spacing and typography controls."
        )
        self.m_SettingsScroller = scroller
        self.m_SettingsContent = settings_content

        # Artwork type is the first decision. Keep it above layer selection and
        # outside the scrollable settings area so it remains discoverable.
        studio_box = self.m_StudioPanel.GetSizer()
        studio_box.Detach(self.m_ArtworkTypeRow)
        mode_sizer = self.m_StudioModeChoice.GetContainingSizer()
        if mode_sizer is not None:
            mode_sizer.Detach(self.m_StudioModeChoice)
        self.m_ArtworkTypeLabel.Hide()
        self.m_StudioModeChoice.Reparent(self)
        artwork_box = wx.StaticBox(self, label="Artwork type")
        artwork_bar = wx.StaticBoxSizer(artwork_box, wx.HORIZONTAL)
        self.m_StudioModeChoice.Reparent(artwork_box)
        artwork_bar.Add(self.m_StudioModeChoice, 1, wx.EXPAND | wx.ALL, 5)
        self.m_HelpButton = wx.Button(artwork_box, label="Need help?")
        self.m_HelpButton.SetToolTip("Open Kobee Studio guides, tutorials and installation help.")
        self.m_HelpButton.Bind(wx.EVT_BUTTON, self._open_docs)
        artwork_bar.Add(self.m_HelpButton, 0, wx.ALIGN_CENTER_VERTICAL | wx.TOP | wx.RIGHT | wx.BOTTOM, 5)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(artwork_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        root.Add(self.m_LayerSelector, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        layer_help = wx.StaticText(
            self,
            label=(
                "Each artwork item is placed on one layer. To repeat it on another layer, "
                "duplicate the placed artwork, reopen it, then choose the new layer."
            ),
        )
        layer_help.Wrap(860)
        root.Add(layer_help, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

        workspace = wx.BoxSizer(wx.HORIZONTAL)
        text_editor = wx.BoxSizer(wx.VERTICAL)
        text_editor.Add(text_sizer, 1, wx.EXPAND)
        subtitle_editor = wx.BoxSizer(wx.VERTICAL)
        subtitle_editor.Add(self.m_SubtitleLabel, 0, wx.BOTTOM, 2)
        subtitle_editor.Add(self.m_SubtitleCtrl, 0, wx.EXPAND)
        text_editor.Add(subtitle_editor, 0, wx.EXPAND | wx.TOP, 6)
        workspace.Add(text_editor, 1, wx.EXPAND | wx.RIGHT, 6)
        workspace.Add(preview_sizer, 1, wx.EXPAND | wx.LEFT, 6)
        root.Add(workspace, 0, wx.EXPAND | wx.ALL, 10)
        # This bar deliberately sits outside the scroller, so advanced controls
        # can always be reached no matter how far down a long mode is scrolled.
        settings_bar = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self, label="Settings")
        heading.SetFont(heading.GetFont().Bold())
        settings_bar.Add(heading, 0, wx.ALIGN_CENTER_VERTICAL)
        settings_bar.AddStretchSpacer(1)
        settings_bar.Add(self.m_advancedCheckbox, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(settings_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(scroller, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        root.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.TOP, 8)

        footer = wx.BoxSizer(wx.HORIZONTAL)
        shortcut = wx.StaticText(self, label="Ctrl/Shift + Enter places artwork")
        footer.Add(shortcut, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        buttons = wx.StdDialogButtonSizer()
        buttons.AddButton(self.m_sdbSizerCancel)
        buttons.AddButton(self.m_sdbSizerOK)
        buttons.Realize()
        footer.Add(buttons, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(footer, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(root)
        self.m_MainStudioSizer = root
        self.m_WorkspaceSizer = workspace
        self.m_SubtitleEditorSizer = subtitle_editor
        self.m_FooterSizer = footer

    def _open_docs(self, event):
        """Open the hosted Kobee Studio guides in the system browser."""
        wx.LaunchDefaultBrowser(KOBEE_STUDIO_DOCS_URL)
        event.Skip()

    def _advanced_visible(self):
        return bool(self.m_advancedCheckbox.IsChecked())

    def _bind_live_artwork_controls(self):
        """Schedule one preview refresh after a burst of control changes."""
        for control in (
            self.m_HeightCtrl,
            self.m_WidthCtrl,
            self.m_LineSpacingCtrl,
            self.m_PaddingTopCtrl,
            self.m_PaddingLeftCtrl,
            self.m_PaddingRightCtrl,
            self.m_PaddingBottomCtrl,
            self.m_BorderThicknessCtrl,
            self.m_CornerRadiusCtrl,
            self.m_FeatureSizeCtrl,
            self.m_IconHeightCtrl,
            self.m_IconGapCtrl,
            self.m_SubtitleHeightCtrl,
            self.m_SubtitleLineSpacingCtrl,
            self.m_SubtitleGapCtrl,
            self.m_UnderlineThicknessCtrl,
            self.m_UnderlineGapCtrl,
            self.m_HeaderPadClearanceCtrl,
            self.m_HeaderOpeningEndPaddingCtrl,
            self.m_HeaderLeadingPaddingCtrl,
            self.m_HeaderTrailingPaddingCtrl,
            self.m_HeaderLabelPaddingCtrl,
            self.m_HeaderPinOuterPaddingCtrl,
            self.m_HeaderPinToLabelGapCtrl,
            self.m_HeaderLabelOuterPaddingCtrl,
            self.m_HeaderCrossSizeCtrl,
            self.m_ComponentWidthCtrl,
            self.m_ComponentHeightCtrl,
            self.m_ComponentClearanceCtrl,
            self.m_ComponentCutoutRadiusCtrl,
            self.m_ComponentTextGapCtrl,
            self.m_ComponentMinWidthCtrl,
            self.m_ComponentMinHeightCtrl,
            self.m_ComponentArrayPitchCtrl,
            self.m_MachineCodeModuleSizeCtrl,
            self.m_MachineCodeBarHeightCtrl,
            self.m_MachineCodeCaptionHeightCtrl,
            self.m_MachineCodeFramePaddingCtrl,
            self.m_MachineCodeContentHeightCtrl,
            self.m_MachineCodeContentGapCtrl,
        ):
            control.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_live_artwork_changed)
            control.Bind(wx.EVT_TEXT, self._on_live_artwork_changed)
        self.m_FontComboBox.Bind(wx.EVT_COMBOBOX, self._on_live_artwork_changed)
        self.m_AlignmentChoice.Bind(wx.EVT_CHOICE, self._on_live_artwork_changed)
        for control in (
            self.m_ShapeDirectionChoice,
            self.m_SubtitleFontChoice,
            self.m_ComponentPositionChoice,
        ):
            control.Bind(wx.EVT_CHOICE, self._on_live_artwork_changed)
        self.m_ComponentArrayCountCtrl.Bind(
            wx.EVT_SPINCTRL, self._on_component_array_count_changed
        )
        self.m_ComponentArrayCountCtrl.Bind(
            wx.EVT_TEXT, self._on_component_array_count_changed
        )
        self.m_MachineCodeCaptionCtrl.Bind(wx.EVT_TEXT, self._on_live_artwork_changed)

    def _on_live_artwork_changed(self, event):
        if (
            self._studio_controls_ready
            and not self._applying_mode_defaults
            and not self._updating_machine_code_content
        ):
            self._request_preview(event)
        event.Skip()

    def _request_preview(self, event=None, *, immediate=False):
        """Coalesce UI events so geometry generation never monopolises wx."""
        if not self._studio_controls_ready:
            return
        self.ReGenerateFlag(event)
        self.timer.Stop()
        if immediate:
            self._preview_pending = False
            self._regenerate_preview_now()
            self.label_params = self.CurrentSettings()
            return
        self._preview_pending = True
        self.timer.Start(milliseconds=300, oneShot=True)

    def labelEditOnText(self, event):
        """Replace the inherited repeating regeneration loop with one pass."""
        if self._studio_controls_ready and self._preview_pending:
            self._preview_pending = False
            self._regenerate_preview_now()
            self.label_params = self.CurrentSettings()
        event.Skip()

    def _refresh_settings_layout(self):
        """Refresh scrolling without changing the outer dialog size."""
        if not hasattr(self, "m_SettingsScroller"):
            return
        self.m_StudioPanel.Layout()
        self.m_HeaderPanel.Layout()
        self.m_ComponentPanel.Layout()
        self.m_ComponentArrayPanel.Layout()
        self.m_MachineCodePanel.Layout()
        self.m_SettingsContent.Layout()
        self.m_SettingsContent.Fit()
        self.m_SettingsScroller.GetSizer().Layout()
        self.m_SettingsScroller.FitInside()
        self.m_SettingsScroller.Layout()
        self.Layout()

    @staticmethod
    def _show_settings_panel(panel, show):
        """Show or remove a settings panel without leaving an empty sizer slot.

        ``wx.Panel.Show()`` alone is not reliable across the supported wx
        builds once a panel has been reparented into the settings scroller. In
        particular, macOS can leave the panel's static-box minimum size behind
        after every child has been hidden. Toggling the containing sizer item
        as well removes that stale geometry before the scroller is refitted.
        """
        containing_sizer = panel.GetContainingSizer()
        if containing_sizer is not None:
            containing_sizer.Show(panel, show)
        panel.Show(show)

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
        mode = self.m_StudioModeChoice.GetStringSelection()
        if not self._editing_existing_artwork:
            self._apply_mode_defaults(mode, refit=False)
        else:
            self._update_mode_ui(refit=True)
        if hasattr(self, "m_SettingsScroller"):
            self.m_SettingsScroller.Scroll(0, 0)
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_header_orientation_changed(self, event):
        self._sync_header_sides()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_header_pin_count_changed(self, event):
        if (
            not self._studio_controls_ready
            or self._applying_mode_defaults
            or self.m_StudioModeChoice.GetStringSelection() != "2.54 mm Pin Header"
        ):
            event.Skip()
            return
        count = self.m_HeaderPinCountCtrl.GetValue()
        labels = self.m_MultiLineText.GetValue().splitlines()
        resized = labels[:count]
        resized.extend(
            "Pin {}".format(index)
            for index in range(len(resized) + 1, count + 1)
        )
        value = "\n".join(resized)
        if value != self.m_MultiLineText.GetValue():
            self.m_MultiLineText.SetValue(value)
        self._request_preview(event)
        event.Skip()

    def _on_header_opening_changed(self, event):
        self._update_opening_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_header_details_changed(self, event):
        show_details = (
            self._advanced_visible()
            and self.m_HeaderDetailsCheckbox.IsChecked()
            and self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header"
        )
        self.m_HeaderDetailBox.GetStaticBox().Show(show_details)
        self.m_HeaderDetailBox.ShowItems(show_details)
        self._schedule_dynamic_refit()
        event.Skip()

    def _on_content_layout_changed(self, event):
        self._update_content_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_component_preset_changed(self, event):
        preset = COMPONENT_PRESET_BY_LABEL.get(
            self.m_ComponentPresetChoice.GetStringSelection()
        )
        if preset is not None:
            self.m_ComponentWidthCtrl.SetValue(preset.width_mm)
            self.m_ComponentHeightCtrl.SetValue(preset.height_mm)
            self.m_ComponentCutoutChoice.SetStringSelection(
                COMPONENT_CUTOUT_ID_TO_LABEL[preset.cutout_shape]
            )
            self.m_ComponentCutoutRadiusCtrl.SetValue(preset.cutout_radius_mm)
            self._ensure_component_array_pitch()
        self._update_component_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_component_cutout_changed(self, event):
        self._update_component_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_component_array_orientation_changed(self, event):
        self._ensure_component_array_pitch()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _on_component_array_count_changed(self, event):
        if (
            not self._studio_controls_ready
            or self._applying_mode_defaults
            or self.m_StudioModeChoice.GetStringSelection() != "Component Array"
        ):
            event.Skip()
            return
        count = self.m_ComponentArrayCountCtrl.GetValue()
        labels = self.m_MultiLineText.GetValue().splitlines()
        resized = labels[:count]
        resized.extend(
            "Component {}".format(index)
            for index in range(len(resized) + 1, count + 1)
        )
        value = "\n".join(resized)
        if value != self.m_MultiLineText.GetValue():
            self.m_MultiLineText.SetValue(value)
        self._request_preview(event)
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

    def _on_machine_code_content_changed(self, event):
        if (
            self.m_MachineCodeShowContentCheckbox.IsChecked()
            and not self.m_MachineCodeContentCtrl.GetValue().strip()
        ):
            self._updating_machine_code_content = True
            try:
                self.m_MachineCodeContentCtrl.SetValue(
                    self.m_MultiLineText.GetValue().strip()
                )
            finally:
                self._updating_machine_code_content = False
        # Windows wx can fault when a checkbox's native event both changes a
        # child text value and forces the scroller to lay out immediately.
        # Make the controls visible now, but leave its refit until the event
        # has returned and schedule one preview for the completed state.
        self._update_machine_code_ui(defer_layout=True)
        self._request_preview(event)
        event.Skip()

    def _on_underline_changed(self, event):
        self._update_content_ui()
        self.ReGenerateFlag(event)
        self.ReGeneratePreview()
        event.Skip()

    def _append_text_character(self, character):
        control = self.m_MultiLineText
        start, end = control.GetSelection()
        value = control.GetValue()
        control.SetValue(value[:start] + character + value[end:])
        insertion = start + len(character)
        control.SetSelection(insertion, insertion)
        control.SetFocus()

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
            and not self._applying_mode_defaults
            and not self._applying_label_preset
            and self.m_StudioModeChoice.GetStringSelection() in ("Label", "Component Callout")
        ):
            self.m_PresetLabelChoice.SetStringSelection("Custom label")
            self._update_asset_button_labels()
        if self._studio_controls_ready and not self._applying_mode_defaults:
            self._request_preview(event)
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
        label_mode = self.m_StudioModeChoice.GetStringSelection() in (
            "Label",
            "Component Callout",
        )
        advanced = self._advanced_visible()
        icon_id = ICON_LABELS.get(self.m_IconChoice.GetStringSelection(), "")
        icon_only = self.m_IconPositionChoice.GetStringSelection() == "Icon only"
        self.m_PresetLabelChoice.Enable(label_mode)
        self.m_IconChoice.Enable(label_mode)
        self.m_PresetPickerButton.Enable(label_mode)
        self.m_IconPickerButton.Enable(label_mode)
        show_icon_options = label_mode and bool(icon_id)
        for control in (self.m_IconPositionLabel, self.m_IconPositionChoice):
            control.Show(show_icon_options)
        for control in (self.m_IconHeightLabel, self.m_IconHeightCtrl):
            control.Show(show_icon_options and advanced)
        show_icon_gap = show_icon_options and not icon_only and advanced
        self.m_IconGapLabel.Show(show_icon_gap)
        self.m_IconGapCtrl.Show(show_icon_gap)
        self._update_asset_button_labels()
        self.m_StudioPanel.Layout()
        self._schedule_dynamic_refit()

    def _update_content_ui(self):
        if not hasattr(self, "m_ContentLayoutChoice"):
            return
        content_mode = self.m_StudioModeChoice.GetStringSelection() in (
            "Label",
            "Component Callout",
        )
        subtitle_mode = (
            content_mode
            and self.m_ContentLayoutChoice.GetStringSelection() == "Title + subtitle"
        )
        advanced = self._advanced_visible()
        label_mode = self.m_StudioModeChoice.GetStringSelection() == "Label"
        self.m_UnderlineCheckbox.Show(label_mode)
        underline_details = (
            label_mode and self.m_UnderlineCheckbox.IsChecked() and advanced
        )
        for control in (
            self.m_UnderlineThicknessLabel,
            self.m_UnderlineThicknessCtrl,
            self.m_UnderlineGapLabel,
            self.m_UnderlineGapCtrl,
        ):
            control.Show(underline_details)
        for control in (
            self.m_SubtitleLabel,
            self.m_SubtitleCtrl,
            self.m_SubtitleHeightLabel,
            self.m_SubtitleHeightCtrl,
        ):
            control.Show(subtitle_mode)
        for control in (
            self.m_SubtitleFontLabel,
            self.m_SubtitleFontChoice,
            self.m_SubtitleLineSpacingLabel,
            self.m_SubtitleLineSpacingCtrl,
            self.m_SubtitleGapLabel,
            self.m_SubtitleGapCtrl,
        ):
            control.Show(subtitle_mode and advanced)
        if content_mode:
            self.textLabel.SetLabel("Main text:" if subtitle_mode else "Label text:")
        self.m_StudioPanel.Layout()
        self._schedule_dynamic_refit()

    def _update_component_ui(self):
        if not hasattr(self, "m_ComponentPanel"):
            return
        advanced = self._advanced_visible()
        advanced_pairs = (
            (self.m_ComponentWidthLabel, self.m_ComponentWidthCtrl),
            (self.m_ComponentHeightLabel, self.m_ComponentHeightCtrl),
            (self.m_ComponentClearanceLabel, self.m_ComponentClearanceCtrl),
            (self.m_ComponentTextGapLabel, self.m_ComponentTextGapCtrl),
            (self.m_ComponentMinWidthLabel, self.m_ComponentMinWidthCtrl),
            (self.m_ComponentMinHeightLabel, self.m_ComponentMinHeightCtrl),
        )
        for label, control in advanced_pairs:
            label.Show(advanced)
            control.Show(advanced)
        rounded = self.m_ComponentCutoutChoice.GetStringSelection() == "Rounded rectangle"
        self.m_ComponentCutoutRadiusLabel.Show(advanced and rounded)
        self.m_ComponentCutoutRadiusCtrl.Show(advanced and rounded)
        self.m_ComponentPanel.Layout()
        self._schedule_dynamic_refit()

    def _update_machine_code_ui(self, defer_layout=False):
        if not hasattr(self, "m_MachineCodePanel"):
            return
        advanced = self._advanced_visible()
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

        self.m_MachineCodeModuleSizeLabel.Show(advanced)
        self.m_MachineCodeModuleSizeCtrl.Show(advanced)
        self.m_MachineCodeBarHeightLabel.Show(code128 and advanced)
        self.m_MachineCodeBarHeightCtrl.Show(code128 and advanced)
        self.m_MachineCodePresentationLabel.Show(not code128)
        self.m_MachineCodePresentationChoice.Show(not code128)
        presentation = QR_PRESENTATION_LABELS.get(
            self.m_MachineCodePresentationChoice.GetStringSelection(), "plain"
        )
        framed_mode = not code128 and presentation != "plain"
        self.m_MachineCodeFramePaddingLabel.Show(framed_mode and advanced)
        self.m_MachineCodeFramePaddingCtrl.Show(framed_mode and advanced)
        caption_mode = not code128 and presentation == "rounded_caption"
        self.m_MachineCodeCaptionLabel.Show(caption_mode)
        self.m_MachineCodeCaptionCtrl.Show(caption_mode)
        self.m_MachineCodeCaptionHeightLabel.Show(caption_mode and advanced)
        self.m_MachineCodeCaptionHeightCtrl.Show(caption_mode and advanced)
        show_content = self.m_MachineCodeShowContentCheckbox.IsChecked()
        self.m_MachineCodeContentLabel.Show(show_content)
        self.m_MachineCodeContentCtrl.Show(show_content)
        self.m_MachineCodeContentHeightLabel.Show(show_content and advanced)
        self.m_MachineCodeContentHeightCtrl.Show(show_content and advanced)
        self.m_MachineCodeContentGapLabel.Show(show_content and advanced)
        self.m_MachineCodeContentGapCtrl.Show(show_content and advanced)

        if code128:
            self.m_MachineCodeHelp.SetLabel(
                "Printable ASCII, maximum 48 characters. Defaults are fabrication-safe; "
                "open advanced settings to tune module width and bar height."
            )
        else:
            self.m_MachineCodeHelp.SetLabel(
                "UTF-8 payload, maximum 512 bytes. Quiet-zone and readability safeguards "
                "are automatic; advanced settings expose exact sizing."
            )
        if not defer_layout:
            self.m_MachineCodePanel.Layout()
        self._schedule_dynamic_refit()

    def _schedule_dynamic_refit(self):
        """Coalesce scroll-layout updates after controls change visibility."""
        if not self._studio_controls_ready or self._dynamic_refit_pending:
            return
        self._dynamic_refit_pending = True
        wx.CallAfter(self._refit_dynamic_controls)

    def _refit_dynamic_controls(self):
        self._dynamic_refit_pending = False
        if not self:
            return
        self._refresh_settings_layout()

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
        component_mode = (
            self.m_StudioModeChoice.GetStringSelection() in ("Component Callout", "Component Array")
        )
        choices = (
            HEADER_SHAPE_LABELS
            if header_mode
            else COMPONENT_SHAPE_LABELS
            if component_mode
            else LABEL_SHAPE_LABELS
        )
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
        mode = self.m_StudioModeChoice.GetStringSelection()
        choices = (
            HEADER_SHAPE_LABELS
            if mode == "2.54 mm Pin Header"
            else COMPONENT_SHAPE_LABELS
            if mode in ("Component Callout", "Component Array")
            else LABEL_SHAPE_LABELS
        )
        return choices[self.m_ShapeChoice.GetStringSelection()]

    def _fill_header_labels(self, event):
        count = self.m_HeaderPinCountCtrl.GetValue()
        self.m_MultiLineText.SetValue("\n".join(str(index + 1) for index in range(count)))
        self.ReGenerateFlag(event)

    def _fill_component_labels(self, event):
        count = self.m_ComponentArrayCountCtrl.GetValue()
        self.m_MultiLineText.SetValue("\n".join(str(index + 1) for index in range(count)))
        self.ReGenerateFlag(event)

    def _ensure_component_array_pitch(self):
        if self.m_StudioModeChoice.GetStringSelection() != "Component Array":
            return
        vertical = (
            self.m_ComponentArrayOrientationChoice.GetStringSelection()
            == "Vertical stack"
        )
        opening_size = (
            self.m_ComponentHeightCtrl.GetValue()
            if vertical
            else self.m_ComponentWidthCtrl.GetValue()
        ) + 2.0 * self.m_ComponentClearanceCtrl.GetValue()
        if vertical:
            opening_size = max(opening_size, self.m_HeightCtrl.GetValue())
        recommended = opening_size + 0.5
        if self.m_ComponentArrayPitchCtrl.GetValue() < recommended:
            self.m_ComponentArrayPitchCtrl.SetValue(recommended)

    def _apply_mode_defaults(self, mode, refit=True):
        """Reset a new artwork mode to a useful, valid starting design.

        Existing placed artwork is deliberately never passed through here: its
        embedded settings remain the source of truth when reopened for editing.
        """
        settings = mode_defaults(mode)
        self._applying_mode_defaults = True
        try:
            self.m_StudioModeChoice.SetStringSelection(settings["StudioModeChoice"])
            self._sync_shape_choices(mode == "2.54 mm Pin Header")
            self._apply_studio_settings(settings)
            self.m_MultiLineText.SetValue(settings["MultiLineText"])
            self.m_SubtitleCtrl.SetValue(settings["SubtitleCtrl"])
            if not self.m_FontComboBox.SetStringSelection(settings.get("FontComboBox", "")):
                self.m_FontComboBox.SetValue(settings.get("FontComboBox", ""))
            self.m_HeightCtrl.SetValue(settings.get("HeightCtrl", 1.2))
            self.m_WidthCtrl.SetValue(0.0)
            self.m_AlignmentChoice.SetStringSelection(settings.get("AlignmentChoice", "Center"))
            self.m_LineSpacingCtrl.SetValue(1.5)
            self.m_advancedCheckbox.SetValue(False)

            padding = COMPONENT_STYLE_DEFAULTS["padding_mm"] if mode in (
                "Component Callout", "Component Array"
            ) else None
            if padding is None:
                padding_values = DEFAULT_LABEL_DIMENSIONS
            else:
                padding_values = {
                    "PaddingTopCtrl": padding,
                    "PaddingLeftCtrl": padding,
                    "PaddingRightCtrl": padding,
                    "PaddingBottomCtrl": padding,
                }
            for key, control in (
                ("PaddingTopCtrl", self.m_PaddingTopCtrl),
                ("PaddingLeftCtrl", self.m_PaddingLeftCtrl),
                ("PaddingRightCtrl", self.m_PaddingRightCtrl),
                ("PaddingBottomCtrl", self.m_PaddingBottomCtrl),
            ):
                control.SetValue(padding_values[key])

            self._component_defaults_applied = mode in ("Component Callout", "Component Array")
        finally:
            self._applying_mode_defaults = False
        self._update_mode_ui(refit=refit)

    def _apply_component_design_defaults(self):
        defaults = COMPONENT_STYLE_DEFAULTS
        if not self.m_FontComboBox.SetStringSelection(defaults["font"]):
            self.m_FontComboBox.SetValue(defaults["font"])
        self.m_HeightCtrl.SetValue(defaults["height_mm"])
        self.m_AlignmentChoice.SetStringSelection(defaults["alignment"])
        self.m_CornerRadiusCtrl.SetValue(defaults["outer_radius_mm"])
        self.m_ComponentCutoutRadiusCtrl.SetValue(defaults["cutout_radius_mm"])
        self.m_ComponentTextGapCtrl.SetValue(defaults["component_text_gap_mm"])
        for control in (
            self.m_PaddingTopCtrl,
            self.m_PaddingLeftCtrl,
            self.m_PaddingRightCtrl,
            self.m_PaddingBottomCtrl,
        ):
            control.SetValue(defaults["padding_mm"])
        self._component_defaults_applied = True
        self._ensure_component_array_pitch()

    def _update_mode_ui(self, refit=True):
        selection = self.m_StudioModeChoice.GetStringSelection()
        label_mode = selection == "Label"
        component_mode = selection == "Component Callout"
        component_array_mode = selection == "Component Array"
        header_mode = selection == "2.54 mm Pin Header"
        code_mode = selection == "QR / Barcode"
        advanced = self._advanced_visible()
        self._sync_shape_choices(header_mode)
        if (component_mode or component_array_mode) and self.m_ShapeChoice.GetStringSelection() == "No container":
            self.m_ShapeChoice.SetStringSelection("Rounded rectangle")
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
        # QR / Barcode owns its settings outright. Hide the entire Design
        # panel, rather than just its child controls, so its empty static box
        # cannot remain as a collapsed artefact in the scroller.
        self._show_settings_panel(self.m_StudioPanel, not code_mode)
        self._show_settings_panel(self.m_HeaderPanel, header_mode)
        self._show_settings_panel(
            self.m_ComponentPanel, component_mode or component_array_mode
        )
        self._show_settings_panel(self.m_ComponentArrayPanel, component_array_mode)
        self._show_settings_panel(self.m_MachineCodePanel, code_mode)
        for group, show in (
            (self.m_ContentBox, label_mode or component_mode),
            (self.m_ContainerBox, not code_mode),
            (self.m_TypographyBox, not code_mode),
        ):
            group.GetStaticBox().Show(show)
            group.ShowItems(show)
        for item in self._ordinary_padding_items:
            item.Show((label_mode or component_mode or component_array_mode) and advanced)

        self.textLabel.SetLabel(
            "Pin labels (one per line):"
            if header_mode
            else "Component labels (one per line):"
            if component_array_mode
            else "Payload:"
            if code_mode
            else "Main text:"
            if self.m_ContentLayoutChoice.GetStringSelection() == "Title + subtitle"
            else "Label text:"
        )
        for control in (self.m_WidthCtrl, self.m_WidthLabel, self.m_WidthUnits):
            control.Show(label_mode and advanced)
            control.Enable(label_mode)
        for control in (self.m_lineSpacingLabel, self.m_LineSpacingCtrl):
            control.Show(not code_mode and advanced)
        self.m_AlignmentChoice.Enable(
            label_mode or component_mode or component_array_mode or header_mode
        )
        self.m_AlignmentLabel.Enable(
            label_mode or component_mode or component_array_mode or header_mode
        )
        self.m_advancedCheckbox.Show(True)

        legacy_advanced = advanced and not code_mode
        self.m_lineoverPanel.Show(legacy_advanced)
        self.m_spCharPanel.Show(legacy_advanced)
        self.m_AdvancedDivider.Show(legacy_advanced)
        self.m_HeaderDetailsCheckbox.Show(header_mode and advanced)
        header_details = (
            header_mode and advanced and self.m_HeaderDetailsCheckbox.IsChecked()
        )
        self.m_HeaderDetailBox.GetStaticBox().Show(header_details)
        self.m_HeaderDetailBox.ShowItems(header_details)

        self._update_opening_ui()
        self._update_shape_ui()
        self._update_icon_ui()
        self._update_content_ui()
        self._update_component_ui()
        self._update_machine_code_ui()
        if header_mode and not self.m_MultiLineText.GetValue().strip():
            self._fill_header_labels(wx.CommandEvent())
        elif component_array_mode and not self.m_MultiLineText.GetValue().strip():
            self._fill_component_labels(wx.CommandEvent())
        if refit:
            self._schedule_dynamic_refit()

    def _stabilise_dialog_layout(self):
        """Choose a useful initial size while keeping the dialog on-screen."""
        self.m_MultiLineText.SetMinSize(wx.Size(260, 112))
        self.m_PreviewPanel.SetMinSize(wx.Size(260, 112))
        display = wx.GetClientDisplayRect()
        width = max(720, min(1100, display.width - 80))
        height = max(560, min(780, display.height - 80))
        minimum_width = min(760, max(560, display.width - 40))
        minimum_height = min(600, max(480, display.height - 40))
        self.SetMinSize(wx.Size(minimum_width, minimum_height))
        self.SetSize(wx.Size(width, height))
        self._refresh_settings_layout()
        self.Centre(wx.BOTH)

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
        params, loaded_footprint = _launch_settings(params, self.config_defaults)
        self._editing_existing_artwork = loaded_footprint
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
            params["ContentLayoutChoice"] = "Single text"
            params["SubtitleCtrl"] = ""
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
        """Request a preview instead of rebuilding on the active UI event."""
        if not self._studio_controls_ready:
            return super(MainDialog, self).ReGeneratePreview(event)
        self._request_preview(event)

    def _regenerate_preview_now(self):
        self.polys = []
        self.stroke_polys = []
        self.guide_polys = []
        self.artwork = None
        self.error = None
        self.buzzard.layer = self.output_layer
        try:
            style = self._document_style()
            vectorizer = self._text_vectorizer
            text = self.m_MultiLineText.GetValue()
            mode = self.m_StudioModeChoice.GetStringSelection()
            subtitle = (
                self.m_SubtitleCtrl.GetValue()
                if mode in ("Label", "Component Callout")
                and self.m_ContentLayoutChoice.GetStringSelection() == "Title + subtitle"
                else ""
            )
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
                    show_content_text=self.m_MachineCodeShowContentCheckbox.IsChecked(),
                    content_text=self.m_MachineCodeContentCtrl.GetValue(),
                    content_height_mm=self.m_MachineCodeContentHeightCtrl.GetValue(),
                    content_gap_mm=self.m_MachineCodeContentGapCtrl.GetValue(),
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
            elif mode in ("Component Callout", "Component Array"):
                array_mode = mode == "Component Array"
                icon_id = (
                    ""
                    if array_mode
                    else ICON_LABELS.get(self.m_IconChoice.GetStringSelection(), "")
                )
                spec = ComponentCalloutSpec(
                    title=text,
                    subtitle=subtitle,
                    preset_id=COMPONENT_PRESET_LABELS.get(
                        self.m_ComponentPresetChoice.GetStringSelection(), "custom"
                    ),
                    component_width_mm=self.m_ComponentWidthCtrl.GetValue(),
                    component_height_mm=self.m_ComponentHeightCtrl.GetValue(),
                    component_clearance_mm=self.m_ComponentClearanceCtrl.GetValue(),
                    cutout_shape=COMPONENT_CUTOUT_LABELS[
                        self.m_ComponentCutoutChoice.GetStringSelection()
                    ],
                    cutout_radius_mm=self.m_ComponentCutoutRadiusCtrl.GetValue(),
                    component_position=COMPONENT_POSITION_LABELS[
                        self.m_ComponentPositionChoice.GetStringSelection()
                    ],
                    component_to_text_gap_mm=self.m_ComponentTextGapCtrl.GetValue(),
                    array_count=(self.m_ComponentArrayCountCtrl.GetValue() if array_mode else 1),
                    array_orientation=COMPONENT_ARRAY_ORIENTATION_LABELS[
                        self.m_ComponentArrayOrientationChoice.GetStringSelection()
                    ],
                    array_pitch_mm=self.m_ComponentArrayPitchCtrl.GetValue(),
                    subtitle_gap_mm=self.m_SubtitleGapCtrl.GetValue(),
                    minimum_width_mm=self.m_ComponentMinWidthCtrl.GetValue(),
                    minimum_height_mm=self.m_ComponentMinHeightCtrl.GetValue(),
                    shape=self._selected_shape() or "rounded_rectangle",
                    output_layer=self.output_layer,
                    style=style,
                )
                self.artwork = render_component_callout_artwork(
                    vectorizer,
                    spec,
                    icon_id=icon_id,
                    icon_position=ICON_POSITION_LABELS[
                        self.m_IconPositionChoice.GetStringSelection()
                    ],
                    icon_height_mm=self.m_IconHeightCtrl.GetValue(),
                    icon_gap_mm=self.m_IconGapCtrl.GetValue(),
                )
            else:
                icon_id = ICON_LABELS.get(self.m_IconChoice.GetStringSelection(), "")
                if not text and not subtitle and not icon_id:
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
                    subtitle_text=subtitle,
                    subtitle_typography=style.secondary_typography,
                    subtitle_gap_mm=self.m_SubtitleGapCtrl.GetValue(),
                    underline=self.m_UnderlineCheckbox.IsChecked(),
                    underline_thickness_mm=self.m_UnderlineThicknessCtrl.GetValue(),
                    underline_gap_mm=self.m_UnderlineGapCtrl.GetValue(),
                )
            self.polys = list(self.artwork.filled_polygons)
            self.stroke_polys = list(self.artwork.strokes)
            self.guide_polys = list(self.artwork.guides)
        except Exception as error:
            traceback.print_exc()
            self.error = str(error) or "Error generating artwork"
        self.RePaint()

    def OnOkClick(self, event):
        """Generate from the controls that are visible at the instant of placement."""
        # Numeric controls can still have uncommitted native text when the
        # user clicks Update artwork immediately after editing them.  Never
        # hand the placement layer a previous preview in that situation.
        self._request_preview(immediate=True)
        if self.error is not None or self.artwork is None:
            wx.MessageBox(
                self.error or "Enter valid artwork before placing it.",
                "Kobee Studio",
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return
        self.m_sdbSizerOK.Disable()
        try:
            super(MainDialog, self).OnOkClick(event)
        except Exception as error:
            traceback.print_exc()
            self.Show()
            self.m_sdbSizerOK.Enable()
            wx.MessageBox(
                str(error) or "KiCad could not place the artwork.",
                "Kobee Studio",
                wx.OK | wx.ICON_ERROR,
                self,
            )

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
            secondary_typography=(
                TypographyStyle(
                    font_name=_subtitle_font_name(
                        self.m_SubtitleFontChoice.GetStringSelection(),
                        self.m_FontComboBox.GetValue(),
                    ),
                    height_mm=max(0.01, self.m_SubtitleHeightCtrl.GetValue()),
                    width_mm=0.0,
                    line_spacing=max(0.1, self.m_SubtitleLineSpacingCtrl.GetValue()),
                    alignment=self.m_AlignmentChoice.GetStringSelection().lower(),
                )
                if self.m_StudioModeChoice.GetStringSelection() in ("Label", "Component Callout")
                and self.m_ContentLayoutChoice.GetStringSelection() == "Title + subtitle"
                else None
            ),
            shape=ShapeStyle(
                padding=padding,
                border_thickness_mm=0.0 if filled else border,
                corner_radius_mm=self.m_CornerRadiusCtrl.GetValue(),
                feature_size_mm=self.m_FeatureSizeCtrl.GetValue(),
                filled=filled,
                inverted=filled,
                direction=self.m_ShapeDirectionChoice.GetStringSelection().lower(),
                start_cap=cap_style_id(self.m_StartCapChoice.GetStringSelection()),
                end_cap=cap_style_id(self.m_EndCapChoice.GetStringSelection()),
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
        """Toggle exact controls without resizing the outer dialog."""
        if (
            self.m_advancedCheckbox.IsChecked()
            and self.m_StudioModeChoice.GetStringSelection() == "2.54 mm Pin Header"
        ):
            # Advanced header spacing is part of the advanced view; requiring
            # a second checkbox made the most useful connector controls easy
            # to miss.
            self.m_HeaderDetailsCheckbox.SetValue(True)
        self._update_mode_ui(refit=False)
        self._refresh_settings_layout()
        event.Skip()

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

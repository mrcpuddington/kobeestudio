#!/usr/bin/env python3
"""Generate the Kobee Studio visual feature board with KiCad 10 Python."""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import replace
from pathlib import Path

import pcbnew


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from kobeestudio.core.component_callout import ComponentCalloutSpec
from kobeestudio.core.composition import DocumentStyle, Padding, ShapeStyle, TypographyStyle
from kobeestudio.core.legacy_adapter import build_footprint_payload
from kobeestudio.core.pin_header import PinHeaderSpec
from kobeestudio.core.studio_artwork import (
    TextVectorizer,
    render_component_callout_artwork,
    render_header_artwork,
    render_label_artwork,
    render_machine_code_artwork,
    serialize_artwork,
)
from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.core.transforms import (
    BOTTOM_COPPER,
    BOTTOM_MASK,
    BOTTOM_SILKSCREEN,
    FRONT_COPPER,
    FRONT_MASK,
    FRONT_SILKSCREEN,
)
from kobeestudio.integration.kicad_compatibility import KiCadCompatibility


HERE = Path(__file__).resolve().parent
BOARD_PATH = HERE / "kobee-studio-showcase.kicad_pcb"
FOOTPRINT_ROOT = Path(
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
)
FOOTPRINT_IO = pcbnew.PCB_IO_KICAD_SEXPR()
COMPATIBILITY = KiCadCompatibility()


def mm(x, y):
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def make_style(
    height=1.5,
    *,
    font="FreddySpark-Regular",
    alignment="center",
    padding=(0.6, 1.0, 0.6, 1.0),
    radius=0.6,
    filled=True,
    border=0.2,
    start_cap="square",
    end_cap="rounded",
    secondary_height=None,
):
    top, right, bottom, left = padding
    secondary = (
        TypographyStyle(
            font_name=font,
            height_mm=secondary_height,
            alignment=alignment,
            line_spacing=1.2,
        )
        if secondary_height is not None
        else None
    )
    return DocumentStyle(
        typography=TypographyStyle(
            font_name=font,
            height_mm=height,
            alignment=alignment,
            line_spacing=1.25,
        ),
        secondary_typography=secondary,
        shape=ShapeStyle(
            padding=Padding(top=top, right=right, bottom=bottom, left=left),
            corner_radius_mm=radius,
            border_thickness_mm=0.0 if filled else border,
            filled=filled,
            inverted=filled,
            start_cap=start_cap,
            end_cap=end_cap,
            feature_size_mm=0.8,
        ),
    )


def editable_settings(text, artwork, mode="Label", shape="Rounded rectangle", **extra):
    typography = artwork.document.style.typography
    shape_style = artwork.document.style.shape
    settings = {
        "MultiLineText": text,
        "FontComboBox": typography.font_name,
        "HeightCtrl": typography.height_mm,
        "LineSpacingCtrl": typography.line_spacing,
        "AlignmentChoice": typography.alignment.title(),
        "LayerComboBox": artwork.document.output_layer,
        "PaddingTopCtrl": shape_style.padding.top,
        "PaddingRightCtrl": shape_style.padding.right,
        "PaddingBottomCtrl": shape_style.padding.bottom,
        "PaddingLeftCtrl": shape_style.padding.left,
        "StudioModeChoice": mode,
        "ShapeChoice": shape,
        "ShapeVariantChoice": (
            "Inverted fill" if shape_style.filled else "Outline"
        ),
        "CornerRadiusCtrl": shape_style.corner_radius_mm,
        "BorderThicknessCtrl": shape_style.border_thickness_mm,
        "PresetLabelChoice": "Custom label",
        "IconChoice": "No icon",
        "ContentLayoutChoice": "Single text",
        "advancedCheckbox": False,
    }
    settings.update(extra)
    return settings


def place_artwork(board, artwork, position, settings, feature=None):
    payload = build_footprint_payload(
        settings,
        document=artwork.document,
        feature=feature,
    )
    encoded = base64.b64encode(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    footprint = COMPATIBILITY.parse_footprint(
        serialize_artwork(artwork, encoded, artwork.document.output_layer)
    )
    footprint.SetPosition(mm(*position))
    board.Add(footprint)
    return footprint


def add_label(
    board,
    vectorizer,
    text,
    position,
    *,
    output_layer=FRONT_SILKSCREEN,
    shape="rounded_rectangle",
    shape_label="Rounded rectangle",
    label_style=None,
    icon_id="",
    icon_position="left",
    icon_height=0.0,
    subtitle="",
):
    label_style = label_style or make_style()
    artwork = render_label_artwork(
        vectorizer,
        text,
        label_style,
        output_layer,
        shape=shape,
        icon_id=icon_id,
        icon_position=icon_position,
        icon_height_mm=icon_height,
        icon_gap_mm=0.35,
        subtitle_text=subtitle,
        subtitle_typography=label_style.secondary_typography,
        subtitle_gap_mm=0.25,
    )
    settings = editable_settings(
        text,
        artwork,
        shape=shape_label,
        IconPositionChoice={
            "left": "Left of text",
            "right": "Right of text",
            "only": "Icon only",
        }[icon_position],
        IconHeightCtrl=icon_height,
        IconGapCtrl=0.35,
        ContentLayoutChoice="Title + subtitle" if subtitle else "Single text",
        SubtitleCtrl=subtitle,
    )
    return place_artwork(board, artwork, position, settings)


def add_component_artwork(board, vectorizer, spec, position):
    artwork = render_component_callout_artwork(vectorizer, spec)
    is_array = spec.array_count > 1
    settings = editable_settings(
        spec.title,
        artwork,
        mode="Component Array" if is_array else "Component Callout",
        ComponentPresetChoice="Custom dimensions",
        ComponentPositionChoice={
            "left": "Left of text",
            "right": "Right of text",
            "above": "Above text",
            "below": "Below text",
        }[spec.component_position],
        ComponentWidthCtrl=spec.component_width_mm,
        ComponentHeightCtrl=spec.component_height_mm,
        ComponentClearanceCtrl=spec.component_clearance_mm,
        ComponentCutoutChoice={
            "rectangle": "Rectangle",
            "rounded_rectangle": "Rounded rectangle",
            "pill": "Pill / oval",
            "tactile_switch": "Legacy tactile switch contour",
        }[spec.cutout_shape],
        ComponentCutoutRadiusCtrl=spec.cutout_radius_mm,
        ComponentTextGapCtrl=spec.component_to_text_gap_mm,
        ComponentArrayCountCtrl=spec.array_count,
        ComponentArrayOrientationChoice=(
            "Vertical stack" if spec.array_orientation == "vertical" else "Horizontal row"
        ),
        ComponentArrayPitchCtrl=spec.array_pitch_mm,
    )
    return place_artwork(
        board,
        artwork,
        position,
        settings,
        {
            "kind": "component_array" if is_array else "component_callout",
            "data": spec.to_dict(),
        },
    )


def add_header_artwork(board, vectorizer, spec, position):
    artwork = render_header_artwork(vectorizer, spec)
    settings = editable_settings(
        "\n".join(spec.pin_labels),
        artwork,
        mode="2.54 mm Pin Header",
        HeaderPinCountCtrl=spec.pin_count,
        HeaderOrientationChoice=spec.orientation.title(),
        HeaderPin1Choice=spec.pin1_end.title(),
        HeaderPinSideChoice={
            "above": "Bottom",
            "below": "Top",
            "left": "Right",
            "right": "Left",
        }[spec.label_side],
        HeaderPadClearanceCtrl=spec.pad_clearance_mm,
        HeaderOpeningChoice={
            "none": "None",
            "continuous": "Continuous plug opening",
            "individual": "Individual pin openings",
        }[spec.opening_mode],
        HeaderPin1MarkerCheckbox=spec.pin1_marker,
    )
    return place_artwork(
        board,
        artwork,
        position,
        settings,
        {"kind": "pin_header_2_54", "data": spec.to_dict()},
    )


def add_machine_code(board, vectorizer, payload, position, kind, presentation="plain"):
    module = 0.35 if kind == "qr" else 0.20
    artwork = render_machine_code_artwork(
        payload=payload,
        kind=kind,
        module_size_mm=module,
        bar_height_mm=3.2,
        output_layer=FRONT_SILKSCREEN,
        vectorizer=vectorizer,
        presentation=presentation,
        caption_text="SCAN ME",
        caption_height_mm=1.1,
        frame_padding_mm=0.1,
    )
    settings = editable_settings(
        payload,
        artwork,
        mode="QR / Barcode",
        MachineCodeTypeChoice="QR Code" if kind == "qr" else "Code 128 barcode",
        MachineCodeModuleSizeCtrl=module,
        MachineCodeBarHeightCtrl=3.2,
        MachineCodePresentationChoice={
            "plain": "Plain code",
            "rounded_frame": "Rounded frame",
            "rounded_caption": "Rounded frame + footer",
        }[presentation],
        MachineCodeCaptionCtrl="SCAN ME",
    )
    return place_artwork(board, artwork, position, settings)


def load_part(board, library, name, reference, position, rotation=0):
    footprint = FOOTPRINT_IO.FootprintLoad(
        str(FOOTPRINT_ROOT / (library + ".pretty")),
        name,
    )
    if footprint is None:
        raise RuntimeError("Could not load {}:{}".format(library, name))
    footprint.SetReference(reference)
    footprint.SetPosition(mm(*position))
    footprint.SetOrientationDegrees(float(rotation))
    footprint.Reference().SetVisible(False)
    footprint.Value().SetVisible(False)
    board.Add(footprint)
    return footprint


def add_outline(board):
    corners = (
        (24, 20),
        (156, 20),
        (160, 24),
        (160, 111),
        (156, 115),
        (24, 115),
        (20, 111),
        (20, 24),
    )
    for start, end in zip(corners, corners[1:] + corners[:1]):
        segment = pcbnew.PCB_SHAPE(board)
        segment.SetShape(pcbnew.SHAPE_T_SEGMENT)
        segment.SetStart(mm(*start))
        segment.SetEnd(mm(*end))
        segment.SetLayer(pcbnew.Edge_Cuts)
        segment.SetWidth(pcbnew.FromMM(0.25))
        board.Add(segment)


def add_stackup_colours(board_path):
    text = board_path.read_text(encoding="utf-8")
    stackup = """\t\t(stackup
\t\t\t(layer "F.SilkS" (type "Top Silk Screen"))
\t\t\t(layer "F.Paste" (type "Top Solder Paste"))
\t\t\t(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01) (color "Black"))
\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01) (color "Black"))
\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))
\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen"))
\t\t\t(copper_finish "ENIG")
\t\t\t(dielectric_constraints no)
\t\t)
"""
    board_path.write_text(
        text.replace("\t(setup\n", "\t(setup\n" + stackup, 1),
        encoding="utf-8",
    )


def generate():
    board = pcbnew.BOARD()
    add_outline(board)
    vectorizer = TextVectorizer(TextGeometry().buzzard)

    for index, position in enumerate(((27, 27), (153, 27), (27, 108), (153, 108)), 1):
        load_part(board, "MountingHole", "MountingHole_3.2mm_M3", "H{}".format(index), position)

    add_label(
        board,
        vectorizer,
        "KOBEE STUDIO",
        (90, 29),
        label_style=make_style(5.4, padding=(1.4, 2.8, 1.3, 2.8), radius=1.4),
    )
    add_label(
        board,
        vectorizer,
        "PCB GRAPHICS, MADE FRIENDLY",
        (90, 38.2),
        shape=None,
        shape_label="No container",
        label_style=make_style(
            1.25,
            font="UbuntuMono-B",
            padding=(0, 0, 0, 0),
            filled=False,
        ),
    )

    section_style = make_style(
        1.05,
        font="UbuntuMono-B",
        alignment="left",
        padding=(0, 0, 0, 0),
        filled=False,
    )
    for title, position in (
        ("COMPONENT CALLOUTS", (29, 45.5)),
        ("LABELS + SYMBOLS", (77, 45.5)),
        ("MACHINE CODES", (132, 45.5)),
        ("2.54 MM CONNECTORS", (121, 84.5)),
    ):
        add_label(
            board,
            vectorizer,
            title,
            position,
            shape=None,
            shape_label="No container",
            label_style=section_style,
        )

    array_position = (34, 59)
    array_spec = ComponentCalloutSpec(
        title="STATUS\nNETWORK\nPOWER",
        preset_id="0603",
        component_width_mm=2.2,
        component_height_mm=1.1,
        component_clearance_mm=0.3,
        cutout_radius_mm=0.35,
        component_position="left",
        component_to_text_gap_mm=1.1,
        array_count=3,
        array_orientation="vertical",
        array_pitch_mm=6.0,
        shape="rounded_rectangle",
        style=make_style(
            1.7,
            alignment="left",
            padding=(0.8, 1.1, 0.8, 1.0),
            radius=1.0,
        ),
    )
    add_component_artwork(board, vectorizer, array_spec, array_position)
    for index, y in enumerate((53, 59, 65), 1):
        load_part(board, "LED_SMD", "LED_0603_1608Metric", "D{}".format(index), (34, y), 90)

    horizontal_array_position = (39, 72)
    horizontal_array_spec = ComponentCalloutSpec(
        title="RED\nGREEN\nBLUE",
        preset_id="0603",
        component_width_mm=2.2,
        component_height_mm=1.1,
        component_clearance_mm=0.3,
        cutout_radius_mm=0.35,
        component_position="above",
        component_to_text_gap_mm=0.6,
        array_count=3,
        array_orientation="horizontal",
        array_pitch_mm=8.0,
        shape="custom_long_edges",
        style=make_style(
            1.15,
            padding=(0.6, 0.8, 0.6, 0.8),
            radius=0.8,
            start_cap="rounded",
            end_cap="square",
        ),
    )
    add_component_artwork(
        board,
        vectorizer,
        horizontal_array_spec,
        horizontal_array_position,
    )
    for index, x in enumerate((31, 39, 47), 5):
        load_part(
            board,
            "LED_SMD",
            "LED_0603_1608Metric",
            "D{}".format(index),
            (x, 72),
            90,
        )

    switch_position = (34, 85)
    switch_spec = ComponentCalloutSpec(
        title="ACTION",
        preset_id="tactile_6",
        component_width_mm=8.0,
        component_height_mm=7.0,
        component_clearance_mm=0.3,
        cutout_shape="rounded_rectangle",
        cutout_radius_mm=0.7,
        component_position="left",
        component_to_text_gap_mm=2.0,
        shape="rounded_rectangle",
        style=make_style(
            2.35,
            alignment="right",
            padding=(1, 1, 1, 1),
            radius=1.0,
        ),
    )
    add_component_artwork(board, vectorizer, switch_spec, switch_position)
    load_part(board, "Button_Switch_THT", "SW_PUSH_6mm", "SW1", switch_position)

    large_led_position = (34, 100)
    large_led_spec = ComponentCalloutSpec(
        title="POWER LED",
        preset_id="1206",
        component_width_mm=4.5,
        component_height_mm=1.9,
        component_clearance_mm=0.3,
        cutout_radius_mm=0.4,
        component_position="left",
        component_to_text_gap_mm=1.5,
        shape="custom_ends",
        style=make_style(
            1.8,
            alignment="right",
            padding=(0.7, 1.2, 0.7, 1.0),
            start_cap="square",
            end_cap="rounded",
        ),
    )
    add_component_artwork(board, vectorizer, large_led_spec, large_led_position)
    load_part(board, "LED_SMD", "LED_1206_3216Metric", "D4", large_led_position, 90)

    add_label(
        board,
        vectorizer,
        "POWER",
        (80, 52),
        shape="pill",
        shape_label="Pill",
        icon_id="builtin.lightning",
        icon_height=2.0,
        label_style=make_style(1.45, padding=(0.6, 0.9, 0.6, 0.9)),
    )
    add_label(
        board,
        vectorizer,
        "WARNING",
        (101, 52),
        shape="custom_ends",
        shape_label="Independent ends",
        icon_id="builtin.warning",
        icon_height=2.0,
        label_style=make_style(
            1.35,
            padding=(0.6, 0.8, 0.6, 0.8),
            start_cap="chamfered",
            end_cap="chamfered",
        ),
    )
    add_label(
        board,
        vectorizer,
        "RESET",
        (80, 61),
        shape="custom_ends",
        shape_label="Independent ends",
        icon_id="builtin.reset",
        icon_height=1.9,
        label_style=make_style(
            1.4,
            padding=(0.6, 0.8, 0.6, 0.8),
            start_cap="notch",
            end_cap="point",
        ),
    )
    add_label(
        board,
        vectorizer,
        "OUTLINE",
        (101, 61),
        label_style=make_style(
            1.3,
            padding=(0.5, 0.8, 0.5, 0.8),
            radius=0.65,
            filled=False,
            border=0.28,
        ),
    )
    add_label(
        board,
        vectorizer,
        "GND",
        (80, 70),
        shape="pill",
        shape_label="Pill",
        icon_id="builtin.ground",
        icon_height=1.75,
        label_style=make_style(1.35, padding=(0.6, 0.9, 0.6, 0.9)),
    )
    add_label(
        board,
        vectorizer,
        "TEST",
        (101, 70),
        icon_id="builtin.test_point",
        icon_height=1.8,
        label_style=make_style(1.35, padding=(0.6, 0.9, 0.6, 0.9)),
    )
    add_label(
        board,
        vectorizer,
        "INPUT",
        (80, 79),
        shape="custom_ends",
        shape_label="Independent ends",
        icon_id="builtin.input",
        icon_height=1.7,
        label_style=make_style(
            1.25,
            padding=(0.6, 0.8, 0.6, 0.8),
            start_cap="square",
            end_cap="point",
        ),
    )
    add_label(
        board,
        vectorizer,
        "OUTPUT",
        (101, 79),
        shape="custom_ends",
        shape_label="Independent ends",
        icon_id="builtin.output",
        icon_position="right",
        icon_height=1.7,
        label_style=make_style(
            1.25,
            padding=(0.6, 0.8, 0.6, 0.8),
            start_cap="point",
            end_cap="square",
        ),
    )
    add_label(
        board,
        vectorizer,
        "MAIN POWER",
        (90, 101),
        subtitle="5V INPUT",
        label_style=make_style(
            2.0,
            alignment="left",
            padding=(0.8, 1.3, 0.8, 1.3),
            radius=0.9,
            secondary_height=0.9,
        ),
    )

    for icon_id, position in (
        ("builtin.positive", (68, 89)),
        ("builtin.negative", (76, 89)),
        ("builtin.battery", (84, 89)),
        ("builtin.light_bulb", (92, 89)),
        ("builtin.power_button", (100, 89)),
        ("builtin.push_button", (108, 89)),
    ):
        add_label(
            board,
            vectorizer,
            "",
            position,
            shape=None,
            shape_label="No container",
            icon_id=icon_id,
            icon_position="only",
            icon_height=3.0,
            label_style=make_style(1.0, padding=(0, 0, 0, 0), filled=False),
        )

    add_machine_code(
        board,
        vectorizer,
        "https://www.coreybusuttil.com",
        (136, 61),
        "qr",
        "rounded_caption",
    )
    add_machine_code(board, vectorizer, "KOBEE-STUDIO", (135, 76.5), "code128")

    header_style = make_style(
        1.25,
        font="UbuntuMono-B",
        alignment="right",
        padding=(0, 0, 0, 0),
        radius=0.8,
    )
    vertical_header = PinHeaderSpec(
        pin_count=4,
        pin_labels=("VCC", "SDA", "SCL", "GND"),
        orientation="vertical",
        label_side="right",
        opening_mode="individual",
        pad_clearance_mm=2.0,
        pin_outer_padding_mm=0.45,
        pin_to_label_gap_mm=0.7,
        label_outer_padding_mm=0.8,
        leading_padding_mm=0.5,
        trailing_padding_mm=0.5,
        label_padding_mm=0.3,
        pin1_marker=True,
        shape="custom_long_edges",
        style=replace(
            header_style,
            shape=replace(header_style.shape, start_cap="square", end_cap="rounded"),
        ),
    )
    add_header_artwork(board, vectorizer, vertical_header, (112, 89))
    load_part(
        board,
        "Connector_PinHeader_2.54mm",
        "PinHeader_1x04_P2.54mm_Vertical",
        "J1",
        (112, 89),
    )

    horizontal_header = PinHeaderSpec(
        pin_count=5,
        pin_labels=("1", "2", "3", "4", "5"),
        orientation="horizontal",
        label_side="below",
        opening_mode="continuous",
        pad_clearance_mm=2.0,
        pin_outer_padding_mm=0.4,
        pin_to_label_gap_mm=0.6,
        label_outer_padding_mm=0.7,
        leading_padding_mm=0.5,
        trailing_padding_mm=0.5,
        label_padding_mm=0.3,
        pin1_marker=True,
        shape="rounded_rectangle",
        style=header_style,
    )
    add_header_artwork(board, vectorizer, horizontal_header, (130, 102))
    load_part(
        board,
        "Connector_PinHeader_2.54mm",
        "PinHeader_1x05_P2.54mm_Vertical",
        "J2",
        (130, 102),
        90,
    )

    copper_style = make_style(1.2, padding=(0.5, 1.0, 0.5, 1.0), radius=0.6)
    for layer in (FRONT_COPPER, FRONT_MASK):
        add_label(
            board,
            vectorizer,
            "COPPER + MASK",
        (82, 111),
            output_layer=layer,
            label_style=copper_style,
        )

    add_label(
        board,
        vectorizer,
        "BUILT WITH KOBEE STUDIO",
        (90, 40),
        output_layer=BOTTOM_SILKSCREEN,
        label_style=make_style(
            3.5,
            padding=(1.0, 2.0, 1.0, 2.0),
            radius=1.0,
        ),
    )
    add_label(
        board,
        vectorizer,
        "BOTTOM SILK",
        (57, 60),
        output_layer=BOTTOM_SILKSCREEN,
        shape="pill",
        shape_label="Pill",
        icon_id="builtin.power_button",
        icon_height=2.2,
        label_style=make_style(1.8, padding=(0.8, 1.2, 0.8, 1.2)),
    )
    back_style = make_style(1.3, padding=(0.5, 1.0, 0.5, 1.0), radius=0.5)
    for layer in (BOTTOM_COPPER, BOTTOM_MASK):
        add_label(
            board,
            vectorizer,
            "BOTTOM COPPER + MASK",
            (115, 60),
            output_layer=layer,
            label_style=back_style,
        )
    add_label(
        board,
        vectorizer,
        "OUTLINE",
        (57, 77),
        output_layer=BOTTOM_SILKSCREEN,
        label_style=make_style(
            1.5,
            padding=(0.6, 1.0, 0.6, 1.0),
            radius=0.7,
            filled=False,
            border=0.28,
        ),
    )
    for icon_id, position in (
        ("builtin.warning", (88, 77)),
        ("builtin.ground", (100, 77)),
        ("builtin.battery", (112, 77)),
        ("builtin.centre_positive", (126, 77)),
    ):
        add_label(
            board,
            vectorizer,
            "",
            position,
            output_layer=BOTTOM_SILKSCREEN,
            shape=None,
            shape_label="No container",
            icon_id=icon_id,
            icon_position="only",
            icon_height=3.6,
            label_style=make_style(1.0, padding=(0, 0, 0, 0), filled=False),
        )
    add_label(
        board,
        vectorizer,
        "COREYBUSUTTIL.COM",
        (90, 100),
        output_layer=BOTTOM_SILKSCREEN,
        shape=None,
        shape_label="No container",
        label_style=make_style(
            1.2,
            font="UbuntuMono-B",
            padding=(0, 0, 0, 0),
            filled=False,
        ),
    )

    pcbnew.SaveBoard(str(BOARD_PATH), board)
    add_stackup_colours(BOARD_PATH)
    # Reparse once so KiCad expands the compact stackup block into its
    # canonical form. The CLI 3D renderer expects those typed fields.
    pcbnew.SaveBoard(str(BOARD_PATH), pcbnew.LoadBoard(str(BOARD_PATH)))
    print("Wrote {}".format(BOARD_PATH))


if __name__ == "__main__":
    generate()

"""Place and update a real Kobee Studio label through a running KiCad IPC API.

This intentionally targets a disposable board. It exercises the same geometry,
metadata, footprint construction, transaction, create, select, and update path
used by the IPC plugin action.
"""

from __future__ import annotations

import argparse
import json

from kobeestudio.core.composition import DocumentStyle, Padding, ShapeStyle, TypographyStyle
from kobeestudio.core.legacy_adapter import build_footprint_payload
from kobeestudio.core.studio_artwork import TextVectorizer, render_label_artwork
from kobeestudio.core.text_geometry import TextGeometry
from kobeestudio.integration.ipc_artwork import IpcArtworkPlacement, selected_artwork
from kobeestudio.integration.ipc_session import IpcSession


def _artwork(text: str):
    style = DocumentStyle(
        typography=TypographyStyle(
            font_name="FreddySpark-Regular",
            height_mm=1.2,
            line_spacing=1.5,
            alignment="center",
        ),
        shape=ShapeStyle(
            padding=Padding(top=0.5, right=1.2, bottom=0.5, left=1.2),
            corner_radius_mm=0.2,
            filled=True,
            inverted=True,
        ),
    )
    vectorizer = TextVectorizer(TextGeometry().buzzard)
    return render_label_artwork(
        vectorizer,
        text,
        style,
        "F.SilkS",
        shape="rounded_rectangle",
    )


def _payload(text: str, artwork):
    return build_footprint_payload(
        {
            "MultiLineText": text,
            "HeightCtrl": "1.2",
            "LayerComboBox": "F.SilkS",
            "StudioModeChoice": "Label",
            "ShapeChoice": "Rounded rectangle",
        },
        document=artwork.document,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True, help="PCB Editor IPC URL")
    args = parser.parse_args()

    session = IpcSession.connect(
        socket_path=args.socket,
        kicad_token="",
        client_name="Kobee Studio end-to-end test",
    )
    placement = IpcArtworkPlacement(session)
    before = len(session.board.get_footprints())

    existing_selection = list(session.board.get_selection())
    if existing_selection:
        session.board.remove_from_selection(existing_selection)
    legacy_candidates = [
        footprint
        for footprint in session.board.get_footprints()
        if "kobee-studio" in footprint.reference_field.text.value.lower()
        and selected_artwork([footprint]) is None
    ]
    legacy_text = None
    if legacy_candidates:
        session.board.add_to_selection(legacy_candidates[0])
        reopened_legacy = session.selected_artwork()
        if reopened_legacy is None:
            raise RuntimeError("A selected released SWIG footprint did not reopen through IPC")
        legacy_text = reopened_legacy[0].get("MultiLineText")
        session.board.remove_from_selection(legacy_candidates[0])

    first_artwork = _artwork("IPC TEST")
    placed = placement.place(first_artwork, _payload("IPC TEST", first_artwork), "F.SilkS")
    after_place = len(session.board.get_footprints())
    if placed is None or after_place != before + 1:
        raise RuntimeError("IPC placement did not add exactly one footprint")

    reopened = selected_artwork([placed])
    if reopened is None or reopened[0].get("MultiLineText") != "IPC TEST":
        raise RuntimeError("Placed IPC artwork did not preserve editable metadata")

    updated_artwork = _artwork("IPC UPDATED")
    updated = placement.place(
        updated_artwork,
        _payload("IPC UPDATED", updated_artwork),
        "F.SilkS",
        old_footprint=placed,
    )
    after_update = len(session.board.get_footprints())
    if updated is None or after_update != after_place:
        raise RuntimeError("IPC update did not replace the original footprint in place")

    reopened_update = selected_artwork([updated])
    if reopened_update is None or reopened_update[0].get("MultiLineText") != "IPC UPDATED":
        raise RuntimeError("Updated IPC artwork did not preserve the new metadata")

    print(
        json.dumps(
            {
                "board": session.board.document.board_filename,
                "footprints_before": before,
                "footprints_after_place": after_place,
                "footprints_after_update": after_update,
                "placed_text": reopened[0]["MultiLineText"],
                "updated_text": reopened_update[0]["MultiLineText"],
                "legacy_text_reopened": legacy_text,
                "result": "passed",
            },
            indent=2,
        )
    )
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

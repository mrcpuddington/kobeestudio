"""Regression checks for the isolated KiCad IPC migration foundation."""

from __future__ import annotations

import json
import importlib.util
import struct
import unittest
from pathlib import Path

from kobeestudio.core.composition import CompositionDocument
from kobeestudio.core.shape_geometry import Point
from kobeestudio.core.studio_artwork import StudioArtwork, StrokePath
from kobeestudio.integration.ipc_artwork import (
    METADATA_FIELD_NAME,
    artwork_polygons,
    decode_metadata,
    encode_metadata,
    selected_artwork,
    selected_legacy_artwork,
    IpcArtworkPlacement,
)
from kobeestudio.integration.ipc_session import IpcSession, IpcUnavailableError


ROOT = Path(__file__).resolve().parents[1]


class _Board:
    def __init__(self):
        self.commit = object()
        self.messages = []

    def get_selection(self):
        return ["selected"]

    def begin_commit(self):
        return self.commit

    def push_commit(self, transaction, message):
        self.messages.append(("push", transaction, message))

    def drop_commit(self, transaction):
        self.messages.append(("drop", transaction))


class _Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.board = _Board()
        self.closed = False

    def get_board(self):
        return self.board

    def get_version(self):
        return "10.0.5"

    def close(self):
        self.closed = True


class IpcMigrationTests(unittest.TestCase):
    def test_manifest_declares_supported_ipc_runtime(self):
        manifest = json.loads((ROOT / "ipc_plugin/plugin.json").read_text())
        self.assertEqual("https://go.kicad.org/api/schemas/v1", manifest["$schema"])
        self.assertEqual(
            "com.github.mrcpuddington.kobeestudio",
            manifest["identifier"],
        )
        self.assertEqual("python", manifest["runtime"]["type"])
        self.assertIn("IPC Development", manifest["name"])
        action = manifest["actions"][0]
        self.assertEqual("kobeestudio_ipc.py", action["entrypoint"])
        self.assertEqual(["pcb"], action["scopes"])
        self.assertIn("IPC DEV", action["name"])
        expected_icons = ["kobee-toolbar-24.png", "kobee-toolbar-48.png"]
        self.assertEqual(expected_icons, action["icons-light"])
        self.assertEqual(expected_icons, action["icons-dark"])
        for icon_name, expected_size in zip(expected_icons, (24, 48)):
            icon_path = ROOT / "ipc_plugin" / icon_name
            icon_data = icon_path.read_bytes()
            self.assertEqual(b"\x89PNG\r\n\x1a\n", icon_data[:8])
            self.assertEqual(
                (expected_size, expected_size),
                struct.unpack(">II", icon_data[16:24]),
            )

    def test_pcm_metadata_matches_ipc_manifest_and_catalog_icon_rules(self):
        manifest = json.loads((ROOT / "ipc_plugin/plugin.json").read_text())
        metadata = json.loads((ROOT / "pcm/metadata_template.json").read_text())
        self.assertEqual(manifest["identifier"], metadata["identifier"])
        self.assertEqual("ipc", metadata["versions"][0]["runtime"])
        self.assertEqual("development", metadata["versions"][0]["status"])
        self.assertEqual("1.3.0", metadata["versions"][0]["version"])
        icon_data = (ROOT / "pcm/resources/icon.png").read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", icon_data[:8])
        self.assertEqual((64, 64), struct.unpack(">II", icon_data[16:24]))

    def test_pcm_builder_places_ipc_manifest_directly_under_plugins(self):
        source = (ROOT / "pcm/build.py").read_text()
        self.assertIn('PLUGINS / filename', source)
        self.assertIn('"plugin.json"', source)
        self.assertNotIn("plugins_path, 'kobeestudio', 'plugin.json'", source)

    def test_ipc_session_uses_the_connection_details_from_kicad(self):
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "/tmp/api.sock", "KICAD_API_TOKEN": "secret"},
            client_factory=_Client,
        )
        self.assertEqual("/tmp/api.sock", session.kicad.kwargs["socket_path"])
        self.assertEqual("secret", session.kicad.kwargs["kicad_token"])
        self.assertEqual(["selected"], session.selected_items())
        transaction = session.begin_commit()
        session.commit(transaction, "Place Kobee Studio artwork")
        self.assertEqual(
            [("push", transaction, "Place Kobee Studio artwork")], session.board.messages
        )
        session.close()
        self.assertTrue(session.kicad.closed)

    def test_development_connection_accepts_kicads_empty_external_token(self):
        session = IpcSession.connect(
            environ={"KICAD_API_SOCKET": "ipc:///tmp/kicad/api.sock", "KICAD_API_TOKEN": ""},
            client_factory=_Client,
        )
        self.assertEqual("", session.kicad.kwargs["kicad_token"])

    def test_ipc_session_fails_clearly_outside_kicad(self):
        with self.assertRaises(IpcUnavailableError):
            IpcSession.connect(environ={}, client_factory=_Client)

    def test_front_and_bottom_artwork_use_the_existing_mirror_rule(self):
        polygon = (Point(-2.0, -1.0), Point(1.0, -1.0), Point(1.0, 2.0))
        artwork = StudioArtwork(
            filled_polygons=(polygon,),
            strokes=(StrokePath(polygon, 0.2),),
            guides=(),
            document=CompositionDocument(objects=()),
        )
        front = artwork_polygons(artwork, "F.SilkS")
        bottom = artwork_polygons(artwork, "B.SilkS")
        self.assertEqual(polygon, front[0].points)
        self.assertEqual(tuple(Point(-p.x, p.y) for p in reversed(polygon)), bottom[0].points)
        self.assertTrue(front[0].filled)
        self.assertFalse(front[1].filled)
        self.assertEqual(0.2, front[1].stroke_width_mm)

    def test_metadata_round_trip_reopens_selected_artwork(self):
        payload = {
            "format": "kobee-studio-composition",
            "legacy_settings": {"MultiLineText": "POWER", "HeightCtrl": "1.2"},
        }
        self.assertEqual(payload, decode_metadata(encode_metadata(payload)))

        class Text:
            value = encode_metadata(payload)

        class Field:
            name = METADATA_FIELD_NAME
            text = Text()

        class Definition:
            items = [Field()]

        class Footprint:
            definition = Definition()

        loaded, footprint = selected_artwork([Footprint()])
        self.assertEqual("POWER", loaded["MultiLineText"])
        self.assertTrue(loaded["_LoadedFootprintSettings"])
        self.assertIsInstance(footprint, Footprint)

    def test_released_swig_footprint_metadata_opens_through_ipc(self):
        payload = {
            "format": "kobee-studio-composition",
            "legacy_settings": {"MultiLineText": "OLD LABEL", "StudioModeChoice": "Label"},
        }
        footprint = object()
        sexpr = '(footprint "kobee-studio" (tags "kb_params={}"))'.format(
            encode_metadata(payload)
        )
        loaded, selected = selected_legacy_artwork([footprint], sexpr)
        self.assertEqual("OLD LABEL", loaded["MultiLineText"])
        self.assertTrue(loaded["_LoadedFootprintSettings"])
        self.assertIs(footprint, selected)

    @unittest.skipUnless(importlib.util.find_spec("kipy"), "kicad-python is not installed")
    def test_real_kicad_python_wrappers_build_an_ipc_footprint(self):
        polygon = (Point(-1.0, -0.5), Point(1.0, -0.5), Point(0.0, 0.5))
        artwork = StudioArtwork(
            filled_polygons=(polygon,),
            strokes=(),
            guides=(),
            document=CompositionDocument(objects=()),
        )
        placement = IpcArtworkPlacement(session=None)
        footprint = placement.build_footprint(
            artwork,
            {"format": "kobee-studio-composition", "legacy_settings": {}},
            "F.SilkS",
        )
        self.assertEqual(2, len(footprint.definition.items))
        self.assertEqual(METADATA_FIELD_NAME, footprint.definition.items[-1].name)
        self.assertTrue(footprint.attributes.not_in_schematic)
        self.assertGreater(footprint.proto.ByteSize(), 0)


if __name__ == "__main__":
    unittest.main()

"""Pin labels pulled out of a selected connector footprint."""

from __future__ import annotations

import unittest

from kobeestudio.core.connector_labels import looks_like_connector, numbered_pad_labels
from kobeestudio.integration.ipc_selection import selected_connector_labels


class FakeNet:
    def __init__(self, name):
        self.name = name


class FakePad:
    def __init__(self, number, net=""):
        self.number = number
        self.net = FakeNet(net)


class FakeIdentifier:
    def __init__(self, library="", name=""):
        self.library = library
        self.name = name


class FakeDefinition:
    def __init__(self, items=(), library="", name=""):
        self.items = list(items)
        self.id = FakeIdentifier(library, name)


class FakeFootprint:
    def __init__(self, pads=(), library="", name="", items=()):
        self.definition = FakeDefinition(items=list(pads) + list(items), library=library, name=name)


class FakeField:
    def __init__(self, name):
        self.name = name


def labels_of_selection(labels):
    return list(labels) if labels is not None else None


def labels_of(pads):
    """Test helper: unwrap the optional result without narrowing noise."""
    labels = numbered_pad_labels(pads)
    return list(labels) if labels is not None else None


class FakeSession:
    def __init__(self, selection):
        self._selection = selection

    def selected_items(self):
        return list(self._selection)


def header_footprint(labels, library="Connector", name="PinHeader_1x04_P2.54mm_Vertical"):
    pads = [FakePad(str(index + 1), label) for index, label in enumerate(labels)]
    return FakeFootprint(pads=pads, library=library, name=name)


class NumberedPadLabelTests(unittest.TestCase):
    def test_wired_header_yields_net_names_in_pin_order(self):
        footprint = header_footprint(["+3.3V", "RX_MCU", "TX_MCU", "GND"])
        self.assertEqual(
            labels_of(footprint.definition.items),
            ["+3.3V", "RX_MCU", "TX_MCU", "GND"],
        )

    def test_order_follows_pad_numbers_not_item_order(self):
        pads = [FakePad("3", "TX"), FakePad("1", "VCC"), FakePad("2", "RX")]
        self.assertEqual(labels_of(pads), ["VCC", "RX", "TX"])

    def test_unconnected_pads_fall_back_to_pin_numbers(self):
        pads = [FakePad("1", "VCC"), FakePad("2", ""), FakePad("3", "unconnected-(J8-Pad3)")]
        self.assertEqual(labels_of(pads), ["VCC", "Pin 2", "Pin 3"])

    def test_hierarchical_net_keeps_the_leaf_name(self):
        pads = [FakePad("1", "/uart/RX"), FakePad("2", "/uart/TX")]
        self.assertEqual(labels_of(pads), ["RX", "TX"])

    def test_gapped_numbers_are_not_a_pin_row(self):
        pads = [FakePad("1", "A"), FakePad("2", "B"), FakePad("4", "C")]
        self.assertIsNone(numbered_pad_labels(pads))

    def test_single_pad_is_not_a_header(self):
        self.assertIsNone(numbered_pad_labels([FakePad("1", "A")]))

    def test_alphanumeric_pads_are_rejected(self):
        pads = [FakePad("A1", "D+"), FakePad("A2", "D-")]
        self.assertIsNone(numbered_pad_labels(pads))

    def test_duplicate_numbers_are_rejected(self):
        pads = [FakePad("1", "A"), FakePad("1", "B")]
        self.assertIsNone(numbered_pad_labels(pads))

    def test_empty_pad_list_is_rejected(self):
        self.assertIsNone(numbered_pad_labels([]))


class ConnectorDetectionTests(unittest.TestCase):
    def test_library_name_identifies_a_connector(self):
        footprint = header_footprint(["A", "B"])
        self.assertTrue(looks_like_connector(footprint))

    def test_passive_footprint_is_not_a_connector(self):
        footprint = FakeFootprint(
            pads=[FakePad("1", "N1"), FakePad("2", "N2")],
            library="Device",
            name="R_0603_1608Metric",
        )
        self.assertFalse(looks_like_connector(footprint))


class SelectedConnectorTests(unittest.TestCase):
    def test_single_selected_connector_is_read(self):
        session = FakeSession([header_footprint(["+3.3V", "RX_MCU", "TX_MCU", "GND"])])
        self.assertEqual(
            labels_of_selection(selected_connector_labels(session)),
            ["+3.3V", "RX_MCU", "TX_MCU", "GND"],
        )

    def test_empty_selection_returns_none(self):
        self.assertIsNone(selected_connector_labels(FakeSession([])))

    def test_multiple_selection_returns_none(self):
        session = FakeSession([header_footprint(["A", "B"]), header_footprint(["C", "D"])])
        self.assertIsNone(selected_connector_labels(session))

    def test_kobee_artwork_is_left_to_the_artwork_editor(self):
        artwork = header_footprint(["A", "B"], library="Kobee", name="kobee-studio-1")
        artwork.definition.items.append(FakeField("KOBEE_STUDIO_DATA"))
        self.assertIsNone(selected_connector_labels(FakeSession([artwork])))

    def test_non_connector_selection_returns_none(self):
        resistor = FakeFootprint(
            pads=[FakePad("1", "N1"), FakePad("2", "N2")],
            library="Device",
            name="R_0603_1608Metric",
        )
        self.assertIsNone(selected_connector_labels(FakeSession([resistor])))


if __name__ == "__main__":
    unittest.main()

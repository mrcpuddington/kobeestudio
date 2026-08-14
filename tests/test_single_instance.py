"""Unit coverage for the cross-process Studio window guard."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import socket

from kobeestudio.ui.single_instance import StudioWindowSingleton


class StudioWindowSingletonTests(unittest.TestCase):
    class _Socket:
        next_port = 42000

        def __init__(self, *_args, **_kwargs):
            self.port = type(self).next_port
            type(self).next_port += 1
            self.closed = False

        def setsockopt(self, *_args):
            pass

        def bind(self, *_args):
            pass

        def listen(self, *_args):
            pass

        def settimeout(self, *_args):
            pass

        def getsockname(self):
            return ("127.0.0.1", self.port)

        def accept(self):
            raise socket.timeout()

        def close(self):
            self.closed = True

    def test_second_instance_activates_the_first_and_does_not_acquire(self):
        with tempfile.TemporaryDirectory() as directory:
            first = StudioWindowSingleton(Path(directory))
            with patch("kobeestudio.ui.single_instance.socket.socket", self._Socket):
                self.assertTrue(first.acquire_or_activate())
                activated = threading.Event()
                first.attach(activated.set)
                second = StudioWindowSingleton(Path(directory))
                try:
                    with patch.object(
                        StudioWindowSingleton,
                        "_send_activation",
                        side_effect=lambda _metadata: (first._dispatch_activation() or True),
                    ):
                        self.assertFalse(second.acquire_or_activate())
                    self.assertTrue(activated.wait(1.0))
                finally:
                    second.release()
                    first.release()

    def test_releases_the_lock_for_a_later_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            first = StudioWindowSingleton(Path(directory))
            with patch("kobeestudio.ui.single_instance.socket.socket", self._Socket):
                self.assertTrue(first.acquire_or_activate())
                first.release()
                later = StudioWindowSingleton(Path(directory))
                try:
                    self.assertTrue(later.acquire_or_activate())
                finally:
                    later.release()

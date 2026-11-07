"""Run all checks with the wx application required by KiCad's font renderer.

Use KiCad's Python on macOS/Windows, or xvfb-run and wxPython on Linux.
The IPC requirements must be installed in the selected environment.
"""

import sys
import unittest
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import wx

    app = wx.App(False)
    # Headless runners have no user to dismiss wx's default log dialog.
    wx.Log.SetActiveTarget(wx.LogStderr())
    # Fail assertions as test errors instead of opening a modal native dialog
    # that can block a CI worker indefinitely.
    app.SetAssertMode(wx.APP_ASSERT_EXCEPTION)
    names = sys.argv[1:]
    suite = (unittest.defaultTestLoader.loadTestsFromNames(names) if names else
             unittest.defaultTestLoader.discover(str(ROOT / "tests")))
    # wx reports Python event-handler exceptions through sys.excepthook rather
    # than raising into unittest. Otherwise a broken UI callback can print a
    # traceback while the suite still misleadingly reports OK.
    event_errors = []
    previous_hook = sys.excepthook

    def record_event_error(kind, error, stack):
        event_errors.append(error)
        traceback.print_exception(kind, error, stack)

    sys.excepthook = record_event_error
    try:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        wx.Yield()
    finally:
        sys.excepthook = previous_hook
    if event_errors:
        print("FAILED: {} unhandled UI callback exception(s)".format(len(event_errors)), file=sys.stderr)
    return 0 if result.wasSuccessful() and not event_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

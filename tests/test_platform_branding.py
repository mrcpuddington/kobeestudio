import unittest
from pathlib import Path

from kobeestudio.integration.platform_branding import (
    APP_NAME,
    APP_USER_MODEL_ID,
    APP_VENDOR,
    configure_application_branding,
    configure_process_identity,
    configure_window_branding,
)


class _Shell32:
    def __init__(self, result=0):
        self.result = result
        self.identifiers = []

    def SetCurrentProcessExplicitAppUserModelID(self, identifier):
        self.identifiers.append(identifier)
        return self.result


class _App:
    def __init__(self):
        self.name = None
        self.vendor = None
        self.display_name = None

    def SetAppName(self, value):
        self.name = value

    def SetVendorName(self, value):
        self.vendor = value

    def SetAppDisplayName(self, value):
        self.display_name = value


class _Icon:
    def __init__(self, path, image_type):
        self.path = path
        self.image_type = image_type

    def IsOk(self):
        return True


class _Wx:
    BITMAP_TYPE_PNG = 15
    Icon = _Icon


class _Window:
    def __init__(self):
        self.icon = None

    def SetIcon(self, icon):
        self.icon = icon


class PlatformBrandingTests(unittest.TestCase):
    def test_windows_process_identity_uses_package_identifier(self):
        shell = _Shell32()
        self.assertTrue(configure_process_identity("win32", shell))
        self.assertEqual([APP_USER_MODEL_ID], shell.identifiers)

    def test_non_windows_process_does_not_call_shell(self):
        shell = _Shell32()
        self.assertFalse(configure_process_identity("darwin", shell))
        self.assertEqual([], shell.identifiers)

    def test_application_names_are_branded(self):
        app = _App()
        self.assertTrue(
            configure_application_branding(app, Path("icon.png"), "linux")
        )
        self.assertEqual(APP_NAME, app.name)
        self.assertEqual(APP_NAME, app.display_name)
        self.assertEqual(APP_VENDOR, app.vendor)

    def test_window_receives_png_icon(self):
        window = _Window()
        self.assertTrue(configure_window_branding(window, Path("icon.png"), _Wx))
        self.assertEqual("icon.png", window.icon.path)
        self.assertEqual(_Wx.BITMAP_TYPE_PNG, window.icon.image_type)


if __name__ == "__main__":
    unittest.main()

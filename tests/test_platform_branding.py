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


class _BundleImage:
    def __init__(self, path, image_type, sizes=None):
        self.path = path
        self.image_type = image_type
        self.sizes = sizes if sizes is not None else []

    def IsOk(self):
        return True

    def Copy(self):
        return _BundleImage(self.path, self.image_type)

    def Rescale(self, width, height, quality):
        self.sizes.append((width, height, quality))


class _BundleIcon:
    def __init__(self):
        self.bitmap = None

    def CopyFromBitmap(self, bitmap):
        self.bitmap = bitmap


class _IconBundle:
    def __init__(self):
        self.icons = []

    def AddIcon(self, icon):
        self.icons.append(icon)


class _BundleWx:
    BITMAP_TYPE_PNG = 15
    IMAGE_QUALITY_HIGH = 30
    Image = _BundleImage
    Icon = _BundleIcon
    IconBundle = _IconBundle

    @staticmethod
    def Bitmap(image):
        return image


class _BundleWindow:
    def __init__(self):
        self.icons = None

    def SetIcons(self, icons):
        self.icons = icons


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

    def test_window_receives_platform_size_icon_bundle(self):
        window = _BundleWindow()
        self.assertTrue(
            configure_window_branding(window, Path("platform-icon.png"), _BundleWx)
        )
        self.assertEqual(7, len(window.icons.icons))
        self.assertEqual(
            [16, 24, 32, 48, 64, 128, 256],
            [icon.bitmap.sizes[-1][0] for icon in window.icons.icons],
        )


if __name__ == "__main__":
    unittest.main()

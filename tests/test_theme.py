import unittest

from kobeestudio.ui.theme import is_dark_mode, set_appearance_preference


class _Appearance:
    def __init__(self, dark):
        self._dark = dark

    def IsDark(self):
        return self._dark


class _SystemSettings:
    dark = False

    @classmethod
    def GetAppearance(cls):
        return _Appearance(cls.dark)


class _Wx:
    SystemSettings = _SystemSettings


class ThemeTests(unittest.TestCase):
    def tearDown(self):
        set_appearance_preference("system")

    def test_explicit_user_preference_overrides_the_platform(self):
        _SystemSettings.dark = False
        set_appearance_preference("dark")
        self.assertTrue(is_dark_mode(_Wx, platform_name="darwin"))
        set_appearance_preference("light")
        _SystemSettings.dark = True
        self.assertFalse(is_dark_mode(_Wx, platform_name="darwin"))

    def test_windows_uses_application_theme_setting_before_wx(self):
        _SystemSettings.dark = False
        self.assertTrue(
            is_dark_mode(
                _Wx,
                platform_name="win32",
                windows_apps_use_light=False,
            )
        )
        _SystemSettings.dark = True
        self.assertFalse(
            is_dark_mode(
                _Wx,
                platform_name="win32",
                windows_apps_use_light=True,
            )
        )

    def test_macos_uses_wx_appearance_like_kicad(self):
        _SystemSettings.dark = True
        self.assertTrue(is_dark_mode(_Wx, platform_name="darwin"))
        _SystemSettings.dark = False
        self.assertFalse(is_dark_mode(_Wx, platform_name="darwin"))

    def test_linux_falls_back_to_gtk_theme(self):
        self.assertTrue(
            is_dark_mode(
                None,
                platform_name="linux",
                environment={"GTK_THEME": "Adwaita:dark"},
            )
        )


if __name__ == "__main__":
    unittest.main()

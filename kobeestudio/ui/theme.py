"""KiCad-aligned light/dark appearance detection for standalone plugin UI."""

from __future__ import annotations

import os
import sys
from typing import Any, Mapping, Optional


_appearance_preference = "system"


def set_appearance_preference(value: str) -> None:
    global _appearance_preference
    value = str(value).strip().lower()
    if value not in ("system", "light", "dark"):
        raise ValueError("Appearance must be system, light, or dark")
    _appearance_preference = value


def _windows_apps_use_light_theme() -> Optional[bool]:
    """Read the Windows application-theme preference used by desktop apps."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return bool(int(value))
    except (ImportError, OSError, TypeError, ValueError):
        return None


def is_dark_mode(
    wx_module: Optional[Any] = None,
    *,
    platform_name: Optional[str] = None,
    environment: Optional[Mapping[str, str]] = None,
    windows_apps_use_light: Optional[bool] = None,
    appearance: Optional[str] = None,
) -> bool:
    """Return the same OS-level dark preference KiCad uses for its UI chrome.

    Kobee Studio's IPC editor is a separate process, so wx can occasionally
    miss the Windows application-theme value.  Reading that preference first
    on Windows keeps the plugin visually aligned with KiCad.  wx remains the
    authoritative source on macOS and the normal source on Linux.
    """
    appearance = str(appearance or _appearance_preference).strip().lower()
    if appearance == "dark":
        return True
    if appearance == "light":
        return False
    if appearance != "system":
        raise ValueError("Appearance must be system, light, or dark")
    platform_name = platform_name or sys.platform
    environment = environment if environment is not None else os.environ

    if platform_name.startswith("win"):
        use_light = (
            windows_apps_use_light
            if windows_apps_use_light is not None
            else _windows_apps_use_light_theme()
        )
        if use_light is not None:
            return not use_light

    if wx_module is not None:
        try:
            return bool(wx_module.SystemSettings.GetAppearance().IsDark())
        except (AttributeError, RuntimeError):
            pass

    if platform_name.startswith("linux"):
        gtk_theme = str(environment.get("GTK_THEME", "")).lower()
        if gtk_theme:
            return "dark" in gtk_theme

    return False


def apply_native_theme(root: Any, wx_module: Any, palette: Mapping[str, Any]) -> None:
    """Apply readable colours to native controls in the standalone IPC app."""
    text_colour = palette["text"]
    field_colour = palette.get("active", palette.get("surface"))
    control_types = [
        wx_module.TextCtrl,
        wx_module.SearchCtrl,
        wx_module.Choice,
        wx_module.SpinCtrl,
        wx_module.SpinCtrlDouble,
    ]
    list_types = tuple(
        item for item in (
            getattr(wx_module, "ListCtrl", None),
            getattr(wx_module, "ListBox", None),
            getattr(wx_module, "CheckListBox", None),
        ) if item is not None
    )
    combo_box = getattr(wx_module, "ComboBox", None)
    if combo_box is not None:
        control_types.append(combo_box)
    control_types = tuple(control_types)

    for child in root.GetChildren():
        try:
            if isinstance(child, wx_module.StaticText):
                child.SetForegroundColour(text_colour)
            elif isinstance(child, control_types):
                # Cocoa can ignore inherited colours for editable native
                # controls. Setting both the local and own colour paths makes
                # dark fields reliable on macOS while retaining the normal
                # platform fallback where a port rejects explicit colouring.
                if hasattr(child, "SetOwnForegroundColour"):
                    child.SetOwnForegroundColour(text_colour)
                child.SetForegroundColour(text_colour)
                if field_colour is not None:
                    if hasattr(child, "SetOwnBackgroundColour"):
                        child.SetOwnBackgroundColour(field_colour)
                    child.SetBackgroundColour(field_colour)
                child.Refresh(False)
            elif list_types and isinstance(child, list_types):
                if hasattr(child, "SetOwnForegroundColour"):
                    child.SetOwnForegroundColour(text_colour)
                child.SetForegroundColour(text_colour)
                if field_colour is not None:
                    if hasattr(child, "SetOwnBackgroundColour"):
                        child.SetOwnBackgroundColour(field_colour)
                    child.SetBackgroundColour(field_colour)
                child.Refresh(False)
            elif isinstance(child, (wx_module.CheckBox, wx_module.RadioButton)):
                child.SetForegroundColour(text_colour)
        except (AttributeError, RuntimeError):
            # Some native controls reject explicit colours on particular wx
            # ports. Their system theme remains a safe fallback.
            pass
        apply_native_theme(child, wx_module, palette)

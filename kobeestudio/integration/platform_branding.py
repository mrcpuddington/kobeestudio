"""Native process and window branding for the external IPC editor."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path
from typing import Any, Optional


APP_NAME = "Kobee Studio"
APP_VENDOR = "Kobee"
APP_USER_MODEL_ID = "com.github.mrcpuddington.kobeestudio"


def configure_process_identity(
    platform_name: Optional[str] = None,
    shell32: Optional[Any] = None,
) -> bool:
    """Give the Windows host process a stable taskbar identity before UI exists."""
    platform_name = platform_name or sys.platform
    if not platform_name.startswith("win"):
        return False

    try:
        shell32 = shell32 or ctypes.windll.shell32
        setter = shell32.SetCurrentProcessExplicitAppUserModelID
        if hasattr(setter, "argtypes"):
            setter.argtypes = [ctypes.c_wchar_p]
            setter.restype = ctypes.c_long
        result = setter(APP_USER_MODEL_ID)
        return result == 0
    except (AttributeError, OSError):
        return False


def configure_application_branding(
    app: Any,
    icon_path: Path,
    platform_name: Optional[str] = None,
) -> bool:
    """Set application metadata and, on macOS, replace the Python Dock icon."""
    app.SetAppName(APP_NAME)
    app.SetVendorName(APP_VENDOR)
    if hasattr(app, "SetAppDisplayName"):
        app.SetAppDisplayName(APP_NAME)

    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        return _set_macos_application_icon(icon_path)
    return True


def configure_window_branding(window: Any, icon_path: Path, wx_module: Any) -> bool:
    """Apply the Kobee icon to the top-level wx window and Windows taskbar."""
    if all(
        hasattr(wx_module, name)
        for name in ("Image", "Bitmap", "Icon", "IconBundle")
    ) and hasattr(window, "SetIcons"):
        try:
            source = wx_module.Image(str(icon_path), wx_module.BITMAP_TYPE_PNG)
            if not source.IsOk():
                return False
            bundle = wx_module.IconBundle()
            for size in (16, 24, 32, 48, 64, 128, 256):
                image = source.Copy()
                image.Rescale(size, size, wx_module.IMAGE_QUALITY_HIGH)
                icon = wx_module.Icon()
                icon.CopyFromBitmap(wx_module.Bitmap(image))
                bundle.AddIcon(icon)
            window.SetIcons(bundle)
            return True
        except (AttributeError, OSError, TypeError):
            # Older wx builds can lack one of the image conversion methods.
            # Their single-icon path is still better than leaving Python's icon.
            pass
    try:
        icon = wx_module.Icon(str(icon_path), wx_module.BITMAP_TYPE_PNG)
        if not icon.IsOk():
            return False
        window.SetIcon(icon)
        return True
    except (AttributeError, OSError):
        return False


def _set_macos_application_icon(icon_path: Path) -> bool:
    """Set NSApplication's Dock icon without adding a PyObjC dependency."""
    if not icon_path.is_file():
        return False

    try:
        appkit_path = ctypes.util.find_library("AppKit")
        objc_path = ctypes.util.find_library("objc")
        if not appkit_path or not objc_path:
            return False

        ctypes.CDLL(appkit_path, mode=ctypes.RTLD_GLOBAL)
        objc = ctypes.CDLL(objc_path)

        objc_get_class = objc.objc_getClass
        objc_get_class.argtypes = [ctypes.c_char_p]
        objc_get_class.restype = ctypes.c_void_p

        selector = objc.sel_registerName
        selector.argtypes = [ctypes.c_char_p]
        selector.restype = ctypes.c_void_p

        send = objc.objc_msgSend
        send.restype = ctypes.c_void_p

        def message(receiver: int, name: bytes, *arguments: Any) -> int:
            return int(
                send(
                    ctypes.c_void_p(receiver),
                    ctypes.c_void_p(selector(name)),
                    *arguments,
                )
                or 0
            )

        application = message(objc_get_class(b"NSApplication"), b"sharedApplication")
        ns_string = message(objc_get_class(b"NSString"), b"alloc")
        ns_string = message(
            ns_string,
            b"initWithUTF8String:",
            ctypes.c_char_p(os.fsencode(str(icon_path))),
        )
        image = message(objc_get_class(b"NSImage"), b"alloc")
        image = message(
            image,
            b"initWithContentsOfFile:",
            ctypes.c_void_p(ns_string),
        )
        if not application or not image:
            return False

        message(application, b"setApplicationIconImage:", ctypes.c_void_p(image))
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False

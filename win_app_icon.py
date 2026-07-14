"""Windows app identity / taskbar icon helpers."""

from __future__ import annotations

import sys
from pathlib import Path


APP_USER_MODEL_ID = "CursorUsageFloat.App"


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Set process AppUserModelID so the taskbar does not group under python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        return


def apply_window_icon(hwnd: int, ico_path: Path) -> None:
    """Set the small/large window icons from an .ico (affects taskbar/alt-tab)."""
    if sys.platform != "win32" or not hwnd or not ico_path.is_file():
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        path = str(ico_path.resolve())
        LoadImageW = user32.LoadImageW
        LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        LoadImageW.restype = wintypes.HANDLE

        hicon_small = LoadImageW(None, path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        hicon_big = LoadImageW(None, path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if not hicon_big:
            hicon_big = LoadImageW(None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception:
        return


def apply_tk_icon(window: object, ico_path: Path) -> None:
    """Apply .ico via tk iconbitmap and Win32 WM_SETICON when possible."""
    if not ico_path.is_file():
        return
    iconbitmap = getattr(window, "iconbitmap", None)
    if callable(iconbitmap):
        try:
            iconbitmap(str(ico_path))
        except Exception:
            pass
    winfo_id = getattr(window, "winfo_id", None)
    if not callable(winfo_id):
        return
    try:
        from win_clickthrough import toplevel_hwnd

        apply_window_icon(toplevel_hwnd(window), ico_path)
    except Exception:
        return

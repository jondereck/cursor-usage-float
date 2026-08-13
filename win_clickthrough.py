"""Windows click-through helper for the floater window."""

from __future__ import annotations

import sys


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Toggle WS_EX_TRANSPARENT on a top-level HWND. No-op off Windows."""
    if sys.platform != "win32" or not hwnd:
        return

    import ctypes

    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020

    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def toplevel_hwnd(widget: object) -> int:
    """Resolve the Windows HWND for a tkinter widget/window."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes

        winfo_id = getattr(widget, "winfo_id", None)
        if winfo_id is None:
            return 0
        wid = int(winfo_id())
        # Tk window id is a child; walk up to the real top-level HWND.
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(wid)
        return int(hwnd or wid)
    except Exception:
        return 0


def get_window_pos(hwnd: int) -> tuple[int, int] | None:
    """Screen position via GetWindowRect (virtual-desktop aware)."""
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        if not ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
            return None
        return int(rect.left), int(rect.top)
    except Exception:
        return None


def set_window_pos(hwnd: int, x: int, y: int) -> bool:
    """Move window with SetWindowPos (works across monitors; keeps size/z-order)."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes

        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        return bool(
            ctypes.windll.user32.SetWindowPos(
                int(hwnd),
                0,
                int(x),
                int(y),
                0,
                0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )
        )
    except Exception:
        return False


def set_rounded_corners(hwnd: int, width: int, height: int, radius: int = 16) -> None:
    """Clip the top-level window to a rounded rectangle. No-op off Windows.

    ``radius`` is the CreateRoundRectRgn ellipse diameter (not CSS border-radius).
    For a full capsule, pass ``height`` so each end is a semicircle.

    Enables WS_EX_LAYERED so DWM soft-composites the clip (less jagged edges).
    """
    if sys.platform != "win32" or not hwnd or width <= 0 or height <= 0:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        LWA_ALPHA = 0x00000002

        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not (style & WS_EX_LAYERED):
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            # Fully opaque — layered mode mainly for smoother edge compositing.
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)

        # Capsule: ellipse diameter == height. +1 exclusive bottom/right.
        ellipse = max(1, int(radius))
        hrgn = gdi32.CreateRoundRectRgn(
            0, 0, int(width) + 1, int(height) + 1, ellipse, ellipse
        )
        user32.SetWindowRgn(hwnd, hrgn, True)
    except Exception:
        return

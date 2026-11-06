"""Detect when another app is using the monitor in exclusive fullscreen."""

from __future__ import annotations

import sys

_QUNS_RUNNING_D3D_FULL_SCREEN = 3
_QUNS_PRESENTATION_MODE = 4
_GA_ROOT = 2


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Return ``(left, top, right, bottom)`` for an HWND."""
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
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:
        return None


def window_process_id(hwnd: int) -> int | None:
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return None


def window_covers_monitor(
    window: tuple[int, int, int, int],
    monitor: tuple[int, int, int, int],
    *,
    tolerance: int = 24,
) -> bool:
    """True when ``window`` covers the full monitor, including the taskbar.

    Maximized (work-area) windows do not qualify: they stop above the taskbar.
    """
    wl, wt, wr, wb = (int(v) for v in window)
    ml, mt, mr, mb = (int(v) for v in monitor)
    tol = max(0, int(tolerance))
    if (wr - wl) < (mr - ml) - tol:
        return False
    if (wb - wt) < (mb - mt) - tol:
        return False
    if abs(wl - ml) > tol or abs(wt - mt) > tol:
        return False
    return wb >= mb - tol


def session_reports_fullscreen() -> bool:
    """Shell thinks a D3D / presentation fullscreen session is active."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        state = ctypes.c_int()
        fn = ctypes.windll.shell32.SHQueryUserNotificationState
        if fn(ctypes.byref(state)) != 0:
            return False
        return int(state.value) in (
            _QUNS_RUNNING_D3D_FULL_SCREEN,
            _QUNS_PRESENTATION_MODE,
        )
    except Exception:
        return False


def _monitor_rect_for_window(hwnd: int) -> tuple[int, int, int, int] | None:
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

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        MONITOR_DEFAULTTONEAREST = 2
        user32 = ctypes.windll.user32
        monitor = user32.MonitorFromWindow(int(hwnd), MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcMonitor
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:
        return None


def _is_window_true_fullscreen(hwnd: int, *, tolerance: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = int(hwnd)
        if not user32.IsWindowVisible(handle):
            return False
        if user32.IsIconic(handle):
            return False
        rect = window_rect(handle)
        mon = _monitor_rect_for_window(handle)
        if rect is None or mon is None:
            return False
        return window_covers_monitor(rect, mon, tolerance=tolerance)
    except Exception:
        return False


def _pid_has_fullscreen_window(
    pid: int,
    *,
    our_hwnd: int,
    tolerance: int,
) -> bool:
    if sys.platform != "win32" or not pid:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        our = int(our_hwnd) if our_hwnd else 0
        found = ctypes.c_int(0)

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum(hwnd: int, _lparam: int) -> bool:
            handle = int(hwnd)
            if our and handle == our:
                return True
            owner_pid = window_process_id(handle)
            if owner_pid != pid:
                return True
            if _is_window_true_fullscreen(handle, tolerance=tolerance):
                found.value = 1
                return False
            return True

        callback = WNDENUMPROC(_enum)
        user32.EnumWindows(callback, 0)
        return bool(found.value)
    except Exception:
        return False


def is_foreground_app_fullscreen(
    our_hwnd: int,
    *,
    exclude_process_ids: set[int] | frozenset[int] | None = None,
    tolerance: int = 24,
) -> bool:
    """True when a non-floater app is in true fullscreen (YouTube, games, F11)."""
    if sys.platform != "win32":
        return False
    exclude = set(exclude_process_ids or ())
    try:
        import ctypes

        user32 = ctypes.windll.user32
        our = int(our_hwnd) if our_hwnd else 0

        if session_reports_fullscreen():
            fg = int(user32.GetForegroundWindow() or 0)
            fg_pid = window_process_id(fg) if fg else None
            if fg_pid is None or fg_pid not in exclude:
                return True

        fg = int(user32.GetForegroundWindow() or 0)
        if not fg or fg == our:
            return False

        fg_pid = window_process_id(fg)
        if fg_pid is not None and fg_pid in exclude:
            return False

        if _is_window_true_fullscreen(fg, tolerance=tolerance):
            return True

        root = int(user32.GetAncestor(fg, _GA_ROOT) or 0)
        if root and root != fg and root != our:
            if _is_window_true_fullscreen(root, tolerance=tolerance):
                return True

        if fg_pid is not None:
            return _pid_has_fullscreen_window(
                fg_pid, our_hwnd=our, tolerance=tolerance
            )
        return False
    except Exception:
        return False

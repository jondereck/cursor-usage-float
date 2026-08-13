"""Windows taskbar button for the borderless floater.

The float itself stays visible (pill or expanded). A hidden proxy window
owns the taskbar button so minimize does not withdraw the overlay.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020


def exstyle_with_taskbar(current: int, show: bool) -> int:
    """Return an extended style that shows or hides a taskbar button."""
    if show:
        return (int(current) | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
    return (int(current) | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW


def apply_taskbar_button(hwnd: int, show: bool) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle_with_taskbar(style, show))
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    except Exception:
        return


def detach_window_owner(hwnd: int) -> None:
    """Unown a window so Windows will give it its own taskbar button."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, 0)
        else:
            user32.SetWindowLongW(hwnd, GWLP_HWNDPARENT, 0)
    except Exception:
        return


class TaskbarProxy:
    """Iconified stand-in that appears on the taskbar while the float stays up."""

    def __init__(
        self,
        master: object,
        *,
        title: str,
        on_restore: Callable[[], None],
        on_close: Callable[[], None] | None = None,
        icon_path: Path | None = None,
    ) -> None:
        import tkinter as tk

        from win_app_icon import apply_tk_icon
        from win_clickthrough import toplevel_hwnd

        self._on_restore = on_restore
        self._on_close = on_close
        self._icon_path = icon_path
        self._toplevel_hwnd = toplevel_hwnd
        self._syncing = False
        self._visible = False
        self._win = tk.Toplevel(master)
        self._win.withdraw()
        self._win.title(title)
        self._win.geometry("1x1+-32000+-32000")
        self._win.resizable(False, False)
        self._win.protocol("WM_DELETE_WINDOW", self._handle_close)
        self._win.bind("<Map>", self._handle_map)
        if icon_path is not None:
            apply_tk_icon(self._win, icon_path)

    def show(self) -> None:
        if self._visible:
            try:
                if str(self._win.state()) != "iconic":
                    self._syncing = True
                    self._win.iconify()
                    self._win.after(80, self._clear_syncing)
            except Exception:
                pass
            return
        self._syncing = True
        self._visible = True
        self._win.deiconify()
        hwnd = self._toplevel_hwnd(self._win)
        detach_window_owner(hwnd)
        apply_taskbar_button(hwnd, True)
        if self._icon_path is not None:
            from win_app_icon import apply_tk_icon

            apply_tk_icon(self._win, self._icon_path)
        self._win.iconify()
        self._win.after(80, self._clear_syncing)

    def hide(self) -> None:
        if not self._visible:
            self._win.withdraw()
            return
        self._syncing = True
        self._visible = False
        self._win.withdraw()
        self._win.after(80, self._clear_syncing)

    def destroy(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            pass

    def _clear_syncing(self) -> None:
        self._syncing = False

    def _handle_map(self, event: object) -> None:
        widget = getattr(event, "widget", None)
        if widget is not self._win or self._syncing or not self._visible:
            return
        try:
            if str(self._win.state()) == "iconic":
                return
        except Exception:
            return
        self._syncing = True
        self._visible = False
        self._win.withdraw()
        self._on_restore()
        self._win.after(80, self._clear_syncing)

    def _handle_close(self) -> None:
        if self._on_close is not None:
            self._on_close()
            return
        self.hide()

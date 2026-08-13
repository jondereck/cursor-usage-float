"""Windows system tray icon via Shell_NotifyIcon (ctypes, no deps)."""

from __future__ import annotations

import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

WM_USER = 0x0400
WM_TRAYICON = WM_USER + 42
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_NULL = 0x0000

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

PM_REMOVE = 0x0001

MF_STRING = 0x00000000
MF_POPUP = 0x00000010
MF_CHECKED = 0x00000008
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

ID_CURSOR_USAGE = 1001
ID_SETTINGS = 1002
ID_ENABLE_STARTUP = 1003
ID_START_MINIMIZED = 1004
ID_QUIT = 1005

QUIT_ARM_DELAY_MS = 400


def tray_notify_flags() -> int:
    return NIF_MESSAGE | NIF_ICON | NIF_TIP


def checked_menu_flags(checked: bool) -> int:
    flags = MF_STRING
    if checked:
        flags |= MF_CHECKED
    return flags


def tray_menu_track_flags() -> int:
    return TPM_RIGHTBUTTON | TPM_RETURNCMD


def menu_popup_origin(cursor_x: int, cursor_y: int, menu_height: int = 0, *, gap: int = 2) -> tuple[int, int]:
    """Anchor the menu near the tray cursor.

    Only a tiny upward nudge — Tk keeps the menu on-screen (above the taskbar).
    A full ``menu_height`` offset made the menu float too far from the icon.
    ``menu_height`` is kept for API compatibility but ignored.
    """
    _ = menu_height
    return int(cursor_x), max(0, int(cursor_y) - int(gap))


class TrayIcon:
    """Notification-area icon.

    Win32 ``WndProc`` must NOT call into Tk (crashes: GIL / thread state).
    Clicks are queued in the callback and drained on the Tk ``after`` poll.
    """

    def __init__(
        self,
        master: object,
        *,
        tip: str = "Cursor Usage",
        icon_path: Path | None = None,
        on_show: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        is_start_with_windows: Callable[[], bool] | None = None,
        is_start_minimized: Callable[[], bool] | None = None,
        set_start_with_windows: Callable[[bool], None] | None = None,
        set_start_minimized: Callable[[bool], None] | None = None,
    ) -> None:
        self._master = master
        self._tip = tip
        self._icon_path = icon_path
        self._on_show = on_show
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._is_start_with_windows = is_start_with_windows or (lambda: False)
        self._is_start_minimized = is_start_minimized or (lambda: False)
        self._set_start_with_windows = set_start_with_windows
        self._set_start_minimized = set_start_minimized
        self._visible = False
        self._hwnd = 0
        self._hicon = 0
        self._nid = None
        self._wndproc = None
        self._class_atom = 0
        self._pump_job: str | None = None
        self._menu = None
        self._extras_menu = None
        self._menu_host = None
        self._quit_armed = False
        self._menu_open = False
        self._pending: deque[int] = deque()

        if sys.platform == "win32":
            self._create_message_window()
            self._load_icon()
            self._build_menu()

    @property
    def visible(self) -> bool:
        return self._visible

    def show(self) -> None:
        if sys.platform != "win32" or not self._hwnd or self._visible:
            return
        self._notify(NIM_ADD)
        self._visible = True
        self._start_pump()

    def hide(self) -> None:
        if sys.platform != "win32" or not self._visible:
            return
        self._notify(NIM_DELETE)
        self._visible = False
        self._stop_pump()

    def destroy(self) -> None:
        self.hide()
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            if self._hwnd:
                ctypes.windll.user32.DestroyWindow(self._hwnd)
                self._hwnd = 0
            if self._hicon:
                ctypes.windll.user32.DestroyIcon(self._hicon)
                self._hicon = 0
            if self._class_atom:
                ctypes.windll.user32.UnregisterClassW(
                    wintypes.LPCWSTR("CursorUsageFloatTray"),
                    ctypes.windll.kernel32.GetModuleHandleW(None),
                )
                self._class_atom = 0
        except Exception:
            pass
        self._menu = None
        self._extras_menu = None
        if self._menu_host is not None:
            try:
                self._menu_host.destroy()
            except Exception:
                pass
            self._menu_host = None

    def _create_message_window(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        LRESULT = ctypes.c_ssize_t
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t

        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            WPARAM,
            LPARAM,
        )

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.restype = wintypes.HWND

        def _wndproc(hwnd, msg, wparam, lparam):  # type: ignore[no-untyped-def]
            # CRITICAL: never call Tk (after/update/...) from this callback.
            # Tk's event loop dispatches our HWND messages; re-entering Tk here
            # aborts with PyEval_RestoreThread / hard-exits the process.
            if msg == WM_TRAYICON:
                self._pending.append(int(lparam) & 0xFFFF)
                return 0
            return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))

        self._wndproc = WNDPROC(_wndproc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class_name = "CursorUsageFloatTray"
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = 0
        wc.hCursor = 0
        wc.hbrBackground = 0
        wc.lpszMenuName = None
        wc.lpszClassName = class_name

        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            err = kernel32.GetLastError()
            if err not in (0, 1410):
                return
        self._class_atom = int(atom or 1)

        WS_POPUP = 0x80000000
        self._hwnd = int(
            user32.CreateWindowExW(
                0,
                class_name,
                "CursorUsageFloatTray",
                WS_POPUP,
                0,
                0,
                0,
                0,
                0,
                0,
                hinst,
                None,
            )
            or 0
        )

    def _load_icon(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        path = self._icon_path
        if path is not None and path.is_file():
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
            handle = LoadImageW(
                None, str(path.resolve()), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
            if handle:
                self._hicon = int(handle)
                return
        self._hicon = int(user32.LoadIconW(None, ctypes.cast(IDI_APPLICATION, wintypes.LPCWSTR)))

    def _notify(self, action: int) -> None:
        if not self._hwnd:
            return
        import ctypes
        from ctypes import wintypes

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
            ]

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = tray_notify_flags()
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._hicon
        tip = (self._tip or "Cursor Usage")[:127]
        nid.szTip = tip
        self._nid = nid
        ctypes.windll.shell32.Shell_NotifyIconW(action, ctypes.byref(nid))

    def _start_pump(self) -> None:
        if self._pump_job is not None:
            return
        self._pump()

    def _stop_pump(self) -> None:
        if self._pump_job is None:
            return
        after_cancel = getattr(self._master, "after_cancel", None)
        if callable(after_cancel):
            try:
                after_cancel(self._pump_job)
            except Exception:
                pass
        self._pump_job = None

    def _drain_pending(self) -> None:
        while self._pending:
            mouse = self._pending.popleft()
            if mouse in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._dismiss_menu()
                self._handle_show()
            elif mouse == WM_RBUTTONUP:
                self._handle_right_click()

    def _pump(self) -> None:
        if not self._visible or not self._hwnd:
            self._pump_job = None
            return
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt", POINT),
                ]

            user32 = ctypes.windll.user32
            msg = MSG()
            # Dispatch Win32 messages first (wndproc only queues); then drain on Tk.
            while user32.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass

        # Always drain — skipping while menu_open blocked the 2nd right-click.
        self._drain_pending()

        after = getattr(self._master, "after", None)
        if callable(after):
            self._pump_job = after(40, self._pump)
        else:
            self._pump_job = None

    def _build_menu(self) -> None:
        import tkinter as tk

        # Menus parented to an overrideredirect floater are unreliable on Windows.
        host = tk.Toplevel(self._master)
        host.withdraw()
        try:
            host.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._menu_host = host

        menu = tk.Menu(host, tearoff=0)
        menu.add_command(label="Cursor Usage", command=self._handle_show)
        menu.add_command(label="Settings", command=self._handle_settings)
        extras = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Extras", menu=extras)
        self._extras_menu = extras
        menu.add_command(label="Quit", command=self._handle_quit)
        self._menu = menu
        self._refresh_extras_checks()

    def _refresh_extras_checks(self) -> None:
        extras = getattr(self, "_extras_menu", None)
        if extras is None:
            return
        extras.delete(0, "end")
        sw = "✓  " if self._is_start_with_windows() else "    "
        sm = "✓  " if self._is_start_minimized() else "    "
        extras.add_command(
            label=f"{sw}Enable at Startup",
            command=self._toggle_start_with_windows,
        )
        extras.add_command(
            label=f"{sm}Start Minimized",
            command=self._toggle_start_minimized,
        )

    def _handle_show(self) -> None:
        if self._on_show:
            self._on_show()

    def _handle_settings(self) -> None:
        if self._on_show:
            self._on_show()
        if self._on_settings:
            self._on_settings()

    def _handle_quit(self) -> None:
        if not self._quit_armed:
            return
        if self._on_quit:
            self._on_quit()

    def _arm_quit(self) -> None:
        self._quit_armed = True

    def _dismiss_menu(self) -> None:
        if self._menu is not None:
            try:
                self._menu.unpost()
            except Exception:
                pass
        self._menu_open = False

    def _handle_right_click(self) -> None:
        if self._menu is None:
            return
        # Fresh post every time (2nd right-click was a no-op while menu_open stuck).
        self._dismiss_menu()
        after = getattr(self._master, "after", None)
        if callable(after):
            after(50, self._popup_menu)
        else:
            self._popup_menu()

    def _popup_menu(self) -> None:
        if self._menu is None:
            return
        self._quit_armed = False
        self._menu_open = True
        self._refresh_extras_checks()

        after = getattr(self._master, "after", None)
        if callable(after):
            after(QUIT_ARM_DELAY_MS, self._arm_quit)

        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            pt = POINT()
            user32 = ctypes.windll.user32
            user32.GetCursorPos(ctypes.byref(pt))

            fg = 0
            try:
                from win_clickthrough import toplevel_hwnd

                fg = int(toplevel_hwnd(self._master) or 0)
            except Exception:
                fg = 0
            user32.SetForegroundWindow(fg or self._hwnd)

            x, y = menu_popup_origin(int(pt.x), int(pt.y))
            self._menu.post(x, y)
            try:
                self._menu.activate(0)
            except Exception:
                pass
            user32.PostMessageW(fg or self._hwnd, WM_NULL, 0, 0)
        except Exception:
            self._menu_open = False
            self._quit_armed = True
            return

        try:
            self._menu.bind("<Unmap>", self._on_menu_unmap, add="+")
        except Exception:
            self._menu_open = False

    def _on_menu_unmap(self, _event: object = None) -> None:
        self._menu_open = False

    def _toggle_start_with_windows(self) -> None:
        if self._set_start_with_windows is None:
            return
        self._set_start_with_windows(not self._is_start_with_windows())

    def _toggle_start_minimized(self) -> None:
        if self._set_start_minimized is None:
            return
        self._set_start_minimized(not self._is_start_minimized())

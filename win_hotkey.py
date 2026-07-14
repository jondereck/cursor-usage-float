"""Windows global hotkey helper (RegisterHotKey on a dedicated thread)."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

HOTKEY_ID = 0x4355  # "CU"

# Prefer Ctrl+Shift+U; fall back if another app already owns it (ERROR_HOTKEY_ALREADY_REGISTERED).
HOTKEY_CANDIDATES: tuple[tuple[int, int, str], ...] = (
    (MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, 0x55, "Ctrl+Shift+U"),
    (MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, 0x55, "Ctrl+Alt+Shift+U"),
    (MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, 0x7B, "Ctrl+Shift+F12"),
)

# Back-compat aliases used by main.py
CLICK_THROUGH_HOTKEY_ID = HOTKEY_ID
CLICK_THROUGH_HOTKEY_MODS = HOTKEY_CANDIDATES[0][0]
CLICK_THROUGH_HOTKEY_VK = HOTKEY_CANDIDATES[0][1]


class GlobalHotkey:
    """Register a thread-level hotkey; marshal fires onto the tk main thread.

    Tk's mainloop consumes WM_HOTKEY on the UI thread, so RegisterHotKey(NULL)
    must live on a dedicated thread with its own GetMessage loop.
    """

    def __init__(
        self,
        root: Any,
        *,
        callback: Callable[[], None],
        hotkey_id: int = HOTKEY_ID,
        candidates: tuple[tuple[int, int, str], ...] = HOTKEY_CANDIDATES,
    ) -> None:
        self._root = root
        self._hotkey_id = hotkey_id
        self._candidates = candidates
        self._callback = callback
        self._registered = False
        self._shortcut_label = ""
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._reg_ok = False
        self._modifiers = 0
        self._vk = 0

    @property
    def shortcut_label(self) -> str:
        return self._shortcut_label

    def register(self) -> bool:
        if sys.platform != "win32" or self._thread is not None:
            return self._registered
        self._ready.clear()
        self._reg_ok = False
        self._thread = threading.Thread(
            target=self._thread_main,
            name="cursor-usage-hotkey",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        self._registered = self._reg_ok
        return self._registered

    def unregister(self) -> None:
        if sys.platform != "win32":
            self._registered = False
            return
        import ctypes

        tid = self._thread_id
        if tid:
            ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0
        self._registered = False

    def _thread_main(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())

        chosen_mods = 0
        chosen_vk = 0
        chosen_label = ""
        for mods, vk, label in self._candidates:
            if user32.RegisterHotKey(None, self._hotkey_id, mods, vk):
                chosen_mods = mods
                chosen_vk = vk
                chosen_label = label
                break

        self._modifiers = chosen_mods
        self._vk = chosen_vk
        self._shortcut_label = chosen_label
        self._reg_ok = bool(chosen_label)
        self._ready.set()
        if not self._reg_ok:
            return

        msg = wintypes.MSG()
        while True:
            result = int(user32.GetMessageW(ctypes.byref(msg), None, 0, 0))
            if result == 0 or result == -1:
                break
            if msg.message == WM_HOTKEY and int(msg.wParam) == self._hotkey_id:
                try:
                    self._root.after(0, self._safe_callback)
                except Exception:
                    pass

        user32.UnregisterHotKey(None, self._hotkey_id)

    def _safe_callback(self) -> None:
        try:
            self._callback()
        except Exception:
            pass

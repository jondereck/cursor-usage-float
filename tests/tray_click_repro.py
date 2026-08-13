"""Reproduce tray clicks; run as subprocess to detect hard crashes."""

from __future__ import annotations

import sys
import time
import tkinter as tk

from win_tray import WM_LBUTTONUP, WM_RBUTTONUP, WM_TRAYICON, TrayIcon


def main() -> int:
    log: list[str] = []
    root = tk.Tk()
    root.withdraw()
    root.geometry("100x100+50+50")

    tray = TrayIcon(
        root,
        tip="repro",
        on_show=lambda: log.append("show"),
        on_settings=lambda: log.append("settings"),
        on_quit=lambda: log.append("quit"),
    )
    # Don't open a real popup in headless repro (can block the event loop).
    tray._popup_menu = lambda: log.append("menu")  # type: ignore[method-assign]
    print("hwnd", tray._hwnd, flush=True)
    if not tray._hwnd:
        print("NO_HWND", flush=True)
        return 2

    tray.show()
    root.update()

    import ctypes

    user32 = ctypes.windll.user32

    user32.PostMessageW(tray._hwnd, WM_TRAYICON, 1, WM_LBUTTONUP)
    for _ in range(40):
        root.update_idletasks()
        root.update()
        time.sleep(0.02)
    print("after_left", log, flush=True)
    if "show" not in log:
        print("FAIL_LEFT_NO_SHOW", flush=True)
        return 3

    log.clear()
    user32.PostMessageW(tray._hwnd, WM_TRAYICON, 1, WM_RBUTTONUP)
    for _ in range(50):
        root.update_idletasks()
        root.update()
        time.sleep(0.02)
    print("after_right", log, flush=True)
    if "menu" not in log:
        print("FAIL_RIGHT_NO_MENU", flush=True)
        return 4
    if "quit" in log:
        print("FAIL_RIGHT_QUIT", flush=True)
        return 5

    print("ALIVE", flush=True)
    tray.destroy()
    root.destroy()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("EXCEPTION", type(exc).__name__, exc, flush=True)
        raise

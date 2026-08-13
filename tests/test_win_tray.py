"""Unit helpers for tray notify flags (no Win32 HWND required)."""

from __future__ import annotations

from win_tray import (
    ID_CURSOR_USAGE,
    ID_ENABLE_STARTUP,
    ID_QUIT,
    ID_SETTINGS,
    ID_START_MINIMIZED,
    MF_CHECKED,
    MF_POPUP,
    MF_STRING,
    NIF_ICON,
    NIF_MESSAGE,
    NIF_TIP,
    TPM_RETURNCMD,
    TPM_RIGHTBUTTON,
    TrayIcon,
    checked_menu_flags,
    menu_popup_origin,
    tray_menu_track_flags,
    tray_notify_flags,
)


def test_tray_notify_flags_include_icon_tip_and_callback() -> None:
    flags = tray_notify_flags()
    assert flags & NIF_MESSAGE
    assert flags & NIF_ICON
    assert flags & NIF_TIP


def test_tray_menu_command_ids_are_distinct() -> None:
    ids = {
        ID_CURSOR_USAGE,
        ID_SETTINGS,
        ID_ENABLE_STARTUP,
        ID_START_MINIMIZED,
        ID_QUIT,
    }
    assert len(ids) == 5
    assert ID_QUIT != ID_CURSOR_USAGE


def test_checked_menu_flags_toggle_mf_checked() -> None:
    assert checked_menu_flags(True) == (MF_STRING | MF_CHECKED)
    assert checked_menu_flags(False) == MF_STRING
    assert MF_POPUP


def test_tray_menu_track_flags_return_command_on_right_button() -> None:
    flags = tray_menu_track_flags()
    assert flags & TPM_RIGHTBUTTON
    assert flags & TPM_RETURNCMD


def test_menu_popup_origin_stays_near_cursor() -> None:
    x, y = menu_popup_origin(500, 1000, menu_height=120, gap=2)
    assert x == 500
    assert y == 998  # tiny nudge only — not a full menu-height jump


def test_right_click_dismisses_stuck_menu_before_repost() -> None:
    calls: list[str] = []
    tray = TrayIcon.__new__(TrayIcon)
    tray._menu = object()  # truthy sentinel
    tray._menu_open = True
    tray._pending = __import__("collections").deque()

    def dismiss() -> None:
        calls.append("dismiss")
        tray._menu_open = False

    tray._dismiss_menu = dismiss  # type: ignore[method-assign]
    tray._popup_menu = lambda: calls.append("popup")  # type: ignore[method-assign]
    tray._master = type("M", (), {"after": None})()  # no after → sync popup
    tray._handle_right_click()
    assert calls == ["dismiss", "popup"]
    assert tray._menu_open is False or "popup" in calls


def test_quit_ignored_until_armed() -> None:
    quit_calls: list[int] = []
    tray = TrayIcon.__new__(TrayIcon)
    tray._on_quit = lambda: quit_calls.append(1)
    tray._quit_armed = False
    tray._handle_quit()
    assert quit_calls == []
    tray._quit_armed = True
    tray._handle_quit()
    assert quit_calls == [1]


def test_tray_clicks_do_not_hard_crash_process() -> None:
    """Regression: WndProc must not call Tk (was killing the app on tray click)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = Path(__file__).resolve().parent / "tray_click_repro.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        cwd=str(root),
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ALIVE" in proc.stdout
    assert "after_left" in proc.stdout
    assert "after_right" in proc.stdout

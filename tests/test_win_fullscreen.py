"""Tests for fullscreen detection helpers."""

from __future__ import annotations

import win_fullscreen
from win_fullscreen import (
    _is_window_true_fullscreen,
    is_foreground_app_fullscreen,
    is_foreground_app_fullscreen_on_monitor,
    is_shell_window,
    window_covers_monitor,
)


def test_window_covers_monitor_full_bleed() -> None:
    monitor = (0, 0, 1920, 1080)
    window = (0, 0, 1920, 1080)
    assert window_covers_monitor(window, monitor)


def test_window_covers_monitor_rejects_small_window() -> None:
    monitor = (0, 0, 1920, 1080)
    window = (100, 100, 900, 700)
    assert not window_covers_monitor(window, monitor)


def test_window_covers_monitor_allows_small_offset() -> None:
    monitor = (0, 0, 1920, 1080)
    window = (2, -2, 1920, 1080)
    assert window_covers_monitor(window, monitor, tolerance=8)


def test_maximized_work_area_is_not_fullscreen() -> None:
    monitor = (0, 0, 1920, 1080)
    window = (0, 0, 1920, 1040)
    assert not window_covers_monitor(window, monitor)


def test_fullscreen_on_other_monitor_does_not_hide_pill(monkeypatch) -> None:
    monkeypatch.setattr(
        win_fullscreen, "is_foreground_app_fullscreen", lambda *_a, **_k: True
    )
    monkeypatch.setattr(win_fullscreen, "_foreground_window_handle", lambda: 999)
    monitors = {999: 2, 123: 1}
    monkeypatch.setattr(
        win_fullscreen, "monitor_handle_for_window", lambda hwnd: monitors.get(hwnd)
    )
    assert is_foreground_app_fullscreen_on_monitor(123) is False


def test_fullscreen_on_pill_monitor_hides_pill(monkeypatch) -> None:
    monkeypatch.setattr(
        win_fullscreen, "is_foreground_app_fullscreen", lambda *_a, **_k: True
    )
    monkeypatch.setattr(win_fullscreen, "_foreground_window_handle", lambda: 999)
    monkeypatch.setattr(win_fullscreen, "monitor_handle_for_window", lambda _hwnd: 2)
    assert is_foreground_app_fullscreen_on_monitor(123) is True


def test_not_fullscreen_never_hides(monkeypatch) -> None:
    monkeypatch.setattr(
        win_fullscreen, "is_foreground_app_fullscreen", lambda *_a, **_k: False
    )
    assert is_foreground_app_fullscreen_on_monitor(123) is False


def test_shell_window_classes(monkeypatch) -> None:
    for name in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        monkeypatch.setattr(
            win_fullscreen, "window_class_name", lambda _hwnd, _name=name: _name
        )
        assert is_shell_window(1) is True
    monkeypatch.setattr(
        win_fullscreen, "window_class_name", lambda _hwnd: "Chrome_WidgetWin_1"
    )
    assert is_shell_window(1) is False


def test_taskbar_focus_is_not_fullscreen(monkeypatch) -> None:
    monkeypatch.setattr(win_fullscreen, "_foreground_window_handle", lambda: 555)
    monkeypatch.setattr(win_fullscreen, "is_shell_window", lambda _hwnd: True)
    assert is_foreground_app_fullscreen(0) is False


def test_desktop_window_covering_monitor_is_not_fullscreen(monkeypatch) -> None:
    monkeypatch.setattr(win_fullscreen, "is_shell_window", lambda _hwnd: True)
    monkeypatch.setattr(
        win_fullscreen, "window_rect", lambda _hwnd: (0, 0, 1920, 1080)
    )
    monkeypatch.setattr(
        win_fullscreen, "_monitor_rect_for_window", lambda _hwnd: (0, 0, 1920, 1080)
    )
    assert _is_window_true_fullscreen(1, tolerance=24) is False

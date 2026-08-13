"""Taskbar button style helpers (float stays visible)."""

from __future__ import annotations

from win_taskbar import WS_EX_APPWINDOW, WS_EX_TOOLWINDOW, exstyle_with_taskbar


def test_exstyle_shows_taskbar_button() -> None:
    current = WS_EX_TOOLWINDOW
    result = exstyle_with_taskbar(current, show=True)
    assert result & WS_EX_APPWINDOW
    assert not (result & WS_EX_TOOLWINDOW)


def test_exstyle_hides_taskbar_button() -> None:
    current = WS_EX_APPWINDOW
    result = exstyle_with_taskbar(current, show=False)
    assert result & WS_EX_TOOLWINDOW
    assert not (result & WS_EX_APPWINDOW)

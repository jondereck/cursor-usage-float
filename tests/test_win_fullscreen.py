"""Tests for fullscreen detection helpers."""

from __future__ import annotations

from win_fullscreen import window_covers_monitor


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

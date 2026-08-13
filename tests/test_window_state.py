"""Unit tests for local window position / mode persistence."""

from __future__ import annotations

import json
from pathlib import Path

from window_state import (
    WindowState,
    clamp_position,
    load_window_state,
    save_window_state,
)


def test_round_trip_save_load(tmp_path: Path) -> None:
    path = tmp_path / "window-state.json"
    original = WindowState(x=1200, y=40, minimized=True)
    save_window_state(original, path)
    loaded = load_window_state(path)
    assert loaded == original


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_window_state(tmp_path / "missing.json") is None


def test_corrupt_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "window-state.json"
    path.write_text("{not-json", encoding="utf-8")
    assert load_window_state(path) is None


def test_invalid_types_return_none(tmp_path: Path) -> None:
    path = tmp_path / "window-state.json"
    path.write_text(json.dumps({"x": "nope", "y": 1, "minimized": False}), encoding="utf-8")
    assert load_window_state(path) is None


def test_clamp_position_keeps_window_on_primary() -> None:
    # 200x80 window on 1920x1080 — off right/bottom should pull back.
    x, y = clamp_position(3000, 2000, width=200, height=80, screen_w=1920, screen_h=1080)
    assert x == 1920 - 200
    assert y == 1080 - 80


def test_clamp_position_rejects_negative_on_primary() -> None:
    x, y = clamp_position(-50, -20, width=100, height=50, screen_w=800, screen_h=600)
    assert x == 0
    assert y == 0


def test_clamp_position_allows_second_monitor_to_the_right() -> None:
    # Primary 1920 + secondary 1920 → virtual 3840 wide starting at 0.
    x, y = clamp_position(
        2500,
        80,
        width=200,
        height=80,
        screen_w=3840,
        screen_h=1080,
        origin_x=0,
        origin_y=0,
    )
    assert x == 2500
    assert y == 80


def test_clamp_position_allows_second_monitor_to_the_left() -> None:
    # Secondary on the left: virtual origin_x = -1920.
    x, y = clamp_position(
        -1500,
        40,
        width=200,
        height=80,
        screen_w=3840,
        screen_h=1080,
        origin_x=-1920,
        origin_y=0,
    )
    assert x == -1500
    assert y == 40

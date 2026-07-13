"""Unit tests for settings load/save and minimized metric selection."""

from __future__ import annotations

import json
from pathlib import Path

from cursor_usage import PlanUsage
from settings import (
    AppSettings,
    format_percent,
    load_settings,
    resolve_minimized_percent,
    save_settings,
)


def _usage(
    total: float = 10.0,
    auto: float = 40.0,
    api: float = 25.0,
) -> PlanUsage:
    return PlanUsage(
        total_percent=total,
        auto_percent=auto,
        api_percent=api,
    )


def test_load_defaults_when_file_missing(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    settings = load_settings(path)
    assert settings == AppSettings()


def test_round_trip_save_load(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = AppSettings(
        density="compact",
        always_on_top=False,
        click_through=True,
        show_header=False,
        show_reset_countdown=False,
        show_stale_badge=False,
        minimized_metric="worst",
        start_minimized=True,
        start_with_windows=True,
    )
    save_settings(original, path)
    loaded = load_settings(path)
    assert loaded == original


def test_unknown_keys_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "density": "minimal",
                "unknown_flag": True,
                "minimized_metric": "api",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_settings(path)
    assert loaded.density == "minimal"
    assert loaded.minimized_metric == "api"
    assert loaded.always_on_top is True
    assert loaded.start_with_windows is False


def test_start_with_windows_default_and_legacy(tmp_path: Path) -> None:
    """Legacy settings.json without start_with_windows keeps default False."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"start_minimized": True}),
        encoding="utf-8",
    )
    loaded = load_settings(path)
    assert loaded.start_minimized is True
    assert loaded.start_with_windows is False


def test_invalid_enum_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"density": "huge", "minimized_metric": "nope"}),
        encoding="utf-8",
    )
    loaded = load_settings(path)
    assert loaded.density == "full"
    assert loaded.minimized_metric == "total"


def test_resolve_minimized_percent_modes() -> None:
    usage = _usage(total=10.0, auto=40.0, api=25.0)
    assert resolve_minimized_percent(usage, "total") == 10.0
    assert resolve_minimized_percent(usage, "auto") == 40.0
    assert resolve_minimized_percent(usage, "api") == 25.0
    assert resolve_minimized_percent(usage, "worst") == 40.0


def test_format_percent() -> None:
    assert format_percent(42.0) == "42.0%"
    assert format_percent(42.5) == "42.5%"
    assert format_percent(12.9) == "12.9%"


def test_bar_color_thresholds() -> None:
    from theme import BAR_FG, CRITICAL, WARN, bar_color_for_percent

    assert bar_color_for_percent(10).lower() == BAR_FG.lower()
    assert bar_color_for_percent(39.9).lower() == BAR_FG.lower()
    # Mid ramp toward warn (visible before 80%)
    mid = bar_color_for_percent(60).lower()
    assert mid != BAR_FG.lower()
    assert mid != CRITICAL.lower()
    assert bar_color_for_percent(80).lower() == WARN.lower()
    assert bar_color_for_percent(100).lower() == CRITICAL.lower()

"""Unit tests for settings load/save and minimized metric selection."""

from __future__ import annotations

import json
from pathlib import Path

from cursor_usage import PlanUsage
from pace_history import default_history_path, resolve_pace_history_path
from settings import (
    AppSettings,
    effective_click_through,
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
    assert loaded.minimized_metric == "pace"


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


def test_effective_click_through() -> None:
    assert effective_click_through(False, False) is False
    assert effective_click_through(False, True) is False
    assert effective_click_through(True, False) is True
    assert effective_click_through(True, True) is False


def test_ensure_usage_section_visible_forces_total() -> None:
    from settings import ensure_usage_section_visible

    s = AppSettings(show_total=False, show_pace=False)
    ensure_usage_section_visible(s)
    assert s.show_total is True
    assert s.show_pace is False


def test_ensure_usage_section_visible_keeps_one() -> None:
    from settings import ensure_usage_section_visible

    only_pace = AppSettings(show_total=False, show_pace=True, minimized_metric="total")
    ensure_usage_section_visible(only_pace)
    assert only_pace.show_pace is True
    assert only_pace.minimized_metric == "pace"

    only_total = AppSettings(show_total=True, show_pace=False, minimized_metric="pace")
    ensure_usage_section_visible(only_total)
    assert only_total.show_total is True
    assert only_total.minimized_metric == "total"


def test_load_repairs_both_sections_off(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"show_total": False, "show_pace": False}),
        encoding="utf-8",
    )
    loaded = load_settings(path)
    assert loaded.show_total is True


def test_effective_pill_metric() -> None:
    from settings import effective_pill_metric

    assert (
        effective_pill_metric(AppSettings(minimized_metric="pace", show_pace=True))
        == "pace"
    )
    assert (
        effective_pill_metric(
            AppSettings(minimized_metric="pace", show_pace=False, show_total=True)
        )
        == "total"
    )
    assert (
        effective_pill_metric(
            AppSettings(minimized_metric="total", show_total=False, show_pace=True)
        )
        == "pace"
    )
    assert (
        effective_pill_metric(AppSettings(minimized_metric="auto", show_total=True))
        == "auto"
    )


def test_pace_sync_folder_default_empty(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(AppSettings(), path)
    loaded = load_settings(path)
    assert loaded.pace_sync_folder == ""


def test_pace_sync_folder_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    folder = str(tmp_path / "GDrive" / "cursor-usage-float")
    original = AppSettings(pace_sync_folder=folder)
    save_settings(original, path)
    assert load_settings(path).pace_sync_folder == folder


def test_resolve_pace_history_path_default() -> None:
    assert resolve_pace_history_path("") == default_history_path()
    assert resolve_pace_history_path("   ") == default_history_path()


def test_resolve_pace_history_path_custom(tmp_path: Path) -> None:
    folder = tmp_path / "sync"
    resolved = resolve_pace_history_path(str(folder))
    assert resolved == folder / "pace-history.json"


def test_active_pace_history_path_falls_back_when_sync_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    from pace_history import active_pace_history_path

    local = tmp_path / "local" / "pace-history.json"
    unavailable = tmp_path / "missing-drive" / "sync"
    monkeypatch.setattr("pace_history.default_history_path", lambda: local)

    assert active_pace_history_path(str(unavailable)) == local


def test_active_pace_history_path_uses_available_sync_folder(tmp_path: Path) -> None:
    from pace_history import active_pace_history_path

    sync_folder = tmp_path / "sync"
    sync_folder.mkdir()

    assert active_pace_history_path(str(sync_folder)) == (
        sync_folder / "pace-history.json"
    )


def test_seed_history_copies_when_destination_missing(tmp_path: Path) -> None:
    from pace_history import seed_history_if_needed

    src = tmp_path / "local" / "pace-history.json"
    dst = tmp_path / "drive" / "pace-history.json"
    src.parent.mkdir(parents=True)
    src.write_text('{"burns":[],"last_used":1,"unit":"percent","day_start":null}\n')
    assert seed_history_if_needed(src, dst) is True
    assert dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    assert seed_history_if_needed(src, dst) is False  # already exists


def test_apply_pace_sync_folder_seeds(tmp_path: Path) -> None:
    from pace_history import apply_pace_sync_folder, resolve_pace_history_path

    local = resolve_pace_history_path("")
    # Use tmp as "previous" by writing via apply from empty→folder after planting local
    # Simulate: old folder empty (local default under tmp via monkeypatch-like path)
    old_folder = str(tmp_path / "old")
    new_folder = str(tmp_path / "new")
    old_path = resolve_pace_history_path(old_folder)
    old_path.parent.mkdir(parents=True)
    old_path.write_text('{"burns":[],"last_used":2,"unit":"percent","day_start":null}\n')
    result = apply_pace_sync_folder(old_folder, new_folder)
    assert result == new_folder
    assert resolve_pace_history_path(result).is_file()


def test_resolve_sync_settings_path(tmp_path: Path) -> None:
    from settings import resolve_sync_settings_path

    assert resolve_sync_settings_path("") is None
    assert resolve_sync_settings_path("  ") is None
    assert resolve_sync_settings_path(str(tmp_path / "sync")) == tmp_path / "sync" / "settings.json"


def test_save_load_merges_synced_settings(tmp_path: Path, monkeypatch) -> None:
    from settings import load_settings, save_settings

    local = tmp_path / "local" / "settings.json"
    sync_dir = tmp_path / "gdrive"
    monkeypatch.setattr("settings.default_settings_path", lambda: local)

    # Local only knows the sync folder path for this PC
    save_settings(AppSettings(pace_sync_folder=str(sync_dir), density="full"))
    # Shared file has appearance prefs from the other PC (overwrite seeded copy)
    shared = sync_dir / "settings.json"
    shared.write_text(
        json.dumps(
            {
                "density": "compact",
                "click_through": True,
                "pace_sync_folder": "C:\\\\OtherPC\\\\DifferentPath",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_settings()
    assert loaded.density == "compact"
    assert loaded.click_through is True
    # Local machine path always wins
    assert loaded.pace_sync_folder == str(sync_dir)


def test_save_settings_writes_shared_copy(tmp_path: Path, monkeypatch) -> None:
    from settings import load_settings, save_settings

    local = tmp_path / "local" / "settings.json"
    sync_dir = tmp_path / "gdrive"
    monkeypatch.setattr("settings.default_settings_path", lambda: local)

    save_settings(
        AppSettings(pace_sync_folder=str(sync_dir), density="minimal", show_pace=False)
    )
    assert local.is_file()
    shared = sync_dir / "settings.json"
    assert shared.is_file()
    shared_data = json.loads(shared.read_text(encoding="utf-8"))
    assert shared_data["density"] == "minimal"
    assert shared_data["show_pace"] is False

    # Reload picks shared values with local folder path
    loaded = load_settings()
    assert loaded.density == "minimal"
    assert loaded.show_pace is False
    assert loaded.pace_sync_folder == str(sync_dir)


def test_save_settings_keeps_local_copy_when_sync_folder_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    local = tmp_path / "local" / "settings.json"
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr("settings.default_settings_path", lambda: local)

    save_settings(AppSettings(pace_sync_folder=str(blocked), density="compact"))

    assert local.is_file()
    assert load_settings(local).density == "compact"


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

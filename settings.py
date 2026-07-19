"""Persisted LAYOUT settings for the Cursor usage floater."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from cursor_usage import PlanUsage
from sync_status import record_sync_error, record_sync_success

DENSITY_OPTIONS = ("full", "compact", "minimal")
METRIC_OPTIONS = ("total", "auto", "api", "worst", "pace")


@dataclass
class AppSettings:
    density: str = "full"  # full | compact | minimal
    always_on_top: bool = True
    click_through: bool = False
    show_header: bool = True
    show_reset_countdown: bool = True
    show_stale_badge: bool = True
    show_total: bool = True
    show_pace: bool = True
    minimized_metric: str = "pace"  # total | auto | api | worst | pace
    start_minimized: bool = False  # open hidden (pill) on launch
    start_with_windows: bool = False
    # Shared folder for pace-history.json + settings.json (e.g. Google Drive).
    # Empty = local APPDATA only. Path itself stays machine-local (Drive letter may differ).
    pace_sync_folder: str = ""


def default_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return Path.home() / ".cursor-usage-float" / "settings.json"
    return Path(appdata) / "cursor-usage-float" / "settings.json"


def resolve_sync_settings_path(sync_folder: str) -> Path | None:
    """Return shared settings.json under sync folder, or None if unset."""
    folder = (sync_folder or "").strip().strip('"')
    if not folder:
        return None
    return Path(folder).expanduser() / "settings.json"


def _normalize(data: dict[str, Any]) -> AppSettings:
    defaults = AppSettings()
    values: dict[str, Any] = {}
    for f in fields(AppSettings):
        if f.name not in data:
            values[f.name] = getattr(defaults, f.name)
            continue
        raw = data[f.name]
        expected = type(getattr(defaults, f.name))
        if not isinstance(raw, expected):
            values[f.name] = getattr(defaults, f.name)
            continue
        values[f.name] = raw

    if values["density"] not in DENSITY_OPTIONS:
        values["density"] = defaults.density
    if values["minimized_metric"] not in METRIC_OPTIONS:
        values["minimized_metric"] = defaults.minimized_metric
    settings = AppSettings(**values)
    ensure_usage_section_visible(settings)
    return settings


def ensure_usage_section_visible(settings: AppSettings) -> AppSettings:
    """Keep at least one of Total / Today's pace visible; align pill metric."""
    if not settings.show_total and not settings.show_pace:
        settings.show_total = True
    if settings.minimized_metric == "pace" and not settings.show_pace:
        settings.minimized_metric = "total"
    elif (
        settings.minimized_metric != "pace"
        and not settings.show_total
        and settings.show_pace
    ):
        settings.minimized_metric = "pace"
    return settings


def effective_pill_metric(settings: AppSettings) -> str:
    """Pill metric respecting which usage sections are enabled."""
    metric = settings.minimized_metric
    if metric == "pace":
        if settings.show_pace:
            return "pace"
        return "total"
    if not settings.show_total and settings.show_pace:
        return "pace"
    return metric


def _read_settings_file(settings_path: Path) -> AppSettings:
    if not settings_path.is_file():
        return AppSettings()
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(payload, dict):
        return AppSettings()
    return _normalize(payload)


def _write_settings_file(settings_path: Path, settings: AppSettings) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(asdict(settings), indent=2) + "\n",
        encoding="utf-8",
    )


def load_settings(path: Path | None = None) -> AppSettings:
    """
    Load settings.

    If ``path`` is given, read only that file (tests / explicit).
    If omitted, read local APPDATA settings, then overlay shared sync copy
    when ``pace_sync_folder`` is set. The local ``pace_sync_folder`` always wins
    so each PC can point at its own Drive path.
    """
    if path is not None:
        return _read_settings_file(path)

    local = _read_settings_file(default_settings_path())
    shared_path = resolve_sync_settings_path(local.pace_sync_folder)
    if shared_path is None or not shared_path.is_file():
        return local

    synced = _read_settings_file(shared_path)
    synced.pace_sync_folder = local.pace_sync_folder
    return synced


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    """
    Save settings.

    If ``path`` is given, write only that file.
    If omitted, write local APPDATA and also the shared sync copy when set.
    """
    if path is not None:
        _write_settings_file(path, settings)
        return

    _write_settings_file(default_settings_path(), settings)
    shared_path = resolve_sync_settings_path(settings.pace_sync_folder)
    if shared_path is not None:
        try:
            _write_settings_file(shared_path, settings)
            record_sync_success()
        except OSError as exc:
            # Google Drive / OneDrive can be offline or expose a temporarily
            # unavailable virtual path. Local settings must remain usable.
            record_sync_error(str(exc))


def seed_settings_if_needed(source: Path, destination: Path) -> bool:
    """Copy settings to destination when missing. Returns True if copied."""
    if destination.is_file() or not source.is_file() or source == destination:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return True


def resolve_minimized_percent(usage: PlanUsage, metric: str) -> float:
    if metric == "auto":
        return usage.auto_percent
    if metric == "api":
        return usage.api_percent
    if metric == "worst":
        return max(usage.total_percent, usage.auto_percent, usage.api_percent)
    # "pace" is rendered separately in the pill; fall back to total for ring %
    return usage.total_percent


def format_percent(value: float) -> str:
    """Always show one decimal place (e.g. 42.9%)."""
    value = max(0.0, min(100.0, float(value)))
    return f"{value:.1f}%"


def effective_click_through(click_through: bool, settings_open: bool) -> bool:
    """Click-through is soft-disabled while Settings is open."""
    return bool(click_through) and not bool(settings_open)

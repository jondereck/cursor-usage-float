"""Persisted LAYOUT settings for the Cursor usage floater."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from cursor_usage import PlanUsage

DENSITY_OPTIONS = ("full", "compact", "minimal")
METRIC_OPTIONS = ("total", "auto", "api", "worst")


@dataclass
class AppSettings:
    density: str = "full"  # full | compact | minimal
    always_on_top: bool = True
    click_through: bool = False
    show_header: bool = True
    show_reset_countdown: bool = True
    show_stale_badge: bool = True
    minimized_metric: str = "total"  # total | auto | api | worst
    start_minimized: bool = False


def default_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return Path.home() / ".cursor-usage-float" / "settings.json"
    return Path(appdata) / "cursor-usage-float" / "settings.json"


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
    return AppSettings(**values)


def load_settings(path: Path | None = None) -> AppSettings:
    settings_path = path or default_settings_path()
    if not settings_path.is_file():
        return AppSettings()
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(payload, dict):
        return AppSettings()
    return _normalize(payload)


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    settings_path = path or default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(asdict(settings), indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_minimized_percent(usage: PlanUsage, metric: str) -> float:
    if metric == "auto":
        return usage.auto_percent
    if metric == "api":
        return usage.api_percent
    if metric == "worst":
        return max(usage.total_percent, usage.auto_percent, usage.api_percent)
    return usage.total_percent


def format_percent(value: float) -> str:
    """Always show one decimal place (e.g. 42.9%)."""
    value = max(0.0, min(100.0, float(value)))
    return f"{value:.1f}%"

"""Local daily burn history for weekday weight learning and usedToday."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pacing import HISTORY_DAYS, DailyBurn, learn_weekday_weights


def default_history_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return Path.home() / ".cursor-usage-float" / "pace-history.json"
    return Path(appdata) / "cursor-usage-float" / "pace-history.json"


@dataclass
class DayStart:
    day: date
    used: float


@dataclass
class PaceHistory:
    day_start: DayStart | None
    burns: list[DailyBurn]
    last_used: float | None = None
    unit: str = "percent"  # "percent" | "cents"


def _parse_day(value: str) -> date:
    return date.fromisoformat(value)


def load_history(path: Path | None = None) -> PaceHistory:
    history_path = path or default_history_path()
    if not history_path.is_file():
        return PaceHistory(day_start=None, burns=[], last_used=None)
    try:
        payload = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PaceHistory(day_start=None, burns=[], last_used=None)
    if not isinstance(payload, dict):
        return PaceHistory(day_start=None, burns=[], last_used=None)

    day_start = None
    raw_start = payload.get("day_start")
    if isinstance(raw_start, dict) and "day" in raw_start and "used" in raw_start:
        try:
            day_start = DayStart(
                day=_parse_day(str(raw_start["day"])),
                used=float(raw_start["used"]),
            )
        except (TypeError, ValueError):
            day_start = None

    burns: list[DailyBurn] = []
    for item in payload.get("burns") or []:
        if not isinstance(item, dict):
            continue
        try:
            burns.append(
                DailyBurn(day=_parse_day(str(item["day"])), burn=float(item["burn"]))
            )
        except (KeyError, TypeError, ValueError):
            continue

    last_used = None
    if payload.get("last_used") is not None:
        try:
            last_used = float(payload["last_used"])
        except (TypeError, ValueError):
            last_used = None

    unit = str(payload.get("unit") or "percent")
    if unit not in ("percent", "cents"):
        unit = "percent"

    return PaceHistory(
        day_start=day_start, burns=burns, last_used=last_used, unit=unit
    )


def save_history(history: PaceHistory, path: Path | None = None) -> None:
    history_path = path or default_history_path()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "burns": [{"day": b.day.isoformat(), "burn": b.burn} for b in history.burns],
        "last_used": history.last_used,
        "unit": history.unit,
        "day_start": None,
    }
    if history.day_start is not None:
        payload["day_start"] = {
            "day": history.day_start.day.isoformat(),
            "used": history.day_start.used,
        }
    history_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _prune_burns(burns: list[DailyBurn], today: date) -> list[DailyBurn]:
    cutoff = today - timedelta(days=HISTORY_DAYS)
    by_day: dict[date, float] = {}
    for b in burns:
        if b.day >= cutoff:
            by_day[b.day] = by_day.get(b.day, 0.0) + b.burn
    return [DailyBurn(day=d, burn=v) for d, v in sorted(by_day.items())]


def _needs_rebaseline(day_start: DayStart, used: float, unit: str, prev_unit: str) -> bool:
    """True when baseline is from another unit/scale or cycle reset."""
    if unit != prev_unit:
        return True
    # Cycle reset or unit switch: current used jumped below the baseline
    if used + 0.05 < day_start.used:
        return True
    # Percent baseline cannot exceed 100; huge values are leftover cents
    if unit == "percent" and day_start.used > 100.0:
        return True
    return False


def record_usage_point(
    history: PaceHistory,
    *,
    used: float,
    unit: str = "percent",
    now: datetime | None = None,
) -> tuple[PaceHistory, float, list[float]]:
    """
    Update history with a new cycle `used` reading.

    Returns (updated_history, used_today, weekday_weights).
    """
    now = now or datetime.now()
    today = now.date()
    used = max(0.0, float(used))
    unit = unit if unit in ("percent", "cents") else "percent"
    burns = list(history.burns)
    day_start = history.day_start
    prev_unit = history.unit or "percent"

    if day_start is not None and _needs_rebaseline(day_start, used, unit, prev_unit):
        # Drop incompatible baseline so today's counter can move again
        day_start = DayStart(day=today, used=used)
        burns = []  # old burns were likely in a different unit/scale
    elif day_start is None:
        day_start = DayStart(day=today, used=used)
    elif day_start.day < today:
        # Finalize previous day(s): burn = last_used - day_start.used
        prev_end = history.last_used if history.last_used is not None else used
        burn = max(0.0, prev_end - day_start.used)
        if burn > 0 or day_start.day not in {b.day for b in burns}:
            burns.append(DailyBurn(day=day_start.day, burn=burn))
        day_start = DayStart(day=today, used=used)
    elif day_start.day > today:
        day_start = DayStart(day=today, used=used)

    # Heal a corrupt same-day baseline (e.g. leftover after unit bugs) that
    # makes "used today" look like most of the cycle instead of today's burn.
    used_today = max(0.0, used - day_start.used)
    if unit == "percent" and used_today > 10.0:
        # Snap baseline to current reading — counter restarts cleanly from here
        day_start = DayStart(day=today, used=used)
        used_today = 0.0

    burns = _prune_burns(burns, today)
    weights = learn_weekday_weights(burns, today=today)
    updated = PaceHistory(
        day_start=day_start, burns=burns, last_used=used, unit=unit
    )
    return updated, used_today, weights


def reset_today_baseline(
    history: PaceHistory,
    *,
    used: float,
    unit: str = "percent",
    now: datetime | None = None,
) -> PaceHistory:
    """
    Reset local 'used today' counting to zero by re-baselining at current used.

    Keeps weekday burn history for learning. Does not change Cursor usage.
    """
    now = now or datetime.now()
    today = now.date()
    used = max(0.0, float(used))
    unit = unit if unit in ("percent", "cents") else "percent"
    return PaceHistory(
        day_start=DayStart(day=today, used=used),
        burns=list(history.burns),
        last_used=used,
        unit=unit,
    )

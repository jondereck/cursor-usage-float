"""Weekday-aware daily pace / soft-stop math (pure functions)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Sequence

SoftStopState = Literal["OK", "WARN", "STOP"]

WARN_THRESHOLD = 0.8
STOP_THRESHOLD = 1.0
WEEKDAY_FLOOR_RATIO = 0.15
HISTORY_DAYS = 28

# Index 0 = Sunday … 6 = Saturday (datetime.weekday is Mon=0; we use date.weekday
# mapped via date.isoweekday / Sunday-first via .weekday() differently)
# Use datetime.timetuple().tm_wday where Monday=0 … OR use date.strftime
# We standardize on Python's datetime.weekday(): Monday=0 … Sunday=6
# Display helpers convert as needed.

DEFAULT_WEIGHTS: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.5)
# Mon…Sun order to match datetime.weekday()


def default_weights() -> list[float]:
    total = sum(DEFAULT_WEIGHTS)
    return [w / total for w in DEFAULT_WEIGHTS]


@dataclass(frozen=True)
class DailyBurn:
    day: date
    burn: float


@dataclass(frozen=True)
class PaceResult:
    fair_today: float
    used_today: float
    percent_of_fair: float
    state: SoftStopState
    days_left: int
    today_weight: float
    weight_sum_remaining: float
    message: str


def learn_weekday_weights(
    burns: Sequence[DailyBurn],
    *,
    today: date | None = None,
    history_days: int = HISTORY_DAYS,
) -> list[float]:
    """Learn Mon–Sun weights from daily burns; normalize with a floor."""
    today = today or date.today()
    cutoff = today - timedelta(days=history_days)
    sums = [0.0] * 7
    total = 0.0
    for b in burns:
        if b.day < cutoff or b.burn <= 0:
            continue
        sums[b.day.weekday()] += b.burn
        total += b.burn

    if total <= 0:
        return default_weights()

    avg = total / 7.0
    floor = avg * WEEKDAY_FLOOR_RATIO
    floored = [max(s, floor) for s in sums]
    floored_total = sum(floored)
    return [s / floored_total for s in floored]


def remaining_calendar_days(now: datetime, cycle_end: datetime) -> list[date]:
    start = now.date()
    end = cycle_end.date()
    if end < start:
        return [start]
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days or [start]


def sum_weights_for_days(days: Sequence[date], weights: Sequence[float]) -> float:
    return sum(weights[d.weekday()] for d in days)


def soft_stop_state(percent_of_fair: float) -> SoftStopState:
    if percent_of_fair >= STOP_THRESHOLD:
        return "STOP"
    if percent_of_fair >= WARN_THRESHOLD:
        return "WARN"
    return "OK"


def soft_stop_message(state: SoftStopState, percent_of_fair: float) -> str:
    if state == "STOP":
        return "Stop for now — save allotment for later in the cycle"
    if state == "WARN":
        return f"Slow down — {round(percent_of_fair * 100)}% of today's budget"
    return "On pace for today"


def compute_pace(
    *,
    remaining: float,
    billing_cycle_end: datetime,
    now: datetime,
    weights: Sequence[float],
    used_today: float,
) -> PaceResult:
    days = remaining_calendar_days(now, billing_cycle_end)
    weight_sum = sum_weights_for_days(days, weights)
    today_weight = float(weights[now.weekday()])
    rem = max(0.0, float(remaining))
    fair = rem * (today_weight / weight_sum) if weight_sum > 0 else rem
    used = max(0.0, float(used_today))
    if fair > 0:
        pct = used / fair
    else:
        pct = 2.0 if used > 0 else 0.0
    state = soft_stop_state(pct)
    return PaceResult(
        fair_today=fair,
        used_today=used,
        percent_of_fair=pct,
        state=state,
        days_left=len(days),
        today_weight=today_weight,
        weight_sum_remaining=weight_sum,
        message=soft_stop_message(state, pct),
    )


def format_units(n: float) -> str:
    if n != n:  # NaN
        return "—"
    if n >= 100:
        return str(int(round(n)))
    return f"{n:.1f}"


def format_compact(used_today: float, fair_today: float) -> str:
    return f"{format_units(used_today)} / {format_units(fair_today)} today"


WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

"""Unit tests for weekday pace math and soft-stop."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pacing import (
    compute_pace,
    default_weights,
    learn_weekday_weights,
    remaining_calendar_days,
    soft_stop_state,
    DailyBurn,
)


def test_soft_stop_thresholds() -> None:
    assert soft_stop_state(0.79) == "OK"
    assert soft_stop_state(0.8) == "WARN"
    assert soft_stop_state(1.0) == "STOP"


def test_learn_weights_weekday_heavy() -> None:
    burns = []
    for week in range(4):
        burns.append(DailyBurn(day=date(2026, 6, 1) + timedelta(weeks=week), burn=50))
        burns.append(DailyBurn(day=date(2026, 6, 6) + timedelta(weeks=week), burn=1))
    weights = learn_weekday_weights(burns, today=date(2026, 7, 15))
    assert weights[0] > weights[5]  # Mon > Sat
    assert abs(sum(weights) - 1.0) < 1e-6
    assert all(w > 0 for w in weights)


def test_remaining_calendar_days() -> None:
    now = datetime(2026, 7, 15, 8, 0, 0)
    end = datetime(2026, 7, 17, 23, 0, 0)
    days = remaining_calendar_days(now, end)
    assert len(days) == 3


def test_compute_pace_equal_split_for_two_remaining_days() -> None:
    # Legacy weights do not affect the equal daily split.
    weights = [0.2, 0.2, 0.2, 0.2, 0.1, 0.05, 0.05]
    now = datetime(2026, 7, 15, 10, 0, 0)  # Wednesday = index 2
    end = datetime(2026, 7, 16, 10, 0, 0)  # Wed + Thu
    result = compute_pace(
        remaining=100,
        billing_cycle_end=end,
        now=now,
        weights=weights,
        used_today=0,
    )
    # Wed 0.2 / (0.2+0.2) = 0.5
    assert abs(result.fair_today - 50.0) < 1e-6
    assert result.state == "OK"
    assert result.days_left == 2


def test_compute_pace_splits_pool_equally_not_by_weekday_weight() -> None:
    weights = [0.1, 0.1, 0.9, 0.1, 0.1, 0.1, 0.1]
    now = datetime(2026, 7, 15, 10, 0, 0)  # Wednesday
    end = datetime(2026, 7, 16, 10, 0, 0)  # Wednesday + Thursday

    result = compute_pace(
        remaining=80,
        billing_cycle_end=end,
        now=now,
        weights=weights,
        used_today=20,
    )

    assert result.fair_today == 50.0
    assert result.today_weight == 0.5


def test_compute_pace_keeps_today_budget_stable_as_usage_grows() -> None:
    weights = [0.2, 0.2, 0.2, 0.2, 0.1, 0.05, 0.05]
    now = datetime(2026, 7, 15, 10, 0, 0)  # Wednesday
    end = datetime(2026, 7, 16, 10, 0, 0)  # Wednesday + Thursday

    morning = compute_pace(
        remaining=100,
        billing_cycle_end=end,
        now=now,
        weights=weights,
        used_today=0,
    )
    later = compute_pace(
        remaining=80,
        billing_cycle_end=end,
        now=now,
        weights=weights,
        used_today=20,
    )

    assert morning.fair_today == 50.0
    assert later.fair_today == morning.fair_today
    assert later.percent_of_fair == 0.4


def test_compute_pace_stop_message() -> None:
    now = datetime(2026, 7, 15, 10, 0, 0)
    end = datetime(2026, 7, 16, 23, 0, 0)
    result = compute_pace(
        remaining=40,
        billing_cycle_end=end,
        now=now,
        weights=default_weights(),
        used_today=45,
    )
    assert result.state == "STOP"
    assert "save allotment" in result.message.lower()
    assert "tama" not in result.message.lower()


def test_budget_from_plan_prefers_percent() -> None:
    from cursor_usage import PlanUsage, budget_from_plan

    pct = budget_from_plan(
        PlanUsage(total_percent=30.0, auto_percent=10.0, api_percent=20.0)
    )
    assert pct.unit == "percent"
    assert pct.remaining == 70.0

    # Percent wins even when cents are present (clearer pace UI)
    mixed = budget_from_plan(
        PlanUsage(
            total_percent=30.0,
            auto_percent=10.0,
            api_percent=20.0,
            total_spend_cents=2500,
            limit_cents=10000,
        )
    )
    assert mixed.unit == "percent"
    assert mixed.remaining == 70.0

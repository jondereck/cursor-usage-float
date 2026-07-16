"""Tests for local pace history / usedToday tracking."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pace_history import DayStart, PaceHistory, load_history, record_usage_point, save_history
from pacing import DailyBurn


def test_history_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "pace.json"
    hist = PaceHistory(
        day_start=DayStart(day=date(2026, 7, 15), used=10.0),
        burns=[DailyBurn(day=date(2026, 7, 14), burn=5.0)],
        last_used=12.0,
    )
    save_history(hist, path)
    loaded = load_history(path)
    assert loaded.day_start is not None
    assert loaded.day_start.used == 10.0
    assert loaded.burns[0].burn == 5.0
    assert loaded.last_used == 12.0


def test_used_today_same_day(tmp_path: Path) -> None:
    path = tmp_path / "pace.json"
    hist = PaceHistory(day_start=None, burns=[], last_used=None)
    now = datetime(2026, 7, 15, 9, 0, 0)
    hist, used, _weights = record_usage_point(hist, used=40.0, now=now)
    save_history(hist, path)
    assert used == 0.0  # baseline set at first reading
    hist2, used2, _ = record_usage_point(hist, used=45.5, now=datetime(2026, 7, 15, 18, 0, 0))
    assert abs(used2 - 5.5) < 1e-6
    assert hist2.day_start is not None
    assert hist2.day_start.used == 40.0


def test_day_rollover_records_burn() -> None:
    hist = PaceHistory(
        day_start=DayStart(day=date(2026, 7, 14), used=10.0),
        burns=[],
        last_used=18.0,
    )
    hist2, used_today, weights = record_usage_point(
        hist, used=20.0, now=datetime(2026, 7, 15, 10, 0, 0)
    )
    assert any(b.day == date(2026, 7, 14) and abs(b.burn - 8.0) < 1e-6 for b in hist2.burns)
    assert used_today == 0.0  # new day baseline is current used
    assert abs(sum(weights) - 1.0) < 1e-6


def test_reset_today_baseline_zeros_used_today() -> None:
    from pace_history import reset_today_baseline

    hist = PaceHistory(
        day_start=DayStart(day=date(2026, 7, 15), used=10.0),
        burns=[DailyBurn(day=date(2026, 7, 14), burn=5.0)],
        last_used=25.0,
    )
    reset = reset_today_baseline(
        hist, used=25.0, now=datetime(2026, 7, 15, 18, 0, 0)
    )
    assert reset.day_start is not None
    assert reset.day_start.used == 25.0
    assert len(reset.burns) == 1  # history kept
    _, used_today, _ = record_usage_point(
        reset, used=25.0, now=datetime(2026, 7, 15, 18, 5, 0)
    )
    assert used_today == 0.0


def test_rebaseline_when_day_start_is_old_cents_vs_percent() -> None:
    hist = PaceHistory(
        day_start=DayStart(day=date(2026, 7, 16), used=15112.0),
        burns=[],
        last_used=44.9,
        unit="cents",
    )
    updated, used_today, _ = record_usage_point(
        hist,
        used=45.2,
        unit="percent",
        now=datetime(2026, 7, 16, 10, 0, 0),
    )
    assert updated.day_start is not None
    assert abs(updated.day_start.used - 45.2) < 1e-6
    assert used_today == 0.0  # rebaselined at current
    # Next tick should track delta again
    _, used2, _ = record_usage_point(
        updated,
        used=46.0,
        unit="percent",
        now=datetime(2026, 7, 16, 10, 5, 0),
    )
    assert abs(used2 - 0.8) < 1e-6


def test_heal_absurd_same_day_used_today() -> None:
    """Corrupt baseline (e.g. 10) vs current ~45 must not report 35% used today."""
    hist = PaceHistory(
        day_start=DayStart(day=date(2026, 7, 16), used=10.0),
        burns=[],
        last_used=44.9,
        unit="percent",
    )
    updated, used_today, _ = record_usage_point(
        hist,
        used=45.0,
        unit="percent",
        now=datetime(2026, 7, 16, 12, 0, 0),
    )
    assert used_today == 0.0
    assert updated.day_start is not None
    assert abs(updated.day_start.used - 45.0) < 1e-6
    # Next real burn after heal should still track
    _, used2, _ = record_usage_point(
        updated,
        used=45.4,
        unit="percent",
        now=datetime(2026, 7, 16, 12, 5, 0),
    )
    assert abs(used2 - 0.4) < 1e-6

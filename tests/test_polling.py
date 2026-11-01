"""Tests for the adaptive refresh cadence."""

from __future__ import annotations

from polling import FAST_POLL_MS, MEDIUM_POLL_MS, SLOW_POLL_MS, poll_interval_ms


def test_recent_input_uses_fast_cadence() -> None:
    assert poll_interval_ms(0) == FAST_POLL_MS
    assert poll_interval_ms(119) == FAST_POLL_MS


def test_recent_usage_change_boosts_even_while_idle() -> None:
    assert poll_interval_ms(60 * 60, since_change_s=10) == FAST_POLL_MS


def test_old_usage_change_does_not_boost() -> None:
    assert poll_interval_ms(60 * 60, since_change_s=600) == SLOW_POLL_MS


def test_mid_idle_uses_medium_cadence() -> None:
    assert poll_interval_ms(5 * 60) == MEDIUM_POLL_MS
    assert poll_interval_ms(9 * 60) == MEDIUM_POLL_MS


def test_long_idle_uses_slow_cadence() -> None:
    assert poll_interval_ms(60 * 60) == SLOW_POLL_MS


def test_unknown_idle_falls_back_to_slow() -> None:
    assert poll_interval_ms(None) == SLOW_POLL_MS
    assert poll_interval_ms(None, since_change_s=5) == FAST_POLL_MS

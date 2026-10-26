from __future__ import annotations

import pytest
from codex_usage import CodexError, parse_codex_usage


def test_parse_codex_usage_success():
    payload = {
        "plan_type": "go",
        "rate_limit": {
            "allowed": True,
            "limit_reached": False,
            "primary_window": {
                "used_percent": 24.5,
                "limit_window_seconds": 2592000,
                "reset_after_seconds": 2592000,
                "reset_at": 1795615711,
            },
            "secondary_window": {
                "used_percent": 10.0,
                "reset_at": 1795615711,
            },
        },
    }
    usage = parse_codex_usage(payload)
    assert usage.is_eligible is True
    assert usage.usage_percent == 24.5
    assert usage.plan_type == "go"
    assert usage.limit_reached is False
    assert usage.primary_window is not None
    assert usage.primary_window.used_percent == 24.5
    assert usage.secondary_window is not None
    assert usage.secondary_window.used_percent == 10.0
    assert usage.next_reset is not None


def test_parse_codex_usage_missing_rate_limit():
    with pytest.raises(CodexError):
        parse_codex_usage({"plan_type": "go"})


def test_parse_codex_usage_no_windows():
    with pytest.raises(CodexError):
        parse_codex_usage({"rate_limit": {"allowed": True}})

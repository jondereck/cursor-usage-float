"""Usage parsing and Cursor-dashboard-matching display."""

from __future__ import annotations

import pytest

from cursor_usage import (
    GrokBotUsage,
    PlanUsage,
    UsageError,
    budget_from_plan,
    parse_grok_bot_usage,
    parse_plan_usage,
)
from settings import format_usage_percent, resolve_minimized_percent


def test_parse_plan_usage_reads_auto_and_api_pools() -> None:
    usage = parse_plan_usage(
        {
            "planUsage": {
                "totalPercentUsed": 9.2,
                "autoPercentUsed": 10.6,
                "apiPercentUsed": 0.0,
            }
        }
    )
    assert usage.total_percent == 9.2
    assert usage.auto_percent == 10.6
    assert usage.api_percent == 0.0


def test_format_usage_percent_matches_cursor_whole_numbers() -> None:
    assert format_usage_percent(10.6) == "11%"
    assert format_usage_percent(0.0) == "0%"
    assert format_usage_percent(11.4) == "11%"


def test_budget_from_plan_uses_cursor_models_pool() -> None:
    """Pace follows Cursor Models (auto), not the old blended Total."""
    budget = budget_from_plan(
        PlanUsage(total_percent=9.2, auto_percent=10.6, api_percent=0.0)
    )
    assert budget.unit == "percent"
    assert budget.used == 10.6
    assert abs(budget.remaining - 89.4) < 1e-9


def test_budget_from_plan_uses_higher_of_the_two_pools() -> None:
    budget = budget_from_plan(
        PlanUsage(total_percent=5.0, auto_percent=10.0, api_percent=40.0)
    )
    assert budget.used == 40.0
    assert budget.remaining == 60.0


def test_pill_total_metric_uses_cursor_models() -> None:
    usage = PlanUsage(total_percent=9.2, auto_percent=10.6, api_percent=0.0)
    assert resolve_minimized_percent(usage, "total") == 10.6
    assert resolve_minimized_percent(usage, "auto") == 10.6
    assert resolve_minimized_percent(usage, "api") == 0.0


def test_parse_grok_bot_usage_reads_weekly_percent() -> None:
    usage = parse_grok_bot_usage(
        {
            "usagePercent": 23.4,
            "hasNonZeroIncludedLimit": True,
            "usesPooledEnterpriseAllowance": False,
            "nextResetTimestampUtc": "2026-10-19T00:00:00.000Z",
        }
    )
    assert usage.usage_percent == 23.4
    assert usage.is_eligible is True
    assert usage.next_reset == "2026-10-19T00:00:00.000Z"


def test_grok_bot_ineligible_without_included_limit() -> None:
    usage = parse_grok_bot_usage(
        {
            "usagePercent": 0.0,
            "hasNonZeroIncludedLimit": False,
            "usesPooledEnterpriseAllowance": False,
        }
    )
    assert usage.is_eligible is False


def test_grok_bot_ineligible_pooled_enterprise() -> None:
    usage = parse_grok_bot_usage(
        {
            "usagePercent": 10.0,
            "hasNonZeroIncludedLimit": True,
            "usesPooledEnterpriseAllowance": True,
        }
    )
    assert usage.is_eligible is False


def test_grok_bot_missing_usage_percent_raises() -> None:
    with pytest.raises(UsageError):
        parse_grok_bot_usage({"hasNonZeroIncludedLimit": True})


def test_pill_grok_metric_uses_grok_bot_percent() -> None:
    usage = PlanUsage(total_percent=9.2, auto_percent=10.6, api_percent=0.0)
    grok = GrokBotUsage(
        usage_percent=42.0,
        has_nonzero_included_limit=True,
    )
    assert resolve_minimized_percent(usage, "grok", grok=grok) == 42.0
    assert resolve_minimized_percent(usage, "grok", grok=None) == 10.6

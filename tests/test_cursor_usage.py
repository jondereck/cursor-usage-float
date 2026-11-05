"""Usage parsing and Cursor-dashboard-matching display."""

from __future__ import annotations

import pytest

from cursor_usage import (
    GrokBotUsage,
    PlanUsage,
    TokenUsage,
    UsageError,
    budget_from_plan,
    parse_aggregated_token_usage,
    parse_grok_bot_usage,
    parse_plan_usage,
)
from settings import (
    format_cursor_usage_percent,
    format_usage_percent,
    resolve_minimized_percent,
)


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


def test_format_cursor_usage_percent_one_decimal() -> None:
    assert format_cursor_usage_percent(15.14) == "15.1%"
    assert format_cursor_usage_percent(10.6) == "10.6%"
    assert format_cursor_usage_percent(0.0) == "0.0%"


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


def test_parse_aggregated_token_usage_sums_quoted_totals() -> None:
    usage = parse_aggregated_token_usage(
        {
            "totalInputTokens": "191242",
            "totalOutputTokens": "9251",
            "totalCacheReadTokens": "1505024",
            "totalCostCents": 119.0502,
            "startDate": "1793491200000",
        }
    )
    assert usage.input_tokens == 191242
    assert usage.output_tokens == 9251
    assert usage.cache_read_tokens == 1505024
    assert usage.total_tokens == 191242 + 9251 + 1505024
    assert usage.cost_cents == pytest.approx(119.0502)
    assert usage.start_date == "1793491200000"
    assert usage.is_eligible is True


def test_parse_aggregated_token_usage_falls_back_to_aggregations() -> None:
    usage = parse_aggregated_token_usage(
        {
            "aggregations": [
                {
                    "inputTokens": "100",
                    "outputTokens": "10",
                    "cacheReadTokens": "1000",
                },
                {
                    "inputTokens": "5",
                    "outputTokens": "2",
                    "cacheReadTokens": "50",
                },
            ]
        }
    )
    assert usage.input_tokens == 105
    assert usage.output_tokens == 12
    assert usage.cache_read_tokens == 1050
    assert usage.total_tokens == 1167


def test_parse_aggregated_token_usage_empty_is_not_eligible() -> None:
    usage = parse_aggregated_token_usage(
        {"totalInputTokens": "0", "totalOutputTokens": "0", "totalCacheReadTokens": "0"}
    )
    assert usage.total_tokens == 0
    assert usage.is_eligible is False


def test_parse_aggregated_token_usage_missing_totals_raises() -> None:
    with pytest.raises(UsageError):
        parse_aggregated_token_usage({"aggregations": []})


def test_token_usage_defaults_are_zero() -> None:
    usage = TokenUsage()
    assert usage.total_tokens == 0
    assert usage.is_eligible is False


def test_cursor_subtext_appends_tokens_before_reset() -> None:
    from main import _cursor_subtext

    usage = PlanUsage(
        total_percent=62.0,
        auto_percent=62.0,
        api_percent=0.0,
        billing_cycle_end="1794149651921",
    )
    tokens = TokenUsage(
        input_tokens=191242,
        output_tokens=9251,
        cache_read_tokens=1505024,
    )
    text = _cursor_subtext(
        usage,
        None,
        show_email=False,
        token_usage=tokens,
    )
    assert "1.7M tokens" in text
    assert text.index("1.7M tokens") < text.index("Resets in")


def test_cursor_subtext_can_hide_tokens() -> None:
    from main import _cursor_subtext

    usage = PlanUsage(total_percent=1.0, auto_percent=1.0, api_percent=0.0)
    tokens = TokenUsage(input_tokens=1000)
    text = _cursor_subtext(usage, None, show_email=False, token_usage=tokens, show_tokens=False)
    assert "tokens" not in text



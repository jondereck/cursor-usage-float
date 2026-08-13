"""Usage parsing and Cursor-dashboard-matching display."""

from __future__ import annotations

from cursor_usage import PlanUsage, budget_from_plan, parse_plan_usage
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

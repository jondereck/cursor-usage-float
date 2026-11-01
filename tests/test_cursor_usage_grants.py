"""Grant-based usage fallback for merged Cursor plans."""

from __future__ import annotations

import pytest

import cursor_usage
from cursor_usage import (
    UsageError,
    parse_usage_limit_grants,
)


def test_parse_usage_limit_grants_derives_percent_from_cents() -> None:
    usage = parse_usage_limit_grants(
        {
            "activeGrants": [
                {
                    "allowedModelIds": ["default"],
                    "totalCents": "10000",
                    "remainingCents": "9402",
                    "expiresAtMs": "1794486958000",
                }
            ],
            "usageLimitPolicyStatus": {"isInSlowPool": True},
        }
    )
    assert usage.source == "grants"
    assert usage.limit_cents == 10000
    assert usage.total_spend_cents == 598
    assert usage.auto_percent == pytest.approx(5.98)
    assert usage.api_percent == 0.0
    assert usage.billing_cycle_end == "1794486958000"
    assert usage.spend_label == "$5.98 of $100.00 used"


def test_parse_usage_limit_grants_splits_auto_and_api_pools() -> None:
    usage = parse_usage_limit_grants(
        {
            "activeGrants": [
                {
                    "allowedModelIds": ["default"],
                    "totalCents": 10000,
                    "remainingCents": 5000,
                },
                {
                    "allowedModelIds": ["gpt-5"],
                    "totalCents": 4000,
                    "remainingCents": 1000,
                },
            ]
        }
    )
    assert usage.auto_percent == pytest.approx(50.0)
    assert usage.api_percent == pytest.approx(75.0)
    assert usage.total_percent == pytest.approx(8000 / 14000 * 100.0)
    assert usage.billing_cycle_end is None


def test_parse_usage_limit_grants_ignores_unusable_grants() -> None:
    usage = parse_usage_limit_grants(
        {
            "activeGrants": [
                {"totalCents": 0, "remainingCents": 0},
                "not-a-grant",
                {"allowedModelIds": ["default"], "totalCents": 500, "remainingCents": 500},
            ]
        }
    )
    assert usage.auto_percent == 0.0
    assert usage.total_spend_cents == 0


def test_parse_usage_limit_grants_prefers_policy_grants() -> None:
    usage = parse_usage_limit_grants(
        {
            "activeGrants": [
                {"grantType": "promo", "totalCents": 5000, "remainingCents": 0},
                {
                    "grantType": "usage_limit_policy",
                    "totalCents": 10000,
                    "remainingCents": 9500,
                },
            ]
        }
    )
    assert usage.limit_cents == 10000
    assert usage.total_spend_cents == 500
    assert usage.auto_percent == pytest.approx(5.0)


def test_parse_usage_limit_grants_rejects_empty_payload() -> None:
    with pytest.raises(UsageError):
        parse_usage_limit_grants({})
    with pytest.raises(UsageError):
        parse_usage_limit_grants({"activeGrants": []})


def test_fetch_falls_back_to_grants_when_plan_usage_missing(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(url: str, token: str) -> dict:
        calls.append(url)
        if url == cursor_usage.USAGE_URL:
            return {"billingCycleEnd": "1796083200000"}
        return {
            "activeGrants": [
                {
                    "allowedModelIds": ["default"],
                    "totalCents": 10000,
                    "remainingCents": 9000,
                }
            ]
        }

    monkeypatch.setattr(cursor_usage, "_post_dashboard_json", fake_post)
    usage = cursor_usage.fetch_current_period_usage("token")
    assert calls == [cursor_usage.USAGE_URL, cursor_usage.GRANT_URL]
    assert usage.source == "grants"
    assert usage.auto_percent == pytest.approx(10.0)


def test_fetch_prefers_plan_usage_when_present(monkeypatch) -> None:
    def fake_post(url: str, token: str) -> dict:
        return {
            "planUsage": {
                "totalPercentUsed": 9.2,
                "autoPercentUsed": 10.6,
                "apiPercentUsed": 0.0,
            }
        }

    monkeypatch.setattr(cursor_usage, "_post_dashboard_json", fake_post)
    usage = cursor_usage.fetch_current_period_usage("token")
    assert usage.source == "plan"
    assert usage.auto_percent == 10.6


def test_fetch_reports_missing_usage_when_grants_fail(monkeypatch) -> None:
    def fake_post(url: str, token: str) -> dict:
        if url == cursor_usage.USAGE_URL:
            return {}
        raise UsageError("Cursor usage API returned HTTP 500.")

    monkeypatch.setattr(cursor_usage, "_post_dashboard_json", fake_post)
    with pytest.raises(UsageError, match="isn't reporting usage"):
        cursor_usage.fetch_current_period_usage("token")

"""Fetch current Cursor plan usage from Cursor-hosted HTTPS only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from cursor_auth import get_access_token

API_ORIGIN = "https://api2.cursor.sh"
USAGE_PATH = "/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
USAGE_URL = f"{API_ORIGIN}{USAGE_PATH}"
GRANT_PATH = "/aiserver.v1.DashboardService/GetUsageLimitStatusAndActiveGrants"
GRANT_URL = f"{API_ORIGIN}{GRANT_PATH}"
GROK_BOT_PATH = "/aiserver.v1.DashboardService/GetSandUsageStatus"
GROK_BOT_URL = f"{API_ORIGIN}{GROK_BOT_PATH}"
TOKEN_USAGE_PATH = "/aiserver.v1.DashboardService/GetAggregatedUsageEvents"
TOKEN_USAGE_URL = f"{API_ORIGIN}{TOKEN_USAGE_PATH}"

# api2.cursor.sh is intermittently slow (20s read timeouts produced spurious
# "Network error" rows); 40s is the shortest timeout that reliably completed.
HTTP_TIMEOUT_S = 40


class UsageError(Exception):
    """Raised when usage cannot be fetched or parsed."""


@dataclass(frozen=True)
class PlanUsage:
    total_percent: float
    auto_percent: float
    api_percent: float
    total_spend_cents: int | None = None
    limit_cents: int | None = None
    billing_cycle_end: str | None = None
    # "plan" = planUsage percentages; "grants" = cent grants from the newer
    # merged-plan endpoint (percentages derived from spend/limit).
    source: str = "plan"

    @property
    def summary_line(self) -> str:
        auto = _fmt_pct(self.auto_percent)
        api = _fmt_pct(self.api_percent)
        return f"{auto}% Auto and {api}% API used"

    @property
    def spend_label(self) -> str | None:
        """'$5.98 of $100.00 used' for spend-based plans, else None."""
        if self.total_spend_cents is None or not self.limit_cents:
            return None
        return f"{_fmt_usd(self.total_spend_cents)} of {_fmt_usd(self.limit_cents)} used"


@dataclass(frozen=True)
class TokenUsage:
    """Tokens Cursor billed this period (from GetAggregatedUsageEvents).

    Cursor's dashboard endpoint only counts token-based model calls; Composer
    requests are tracked as requests instead, so this can be far below the
    plan percentage.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_cents: float = 0.0
    start_date: str | None = None

    @property
    def total_tokens(self) -> int:
        """Input + output + cache reads (what was actually processed)."""
        return max(0, self.input_tokens) + max(0, self.output_tokens) + max(
            0, self.cache_read_tokens
        )

    @property
    def is_eligible(self) -> bool:
        return self.total_tokens > 0


@dataclass(frozen=True)
class GrokBotUsage:
    """Grok Bot weekly included-usage pool (separate from Cursor Models)."""

    usage_percent: float
    next_reset: str | None = None
    has_nonzero_included_limit: bool = False
    uses_pooled_enterprise_allowance: bool = False
    included_limit_zero: bool = False

    @property
    def is_eligible(self) -> bool:
        """True when the account has a personal weekly Grok Bot allowance to show."""
        if self.uses_pooled_enterprise_allowance:
            return False
        if self.included_limit_zero:
            return False
        return bool(self.has_nonzero_included_limit)


@dataclass(frozen=True)
class UsageBudget:
    """Normalized used/remaining for pacing (percent units or cents)."""

    used: float
    limit: float
    remaining: float
    unit: str  # "percent" | "cents"


def budget_from_plan(usage: PlanUsage) -> UsageBudget:
    """
    Normalize used/remaining for pacing.

    Prefer the higher of Cursor Models (auto) and Other Models (api) so pace
    matches the dashboard pools. Fall back to spend/limit cents only when
    percent data is missing.
    """
    used_pct = max(float(usage.auto_percent), float(usage.api_percent))
    if used_pct >= 0:
        used = float(max(0.0, min(100.0, used_pct)))
        return UsageBudget(
            used=used,
            limit=100.0,
            remaining=max(0.0, 100.0 - used),
            unit="percent",
        )

    if (
        usage.limit_cents is not None
        and usage.limit_cents > 0
        and usage.total_spend_cents is not None
    ):
        used = float(max(0, usage.total_spend_cents))
        limit = float(usage.limit_cents)
        return UsageBudget(
            used=used,
            limit=limit,
            remaining=max(0.0, limit - used),
            unit="cents",
        )

    return UsageBudget(used=0.0, limit=100.0, remaining=100.0, unit="percent")



def _fmt_pct(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _fmt_usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _clamp_pct(value: float) -> float:
    return max(0.0, min(100.0, value))


def _as_float(data: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                continue
    return default


def _as_optional_int(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return int(data[key])
            except (TypeError, ValueError):
                continue
    return None


def parse_plan_usage(payload: dict[str, Any]) -> PlanUsage:
    plan = payload.get("planUsage")
    if not isinstance(plan, dict):
        # Some responses nest under different shapes; fall back to top-level.
        plan = payload if any(
            k in payload
            for k in ("totalPercentUsed", "autoPercentUsed", "apiPercentUsed")
        ) else None

    if not isinstance(plan, dict):
        raise UsageError("Usage response missing planUsage data.")

    total = _as_float(plan, "totalPercentUsed", "totalPercent")
    auto = _as_float(plan, "autoPercentUsed", "autoPercent")
    api = _as_float(plan, "apiPercentUsed", "apiPercent")

    billing_end = payload.get("billingCycleEnd") or plan.get("billingCycleEnd")
    if billing_end is not None:
        billing_end = str(billing_end)

    return PlanUsage(
        total_percent=max(0.0, min(100.0, total)),
        auto_percent=max(0.0, min(100.0, auto)),
        api_percent=max(0.0, min(100.0, api)),
        total_spend_cents=_as_optional_int(plan, "totalSpend", "totalSpendCents"),
        limit_cents=_as_optional_int(plan, "limit", "limitCents"),
        billing_cycle_end=billing_end,
    )


def parse_usage_limit_grants(
    payload: dict[str, Any],
    *,
    billing_cycle_end: str | None = None,
) -> PlanUsage:
    """
    Build PlanUsage from GetUsageLimitStatusAndActiveGrants.

    Merged xAI-era plans stopped returning planUsage percentages; the client
    tracks included usage as cent grants instead. Percentages here are derived
    from (totalCents - remainingCents) / totalCents, and the reset time comes
    from the earliest grant expiry.
    """
    grants = payload.get("activeGrants")
    if not isinstance(grants, list):
        raise UsageError("Cursor isn't reporting usage for this account yet.")

    # Included-usage grants are typed "usage_limit_policy"; promos and credits
    # share the list, so prefer the policy grants when any are present.
    policy_grants = [
        grant
        for grant in grants
        if isinstance(grant, dict) and grant.get("grantType") == "usage_limit_policy"
    ]
    if policy_grants:
        grants = policy_grants

    total_cents = 0
    remaining_cents = 0
    auto_total = 0
    auto_remaining = 0
    expiries: list[int] = []

    for grant in grants:
        if not isinstance(grant, dict):
            continue
        total = _as_optional_int(grant, "totalCents")
        remaining = _as_optional_int(grant, "remainingCents")
        if not total or total <= 0 or remaining is None:
            continue
        remaining = max(0, min(total, remaining))
        total_cents += total
        remaining_cents += remaining
        expires_at = _as_optional_int(grant, "expiresAtMs")
        if expires_at:
            expiries.append(expires_at)
        models = grant.get("allowedModelIds")
        models = models if isinstance(models, list) else []
        if not models or "default" in models:
            auto_total += total
            auto_remaining += remaining

    if total_cents <= 0:
        raise UsageError("Cursor isn't reporting usage for this account yet.")

    used_cents = total_cents - remaining_cents
    total_percent = _clamp_pct(used_cents / total_cents * 100.0)
    if auto_total > 0:
        auto_percent = _clamp_pct((auto_total - auto_remaining) / auto_total * 100.0)
        api_total = total_cents - auto_total
        api_remaining = remaining_cents - auto_remaining
        api_percent = (
            _clamp_pct((api_total - api_remaining) / api_total * 100.0)
            if api_total > 0
            else 0.0
        )
    else:
        auto_percent = total_percent
        api_percent = 0.0

    reset_at = min(expiries) if expiries else None
    if reset_at is not None:
        billing_cycle_end = str(reset_at)

    return PlanUsage(
        total_percent=total_percent,
        auto_percent=auto_percent,
        api_percent=api_percent,
        total_spend_cents=used_cents,
        limit_cents=total_cents,
        billing_cycle_end=billing_cycle_end,
        source="grants",
    )


def _as_optional_bool(data: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key in data and data[key] is not None:
            value = data[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("true", "1", "yes"):
                    return True
                if lowered in ("false", "0", "no"):
                    return False
    return None


def parse_grok_bot_usage(payload: dict[str, Any]) -> GrokBotUsage:
    """Parse GetSandUsageStatus JSON into GrokBotUsage."""
    if not isinstance(payload, dict):
        raise UsageError("Unexpected Grok Bot usage API response shape.")

    # usagePercent is optional; absent means unreadable / not a zero reading.
    if "usagePercent" not in payload or payload.get("usagePercent") is None:
        raise UsageError("Grok Bot usage response missing usagePercent.")

    percent = _as_float(payload, "usagePercent")
    has_limit = _as_optional_bool(
        payload, "hasNonZeroIncludedLimit", "has_nonzero_included_limit"
    )
    pooled = _as_optional_bool(
        payload, "usesPooledEnterpriseAllowance", "uses_pooled_enterprise_allowance"
    )
    limit_zero = _as_optional_bool(
        payload, "includedLimitZero", "included_limit_zero"
    )

    next_reset = payload.get("nextResetTimestampUtc") or payload.get("nextReset")
    if next_reset is not None:
        next_reset = str(next_reset)

    return GrokBotUsage(
        usage_percent=max(0.0, min(100.0, percent)),
        next_reset=next_reset,
        has_nonzero_included_limit=bool(has_limit) if has_limit is not None else False,
        uses_pooled_enterprise_allowance=bool(pooled) if pooled is not None else False,
        included_limit_zero=bool(limit_zero) if limit_zero is not None else False,
    )


def _post_dashboard_json(
    url: str,
    access_token: str,
    *,
    timeout: int = HTTP_TIMEOUT_S,
) -> dict[str, Any]:
    """POST empty JSON body to a Cursor DashboardService Connect-RPC endpoint."""
    request = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "User-Agent": "cursor-usage-float/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise UsageError(
            f"Cursor usage API returned HTTP {exc.code}."
            + (f" {detail}" if detail else "")
        ) from exc
    except urllib.error.URLError as exc:
        raise UsageError(f"Network error talking to Cursor: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError("Cursor usage API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise UsageError("Unexpected usage API response shape.")

    return payload


def fetch_current_period_usage(token: str | None = None) -> PlanUsage:
    """
    POST GetCurrentPeriodUsage using the local Cursor bearer token.

    Falls back to GetUsageLimitStatusAndActiveGrants when the response has no
    planUsage block (merged xAI-era plans report cent grants instead).

    Token is used in-memory only and sent solely to api2.cursor.sh.
    """
    access_token = token if token is not None else get_access_token()
    payload = _post_dashboard_json(USAGE_URL, access_token)
    try:
        return parse_plan_usage(payload)
    except UsageError:
        pass

    billing_end = payload.get("billingCycleEnd")
    try:
        grants = _post_dashboard_json(GRANT_URL, access_token)
    except UsageError as exc:
        raise UsageError(
            "Cursor isn't reporting usage for this account yet."
        ) from exc

    return parse_usage_limit_grants(
        grants,
        billing_cycle_end=str(billing_end) if billing_end is not None else None,
    )


def fetch_grok_bot_usage(token: str | None = None) -> GrokBotUsage:
    """
    POST GetSandUsageStatus using the local Cursor bearer token.

    Token is used in-memory only and sent solely to api2.cursor.sh.
    """
    access_token = token if token is not None else get_access_token()
    return parse_grok_bot_usage(_post_dashboard_json(GROK_BOT_URL, access_token))


def _as_token_int(data: dict[str, Any], *keys: str) -> int:
    """Token counters arrive as quoted decimal strings ("191242")."""
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return max(0, int(float(data[key])))
            except (TypeError, ValueError):
                continue
    return 0


def parse_aggregated_token_usage(payload: dict[str, Any]) -> TokenUsage:
    """Parse GetAggregatedUsageEvents JSON into TokenUsage."""
    if not isinstance(payload, dict):
        raise UsageError("Unexpected token usage API response shape.")

    totals = payload
    if not any(
        key in payload
        for key in ("totalInputTokens", "totalOutputTokens", "totalCacheReadTokens")
    ):
        # Older/newer shapes may only include the per-model aggregation list.
        aggregations = payload.get("aggregations")
        if isinstance(aggregations, list) and aggregations:
            merged: dict[str, Any] = {
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheReadTokens": 0,
            }
            for entry in aggregations:
                if not isinstance(entry, dict):
                    continue
                for src, dst in (
                    ("inputTokens", "inputTokens"),
                    ("outputTokens", "outputTokens"),
                    ("cacheReadTokens", "cacheReadTokens"),
                ):
                    merged[dst] += _as_token_int(entry, src)
            totals = merged
        else:
            raise UsageError("Token usage response missing token totals.")

    start_date = payload.get("startDate")
    return TokenUsage(
        input_tokens=_as_token_int(totals, "totalInputTokens", "inputTokens"),
        output_tokens=_as_token_int(totals, "totalOutputTokens", "outputTokens"),
        cache_read_tokens=_as_token_int(
            totals, "totalCacheReadTokens", "cacheReadTokens"
        ),
        cost_cents=_as_float(totals, "totalCostCents", "costCents"),
        start_date=str(start_date) if start_date is not None else None,
    )


def fetch_token_usage(token: str | None = None) -> TokenUsage:
    """
    POST GetAggregatedUsageEvents using the local Cursor bearer token.

    Cursor defaults the range to the current month, so this is a month-to-date
    cumulative total. Token is used in-memory only and sent solely to
    api2.cursor.sh.
    """
    access_token = token if token is not None else get_access_token()
    payload = _post_dashboard_json(TOKEN_USAGE_URL, access_token, timeout=20)
    return parse_aggregated_token_usage(payload)

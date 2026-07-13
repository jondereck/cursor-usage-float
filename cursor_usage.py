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

    @property
    def summary_line(self) -> str:
        auto = _fmt_pct(self.auto_percent)
        api = _fmt_pct(self.api_percent)
        return f"{auto}% Auto and {api}% API used"


def _fmt_pct(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}".rstrip("0").rstrip(".")


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


def fetch_current_period_usage(token: str | None = None) -> PlanUsage:
    """
    POST GetCurrentPeriodUsage using the local Cursor bearer token.

    Token is used in-memory only and sent solely to api2.cursor.sh.
    """
    access_token = token if token is not None else get_access_token()

    body = b"{}"
    request = urllib.request.Request(
        USAGE_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "User-Agent": "cursor-usage-float/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
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

    return parse_plan_usage(payload)

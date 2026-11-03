"""Grok.com / grok CLI weekly usage (separate from Cursor Grok Bot)."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
SETTINGS_URL = "https://cli-chat-proxy.grok.com/v1/settings"


class GrokAppError(Exception):
    """Raised when Grok Premium usage cannot be read."""


def grok_access_token_expired(token: str, *, skew_seconds: int = 60) -> bool:
    """True when JWT exp is in the past (Grok CLI access tokens are short-lived)."""
    import base64
    import json
    import time

    parts = (token or "").split(".")
    if len(parts) < 2:
        return False
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (json.JSONDecodeError, ValueError):
        return False
    exp = data.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= time.time() + skew_seconds


def format_grok_app_error(message: str) -> str:
    """User-facing Grok row error (no raw HTTP codes when we can help)."""
    text = (message or "").strip()
    lower = text.lower()
    if "401" in text or "expired" in lower or "invalid or expired" in lower:
        return "Grok login expired. Run grok login, then refresh."
    if "no access token" in lower:
        return "Wrong Grok auth file in Settings — clear path to use ~/.grok/auth.json."
    if "not found" in lower and "grok login" in lower:
        return text
    return text[:120]


def grok_error_needs_login_action(message: str | None) -> bool:
    if not message:
        return False
    lower = message.lower()
    return any(
        needle in lower
        for needle in (
            "expired",
            "401",
            "grok login",
            "no access token",
            "not found",
            "invalid or expired",
        )
    )


@dataclass(frozen=True)
class GrokAppUsage:
    usage_percent: float
    email: str | None = None
    plan_tier: str | None = None
    plan_tier_id: str | None = None
    period_end: str | None = None
    is_eligible: bool = True


def format_grok_plan_label(
    tier_display: str | None,
    tier_id: str | None = None,
) -> str | None:
    """Map grok CLI settings tiers to short labels (Premium, Super, Plus, …)."""
    if isinstance(tier_id, str) and tier_id.strip():
        lower = tier_id.strip().lower().replace("_", " ")
        if "premium" in lower and "super" not in lower:
            return "Premium"
        if "super" in lower:
            return "Super"
        if lower in ("plus", "grok plus"):
            return "Plus"
        if lower == "free":
            return "Free"
        return tier_id.strip()
    if isinstance(tier_display, str) and tier_display.strip():
        text = tier_display.strip()
        # grok CLI reports "SuperGrok" for paid grok.com plans; web pricing uses Premium ($30).
        if text == "SuperGrok":
            return "Premium"
        return text
    return None


def default_grok_auth_path() -> Path:
    return Path.home() / ".grok" / "auth.json"


def read_grok_access_token(path: str | Path | None = None) -> str:
    """Read a bearer token from grok CLI auth.json or a one-line token file."""
    file_path = Path(path).expanduser() if path else default_grok_auth_path()
    if not file_path.is_file():
        raise GrokAppError(
            "Grok login not found. Run grok login (creates ~/.grok/auth.json) "
            "or set a token file in Settings."
        )
    raw = file_path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        raise GrokAppError("Grok token file is empty.")
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GrokAppError("Grok auth file is not valid JSON.") from exc
        token = _token_from_json(data)
        if not token:
            raise GrokAppError("Grok auth file has no access token.")
        return token
    return raw.splitlines()[0].strip()


def _auth_record_from_json(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    oidc_scope = "https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828"
    legacy_scope = "https://accounts.x.ai/sign-in"
    for scope in (oidc_scope, legacy_scope):
        entry = data.get(scope)
        if isinstance(entry, dict) and entry.get("key"):
            return entry
    for value in data.values():
        if isinstance(value, dict) and value.get("key"):
            return value
    return None


def _metadata_from_auth_path(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw.startswith("{"):
        return None, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    entry = _auth_record_from_json(data)
    if not entry:
        return None, None
    email = entry.get("email")
    email_text = email.strip() if isinstance(email, str) and "@" in email else None
    return email_text, None


def _token_from_json(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("access_token", "accessToken", "token"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    tokens = data.get("tokens")
    if isinstance(tokens, dict):
        nested = tokens.get("access_token") or tokens.get("accessToken")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    # grok CLI auth.json: { "https://auth.x.ai::…": { "key": "…" }, … }
    oidc_scope = "https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828"
    legacy_scope = "https://accounts.x.ai/sign-in"
    for scope in (oidc_scope, legacy_scope):
        entry = data.get(scope)
        if isinstance(entry, dict):
            key = entry.get("key")
            if isinstance(key, str) and key.strip():
                return key.strip()
    for value in data.values():
        if isinstance(value, dict):
            key = value.get("key")
            if isinstance(key, str) and key.strip():
                return key.strip()
    return None


def parse_grok_billing(payload: dict[str, Any]) -> GrokAppUsage:
    config = payload.get("config")
    if not isinstance(config, dict):
        raise GrokAppError("Grok billing response has no config.")
    percent = config.get("creditUsagePercent")
    if not isinstance(percent, (int, float)):
        raise GrokAppError("Grok billing response has no creditUsagePercent.")
    period = config.get("currentPeriod")
    end = None
    if isinstance(period, dict) and isinstance(period.get("end"), str):
        end = period["end"]
    return GrokAppUsage(
        usage_percent=max(0.0, min(100.0, float(percent))),
        period_end=end,
        is_eligible=True,
    )


def _fetch_grok_settings_tiers(access: str) -> tuple[str | None, str | None]:
    request = urllib.request.Request(
        SETTINGS_URL,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
            "x-xai-token-auth": "xai-grok-cli",
            "User-Agent": "cursor-usage-float",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=15, context=ssl.create_default_context()
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    display = payload.get("subscription_tier_display")
    tier_id = payload.get("subscription_tier")
    disp_text = display.strip() if isinstance(display, str) and display.strip() else None
    id_text = tier_id.strip() if isinstance(tier_id, str) and tier_id.strip() else None
    return disp_text, id_text


def fetch_grok_app_usage(token: str | None = None, auth_path: str | None = None) -> GrokAppUsage:
    path = resolve_grok_auth_path(auth_path or "")
    access = token if token is not None else read_grok_access_token(path)
    if grok_access_token_expired(access):
        raise GrokAppError(format_grok_app_error("Grok login expired"))
    request = urllib.request.Request(
        BILLING_URL,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
            "x-xai-token-auth": "xai-grok-cli",
            "User-Agent": "cursor-usage-float",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise GrokAppError(format_grok_app_error("Grok billing HTTP 401")) from exc
        raise GrokAppError(f"Grok billing HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GrokAppError(f"Grok billing unreachable: {exc.reason}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GrokAppError("Grok billing returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise GrokAppError("Unexpected Grok billing response.")
    usage = parse_grok_billing(payload)
    email, _ = _metadata_from_auth_path(path)
    if not email:
        from cursor_auth import jwt_email_claim

        email = jwt_email_claim(access)
    tier_display, tier_id = _fetch_grok_settings_tiers(access)
    return GrokAppUsage(
        usage_percent=usage.usage_percent,
        email=email,
        plan_tier=tier_display,
        plan_tier_id=tier_id,
        period_end=usage.period_end,
        is_eligible=True,
    )


def resolve_grok_auth_path(token_file: str) -> Path:
    """Prefer a working auth file; fall back to ~/.grok/auth.json when custom path fails."""
    custom = (token_file or "").strip()
    default = default_grok_auth_path()

    def _readable(path: Path) -> bool:
        try:
            read_grok_access_token(path)
            return True
        except GrokAppError:
            return False

    if custom:
        candidate = Path(custom).expanduser()
        if _readable(candidate):
            raw = candidate.read_text(encoding="utf-8-sig").strip()
            # Plain one-line files are often Cursor token exports, not grok login.
            if (
                not raw.startswith("{")
                and default.is_file()
                and default.resolve() != candidate.resolve()
                and _readable(default)
            ):
                return default
            return candidate

    if default.is_file() and _readable(default):
        return default

    if custom:
        return Path(custom).expanduser()
    return default


def grok_auth_path_from_settings(token_file: str) -> Path:
    return resolve_grok_auth_path(token_file)

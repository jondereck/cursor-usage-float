"""Fetch Codex / ChatGPT plan usage from ChatGPT backend API."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


class CodexError(Exception):
    """Raised when Codex usage cannot be fetched or parsed."""


@dataclass(frozen=True)
class CodexWindow:
    used_percent: float
    limit_window_seconds: int | None = None
    reset_after_seconds: int | None = None
    reset_at: int | None = None


@dataclass(frozen=True)
class CodexUsage:
    """Codex / ChatGPT rate limit & usage allowance."""

    usage_percent: float
    primary_window: CodexWindow | None = None
    secondary_window: CodexWindow | None = None
    plan_type: str | None = None
    limit_reached: bool = False
    next_reset: str | None = None  # ISO format string or None
    is_eligible: bool = True


def default_codex_auth_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "auth.json"
    return Path.home() / ".codex" / "auth.json"


def get_codex_tokens(auth_path: Path | None = None) -> tuple[str, str | None]:
    """Read access_token and optional account_id from ~/.codex/auth.json."""
    path = auth_path or default_codex_auth_path()
    if not path.is_file():
        raise CodexError(f"Codex auth file not found at {path}. Sign in to Codex first.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CodexError(f"Could not read Codex auth file: {exc}") from exc

    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexError("No tokens found in Codex auth file.")

    token = tokens.get("access_token")
    if not token or not isinstance(token, str):
        raise CodexError("No valid access_token found in Codex auth file.")

    account_id = tokens.get("account_id")
    if account_id and not isinstance(account_id, str):
        account_id = None

    return token.strip(), (account_id.strip() if account_id else None)


def parse_codex_usage(payload: dict[str, Any]) -> CodexUsage:
    """Parse /backend-api/wham/usage response into CodexUsage."""
    plan_type = str(payload.get("plan_type") or "").strip() or None
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise CodexError("Codex usage response missing rate_limit field.")

    limit_reached = bool(rate_limit.get("limit_reached", False))

    def _parse_window(win_data: Any) -> CodexWindow | None:
        if not isinstance(win_data, dict):
            return None
        raw_pct = win_data.get("used_percent", 0.0)
        try:
            pct = float(raw_pct)
        except (ValueError, TypeError):
            pct = 0.0
        pct = max(0.0, min(100.0, round(pct, 1)))

        raw_reset_at = win_data.get("reset_at")
        reset_at = int(raw_reset_at) if raw_reset_at is not None else None

        raw_window_sec = win_data.get("limit_window_seconds")
        window_sec = int(raw_window_sec) if raw_window_sec is not None else None

        raw_after_sec = win_data.get("reset_after_seconds")
        after_sec = int(raw_after_sec) if raw_after_sec is not None else None

        return CodexWindow(
            used_percent=pct,
            limit_window_seconds=window_sec,
            reset_after_seconds=after_sec,
            reset_at=reset_at,
        )

    primary = _parse_window(rate_limit.get("primary_window"))
    secondary = _parse_window(rate_limit.get("secondary_window"))

    if primary is None and secondary is None:
        raise CodexError("No active rate limit windows in Codex usage response.")

    # Determine primary percent and next reset
    primary_pct = primary.used_percent if primary else (secondary.used_percent if secondary else 0.0)
    reset_ts: int | None = None
    if primary and primary.reset_at:
        reset_ts = primary.reset_at
    elif secondary and secondary.reset_at:
        reset_ts = secondary.reset_at

    next_reset_str: str | None = None
    if reset_ts:
        try:
            next_reset_str = datetime.fromtimestamp(reset_ts, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            next_reset_str = None

    return CodexUsage(
        usage_percent=primary_pct,
        primary_window=primary,
        secondary_window=secondary,
        plan_type=plan_type,
        limit_reached=limit_reached,
        next_reset=next_reset_str,
        is_eligible=True,
    )


def fetch_codex_usage(auth_path: Path | None = None) -> CodexUsage:
    """Fetch live Codex usage from ChatGPT backend API."""
    token, account_id = get_codex_tokens(auth_path)

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "codex/0.164.0",
        "Accept": "application/json",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    req = urllib.request.Request(CODEX_USAGE_URL, headers=headers)
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return parse_codex_usage(data)
    except urllib.error.HTTPError as exc:
        raise CodexError(f"Codex API HTTP error {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise CodexError(f"Could not connect to Codex API: {exc.reason}") from exc
    except Exception as exc:
        raise CodexError(f"Unexpected error fetching Codex usage: {exc}") from exc

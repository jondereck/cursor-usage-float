"""Read OpenCode local usage (tokens / cost) from its SQLite store.

OpenCode has no plan-quota API like Cursor or Codex, so usage is measured
against a daily token budget instead. Everything is read locally — no network.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DAILY_TOKEN_BUDGET = 50_000_000


class OpenCodeError(Exception):
    """Raised when OpenCode usage cannot be read."""


@dataclass(frozen=True)
class OpenCodeUsage:
    """OpenCode usage for the current day, as % of a token budget."""

    usage_percent: float
    tokens_used: int
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_reasoning: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    cost_usd: float = 0.0
    sessions: int = 0
    prompts: int = 0
    steps: int = 0
    budget_tokens: int = DEFAULT_DAILY_TOKEN_BUDGET
    day: str = ""
    source: str = "db"
    is_eligible: bool = True


def default_opencode_data_dir() -> Path:
    explicit = os.environ.get("OPENCODE_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "opencode"
    return Path.home() / ".local" / "share" / "opencode"


def default_opencode_db_path() -> Path:
    return default_opencode_data_dir() / "opencode.db"


def format_token_count(tokens: int) -> str:
    """Compact token label: 948, 15k, 15.6M, 1.2B."""
    value = max(0, int(tokens))
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def apply_budget(usage: OpenCodeUsage, budget_tokens: int) -> OpenCodeUsage:
    """Re-score cached usage after the token budget changes in Settings."""
    budget = _positive_budget(budget_tokens)
    return replace(
        usage,
        budget_tokens=budget,
        usage_percent=_percent(usage.tokens_used, budget),
    )


def _positive_budget(budget_tokens: int) -> int:
    try:
        budget = int(budget_tokens)
    except (TypeError, ValueError):
        return DEFAULT_DAILY_TOKEN_BUDGET
    return budget if budget > 0 else DEFAULT_DAILY_TOKEN_BUDGET


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _message_tokens(payload: dict[str, Any]) -> dict[str, int] | None:
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    return {
        "input": _int(tokens.get("input")),
        "output": _int(tokens.get("output")),
        "reasoning": _int(tokens.get("reasoning")),
        "cache_read": _int(cache.get("read")),
        "cache_write": _int(cache.get("write")),
    }


def _day_start_ms(now: datetime | None = None) -> int:
    current = now or datetime.now()
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def _percent(used: int, budget: int) -> float:
    if budget <= 0:
        return 0.0
    return max(0.0, min(100.0, round(used / budget * 100.0, 1)))


def _build_usage(
    *,
    tokens: dict[str, int],
    cost: float,
    sessions: int,
    prompts: int,
    steps: int,
    budget_tokens: int,
    day: str,
    source: str,
) -> OpenCodeUsage:
    used = (
        tokens["input"]
        + tokens["output"]
        + tokens["reasoning"]
        + tokens["cache_read"]
        + tokens["cache_write"]
    )
    return OpenCodeUsage(
        usage_percent=_percent(used, budget_tokens),
        tokens_used=used,
        tokens_input=tokens["input"],
        tokens_output=tokens["output"],
        tokens_reasoning=tokens["reasoning"],
        tokens_cache_read=tokens["cache_read"],
        tokens_cache_write=tokens["cache_write"],
        cost_usd=round(cost, 4),
        sessions=sessions,
        prompts=prompts,
        steps=steps,
        budget_tokens=budget_tokens,
        day=day,
        source=source,
        is_eligible=True,
    )


def _empty_tokens() -> dict[str, int]:
    return {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
    }


def _read_from_db(db_path: Path, day_start_ms: int, budget_tokens: int, day: str) -> OpenCodeUsage:
    if not db_path.is_file():
        raise OpenCodeError(f"OpenCode database not found at {db_path}")

    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        raise OpenCodeError(f"Could not open OpenCode database: {exc}") from exc

    try:
        try:
            rows = conn.execute(
                "select session_id, type, data from session_message "
                "where time_created >= ?",
                (day_start_ms,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise OpenCodeError(
                f"OpenCode database schema not recognised: {exc}"
            ) from exc
    finally:
        conn.close()

    tokens = _empty_tokens()
    cost = 0.0
    session_ids: set[str] = set()
    prompts = 0
    steps = 0

    for session_id, msg_type, raw in rows:
        if msg_type not in ("assistant", "user"):
            continue
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if session_id:
            session_ids.add(str(session_id))
        if msg_type == "user":
            prompts += 1
            continue

        message_tokens = _message_tokens(payload)
        if message_tokens is None:
            continue
        steps += 1
        for key, value in message_tokens.items():
            tokens[key] += value
        cost += _float(payload.get("cost"))

    return _build_usage(
        tokens=tokens,
        cost=cost,
        sessions=len(session_ids),
        prompts=prompts,
        steps=steps,
        budget_tokens=budget_tokens,
        day=day,
        source="db",
    )


def _find_opencode_cli() -> Path | None:
    for name in ("opencode", "opencode-cli"):
        found = shutil.which(name)
        if found:
            return Path(found)
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    candidate = Path(local) / "Programs" / "ai.opencode.desktop" / "resources" / "opencode-cli.exe"
    return candidate if candidate.is_file() else None


def _payload_from_stdout(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise OpenCodeError("OpenCode CLI returned no JSON payload.")
    try:
        payload = json.loads(text[start:])
    except (TypeError, ValueError) as exc:
        raise OpenCodeError(f"Could not parse OpenCode CLI stats: {exc}") from exc
    if not isinstance(payload, dict):
        raise OpenCodeError("OpenCode CLI returned an unexpected payload.")
    return payload


def _read_from_cli(cli: Path, budget_tokens: int, day: str) -> OpenCodeUsage:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [str(cli), "stats", "--days", "0", "--cost", "--json"],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OpenCodeError(f"Could not run OpenCode CLI: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        reason = detail[-1] if detail else f"exit {proc.returncode}"
        raise OpenCodeError(f"OpenCode CLI stats failed: {reason}")

    payload = _payload_from_stdout(proc.stdout or "")
    raw_tokens = payload.get("tokens")
    raw_tokens = raw_tokens if isinstance(raw_tokens, dict) else {}
    cache = raw_tokens.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    tokens = {
        "input": _int(raw_tokens.get("input")),
        "output": _int(raw_tokens.get("output")),
        "reasoning": _int(raw_tokens.get("reasoning")),
        "cache_read": _int(cache.get("read")),
        "cache_write": _int(cache.get("write")),
    }

    return _build_usage(
        tokens=tokens,
        cost=_float(payload.get("cost")),
        sessions=_int(payload.get("sessions")),
        prompts=_int(payload.get("prompts")),
        steps=_int(payload.get("steps")),
        budget_tokens=budget_tokens,
        day=day,
        source="cli",
    )


def fetch_opencode_usage(
    budget_tokens: int = DEFAULT_DAILY_TOKEN_BUDGET,
    db_path: Path | None = None,
    now: datetime | None = None,
) -> OpenCodeUsage:
    """Read today's OpenCode usage, falling back to the bundled CLI."""
    budget = int(budget_tokens) if budget_tokens else DEFAULT_DAILY_TOKEN_BUDGET
    current = now or datetime.now()
    day = current.strftime("%Y-%m-%d")
    start_ms = _day_start_ms(current)

    db_error: OpenCodeError | None = None
    try:
        return _read_from_db(db_path or default_opencode_db_path(), start_ms, budget, day)
    except OpenCodeError as exc:
        db_error = exc

    cli = _find_opencode_cli()
    if cli is None:
        raise db_error
    return _read_from_cli(cli, budget, day)

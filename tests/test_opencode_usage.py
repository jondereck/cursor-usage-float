from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from opencode_usage import (
    OpenCodeError,
    apply_budget,
    fetch_opencode_usage,
    format_token_count,
)


def _make_db(path: Path, rows: list[tuple[str, str, int, dict]]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "create table session_message ("
        "id text primary key, session_id text, type text, seq integer, "
        "time_created integer, time_updated integer, data text)"
    )
    for index, (session_id, msg_type, created, payload) in enumerate(rows):
        conn.execute(
            "insert into session_message values (?, ?, ?, ?, ?, ?, ?)",
            (f"msg_{index}", session_id, msg_type, index, created, created, json.dumps(payload)),
        )
    conn.commit()
    conn.close()


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def test_fetch_opencode_usage_today_only(tmp_path: Path):
    now = datetime(2026, 10, 28, 15, 0, 0)
    today = _ms(now.replace(hour=9))
    yesterday = _ms(now - timedelta(days=1))

    db = tmp_path / "opencode.db"
    _make_db(
        db,
        [
            ("ses_a", "user", today, {"text": "hi"}),
            (
                "ses_a",
                "assistant",
                today,
                {
                    "tokens": {
                        "input": 1_000_000,
                        "output": 500_000,
                        "reasoning": 0,
                        "cache": {"read": 500_000, "write": 0},
                    },
                    "cost": 0.25,
                },
            ),
            (
                "ses_b",
                "assistant",
                today,
                {
                    "tokens": {
                        "input": 1_000_000,
                        "output": 0,
                        "reasoning": 0,
                        "cache": {"read": 0, "write": 0},
                    },
                    "cost": 0.0,
                },
            ),
            (
                "ses_c",
                "assistant",
                yesterday,
                {
                    "tokens": {"input": 9_000_000, "output": 0, "cache": {}},
                    "cost": 9.0,
                },
            ),
        ],
    )

    usage = fetch_opencode_usage(4_000_000, db_path=db, now=now)

    assert usage.source == "db"
    assert usage.tokens_input == 2_000_000
    assert usage.tokens_output == 500_000
    assert usage.tokens_cache_read == 500_000
    assert usage.tokens_used == 3_000_000
    assert usage.usage_percent == 75.0
    assert usage.sessions == 2
    assert usage.prompts == 1
    assert usage.steps == 2
    assert usage.cost_usd == 0.25
    assert usage.day == "2026-10-28"
    assert usage.is_eligible is True


def test_fetch_opencode_usage_missing_db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("opencode_usage._find_opencode_cli", lambda: None)
    with pytest.raises(OpenCodeError):
        fetch_opencode_usage(db_path=tmp_path / "nope.db")


def test_fetch_opencode_usage_percent_is_clamped(tmp_path: Path):
    now = datetime(2026, 10, 28, 8, 0, 0)
    db = tmp_path / "opencode.db"
    _make_db(
        db,
        [
            (
                "ses_a",
                "assistant",
                _ms(now),
                {"tokens": {"input": 50_000_000, "output": 0, "cache": {}}},
            )
        ],
    )

    usage = fetch_opencode_usage(10_000_000, db_path=db, now=now)

    assert usage.usage_percent == 100.0


def test_apply_budget_rescores_cached_usage(tmp_path: Path):
    now = datetime(2026, 10, 28, 8, 0, 0)
    db = tmp_path / "opencode.db"
    _make_db(
        db,
        [
            (
                "ses_a",
                "assistant",
                _ms(now),
                {"tokens": {"input": 5_000_000, "output": 0, "cache": {}}},
            )
        ],
    )
    usage = fetch_opencode_usage(20_000_000, db_path=db, now=now)
    assert usage.usage_percent == 25.0

    rescored = apply_budget(usage, 10_000_000)

    assert rescored.usage_percent == 50.0
    assert rescored.budget_tokens == 10_000_000
    assert rescored.tokens_used == usage.tokens_used


def test_format_token_count():
    assert format_token_count(948) == "948"
    assert format_token_count(15_000) == "15k"
    assert format_token_count(15_600_000) == "15.6M"
    assert format_token_count(1_200_000_000) == "1.2B"

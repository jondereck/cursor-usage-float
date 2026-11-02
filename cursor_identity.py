"""Cursor account email and subscription tier from local state (read-only)."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cursor_auth import AuthError, default_state_db_path, get_access_token, jwt_email_claim


@dataclass(frozen=True)
class CursorAccountInfo:
    email: str | None = None
    membership_type: str | None = None
    subscription_status: str | None = None

    @property
    def plan_label(self) -> str | None:
        tier = (self.membership_type or "").strip()
        status = (self.subscription_status or "").strip()
        if not tier and not status:
            return None
        tier_text = tier.replace("_", " ").title() if tier else "Unknown"
        if status and status.lower() not in ("active", "trialing"):
            return f"{tier_text} · {status}"
        if status and status.lower() == "trialing":
            return f"{tier_text} · trial"
        return tier_text


def _read_state_value(db_path: Path, key: str) -> str | None:
    if not db_path.is_file():
        return None
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?",
            (key,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row or row[0] is None:
        return None
    text = str(row[0]).strip()
    return text or None


def get_cursor_account_info(db_path: Path | None = None) -> CursorAccountInfo:
    path = db_path or default_state_db_path()
    return CursorAccountInfo(
        email=_read_state_value(path, "cursorAuth/cachedEmail"),
        membership_type=_read_state_value(path, "cursorAuth/stripeMembershipType"),
        subscription_status=_read_state_value(path, "cursorAuth/stripeSubscriptionStatus"),
    )


def live_cursor_email(db_path: Path | None = None) -> str | None:
    info = get_cursor_account_info(db_path)
    if info.email:
        return info.email
    try:
        return jwt_email_claim(get_access_token(db_path))
    except AuthError:
        return None

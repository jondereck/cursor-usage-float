"""Read Cursor access token from local SQLite (never persisted by this app)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class AuthError(Exception):
    """Raised when the Cursor token cannot be read."""


def default_state_db_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AuthError("APPDATA is not set; cannot locate Cursor state database.")
    return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def get_access_token(db_path: Path | None = None) -> str:
    """
    Read cursorAuth/accessToken from Cursor's local state DB.

    Opens the DB read-only and does not copy or store the token.
    """
    path = db_path or default_state_db_path()
    if not path.is_file():
        raise AuthError(
            "Cursor state database not found. Sign in to Cursor and try again."
        )

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise AuthError(f"Could not open Cursor state database: {exc}") from exc

    try:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?",
            ("cursorAuth/accessToken",),
        ).fetchone()
    except sqlite3.Error as exc:
        raise AuthError(f"Could not read Cursor auth token: {exc}") from exc
    finally:
        conn.close()

    if not row or not row[0]:
        raise AuthError("No Cursor access token found. Sign in to Cursor first.")

    token = str(row[0]).strip()
    if not token:
        raise AuthError("Cursor access token is empty. Sign in to Cursor again.")
    return token

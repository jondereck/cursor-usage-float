"""Detect when a local login file or Cursor token identity changes."""

from __future__ import annotations

from pathlib import Path

from cursor_auth import AuthError, get_access_token, token_fingerprint


def live_cursor_fingerprint(db_path: Path | None = None) -> str | None:
    try:
        token = get_access_token(db_path)
    except AuthError:
        return None
    return token_fingerprint(token)


def file_stamp(path: str | Path | None) -> str | None:
    if path is None:
        return None
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        return None
    stat = file_path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"

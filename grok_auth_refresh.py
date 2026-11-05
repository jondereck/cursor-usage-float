"""Silent OAuth refresh for the grok CLI auth file.

``~/.grok/auth.json`` stores a short-lived access token (``key``) plus a
long-lived ``refresh_token``. The grok CLI refreshes it in place, but the
floater used to only *read* the file — so every access-token expiry looked like
a logout ("run grok login").

This module posts the stored ``refresh_token`` to ``https://auth.x.ai/oauth2/token``
and writes the rotated tokens back atomically. It is deliberately careful:

* it only runs when the access token is (nearly) expired or the API said 401;
* it re-reads the file before saving and skips the write when the grok CLI
  already refreshed it (compare-and-swap on ``key``);
* it never raises — callers get a :class:`GrokRefreshResult`.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from grok_app_usage import default_grok_auth_path, grok_access_token_expired

TOKEN_URL = "https://auth.x.ai/oauth2/token"
DEFAULT_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
DEFAULT_ISSUER = "https://auth.x.ai"

# Refresh before the JWT actually dies so a poll never races expiry.
REFRESH_SKEW_S = 120
REQUEST_TIMEOUT_S = 20

_PREFERRED_SCOPES = (
    f"{DEFAULT_ISSUER}::{DEFAULT_CLIENT_ID}",
    "https://accounts.x.ai/sign-in",
)

_REFRESH_LOCK = threading.Lock()


@dataclass(frozen=True)
class GrokRefreshResult:
    """Outcome of one refresh attempt."""

    refreshed: bool
    needs_login: bool = False
    error: str | None = None


class _Unauthorized(Exception):
    """Token endpoint rejected the request as an auth problem."""


def grok_auth_needs_refresh(token: str) -> bool:
    return grok_access_token_expired(token, skew_seconds=REFRESH_SKEW_S)


def grok_auth_has_refresh_token(path: str | Path | None = None) -> bool:
    data = _read_auth(_auth_path(path))
    return _find_scope(data) is not None if data is not None else False


def refresh_grok_auth(path: str | Path | None = None) -> GrokRefreshResult:
    """Refresh the stored grok token. Never raises."""
    auth_path = _auth_path(path)
    with _REFRESH_LOCK:
        try:
            return _refresh_locked(auth_path)
        except Exception as exc:  # noqa: BLE001 - never break the caller's poll
            return GrokRefreshResult(False, error=f"Grok token refresh failed: {exc}")


def _auth_path(path: str | Path | None) -> Path:
    return Path(path).expanduser() if path else default_grok_auth_path()


def _read_auth(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _find_scope(data: dict[str, Any] | None) -> str | None:
    if not isinstance(data, dict):
        return None
    for scope in _PREFERRED_SCOPES:
        entry = data.get(scope)
        if isinstance(entry, dict) and _text(entry.get("refresh_token")):
            return scope
    for scope, entry in data.items():
        if isinstance(entry, dict) and _text(entry.get("refresh_token")):
            return scope
    return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _refresh_locked(auth_path: Path) -> GrokRefreshResult:
    data = _read_auth(auth_path)
    if data is None:
        return GrokRefreshResult(
            False,
            needs_login=True,
            error="Grok login not found. Run grok login.",
        )
    scope = _find_scope(data)
    if scope is None:
        return GrokRefreshResult(
            False,
            needs_login=True,
            error="Grok login has no refresh token. Run grok login.",
        )
    entry = data.get(scope)
    if not isinstance(entry, dict):
        return GrokRefreshResult(
            False,
            needs_login=True,
            error="Grok login is unreadable. Run grok login.",
        )
    refresh_token = _text(entry.get("refresh_token"))
    client_id = _text(entry.get("oidc_client_id")) or DEFAULT_CLIENT_ID
    old_key = _text(entry.get("key")) or ""
    if refresh_token is None:
        return GrokRefreshResult(
            False,
            needs_login=True,
            error="Grok login has no refresh token. Run grok login.",
        )

    try:
        payload = _request_new_tokens(client_id, refresh_token)
    except _Unauthorized:
        # The grok CLI may have rotated the token while we were asking.
        if _refreshed_elsewhere(auth_path, old_key):
            return GrokRefreshResult(True)
        return GrokRefreshResult(
            False,
            needs_login=True,
            error="Grok login expired. Run grok login, then refresh.",
        )
    except urllib.error.HTTPError as exc:
        return GrokRefreshResult(False, error=f"Grok token endpoint HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return GrokRefreshResult(
            False,
            error=f"Grok token endpoint unreachable: {exc.reason}",
        )
    except (TimeoutError, OSError) as exc:
        return GrokRefreshResult(False, error=f"Grok token endpoint unreachable: {exc}")
    except (json.JSONDecodeError, ValueError):
        return GrokRefreshResult(False, error="Grok token endpoint returned invalid JSON")

    access = _text(payload.get("access_token"))
    if access is None:
        return GrokRefreshResult(False, error="Grok token response had no access_token")

    rotated = _text(payload.get("refresh_token")) or refresh_token
    expires_at = _expires_at(payload.get("expires_in"))

    # Someone (the CLI) may have refreshed while our request was in flight.
    current = _read_auth(auth_path)
    if current is not None:
        if _refreshed_elsewhere(auth_path, old_key, data=current):
            return GrokRefreshResult(True)
        scope_now = _find_scope(current) or scope
        entry_now = current.get(scope_now)
        if isinstance(entry_now, dict):
            data = current
            scope = scope_now
            entry = entry_now

    entry["key"] = access
    entry["refresh_token"] = rotated
    if expires_at:
        entry["expires_at"] = expires_at
    data[scope] = entry

    try:
        _write_auth(auth_path, data)
    except OSError as exc:
        return GrokRefreshResult(False, error=f"Could not save refreshed Grok token: {exc}")
    return GrokRefreshResult(True)


def _refreshed_elsewhere(
    auth_path: Path,
    old_key: str,
    *,
    data: dict[str, Any] | None = None,
) -> bool:
    """True when the on-disk token changed to a different, still-valid one."""
    data = data if data is not None else _read_auth(auth_path)
    if data is None:
        return False
    scope = _find_scope(data)
    if scope is None:
        return False
    entry = data.get(scope)
    key = _text(entry.get("key")) if isinstance(entry, dict) else None
    if key is None or key == old_key:
        return False
    return not grok_access_token_expired(key, skew_seconds=0)


def _request_new_tokens(client_id: str, refresh_token: str) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "cursor-usage-float",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_S,
            context=ssl.create_default_context(),
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if _is_auth_rejection(exc):
            raise _Unauthorized() from exc
        raise
    if not isinstance(payload, dict):
        raise ValueError("token response was not an object")
    return payload


def _is_auth_rejection(exc: urllib.error.HTTPError) -> bool:
    if exc.code == 401:
        return True
    if exc.code != 400:
        return False
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
    except (json.JSONDecodeError, ValueError, OSError):
        return False
    if not isinstance(payload, dict):
        return False
    return str(payload.get("error") or "").strip().lower() == "invalid_grant"


def _expires_at(expires_in: Any) -> str | None:
    try:
        seconds = float(expires_in)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    when = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    # Match the grok CLI format: RFC3339 with microseconds and a Z suffix.
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write_auth(path: Path, data: dict[str, Any]) -> None:
    """Atomic replace; the grok CLI keeps its own lock file, we don't touch it."""
    payload = json.dumps(data, indent=2)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


__all__ = [
    "GrokRefreshResult",
    "REFRESH_SKEW_S",
    "grok_auth_has_refresh_token",
    "grok_auth_needs_refresh",
    "refresh_grok_auth",
]

"""Silent grok token refresh (no network: token endpoint is stubbed)."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import grok_auth_refresh
from grok_auth_refresh import (
    GrokRefreshResult,
    grok_auth_has_refresh_token,
    grok_auth_needs_refresh,
    refresh_grok_auth,
)

SCOPE = "https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"


def _jwt(exp_offset_s: int) -> str:
    def enc(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'ES256'})}.{enc({'exp': int(time.time()) + exp_offset_s})}.sig"


def _write_auth(path: Path, *, key: str, refresh_token: str | None = "refresh-1") -> None:
    entry = {
        "key": key,
        "email": "user@example.com",
        "principal_id": "principal",
        "oidc_issuer": "https://auth.x.ai",
        "oidc_client_id": CLIENT_ID,
        "expires_at": "2020-01-01T00:00:00.000000Z",
    }
    if refresh_token is not None:
        entry["refresh_token"] = refresh_token
    path.write_text(json.dumps({SCOPE: entry}, indent=2), encoding="utf-8")


def _payload(access: str, *, refresh: str | None = "refresh-2") -> dict:
    payload = {"access_token": access, "expires_in": 21600, "token_type": "Bearer"}
    if refresh is not None:
        payload["refresh_token"] = refresh
    return payload


def test_refresh_writes_rotated_tokens(tmp_path, monkeypatch) -> None:
    path = tmp_path / "auth.json"
    _write_auth(path, key=_jwt(-60))
    calls: list[tuple[str, str]] = []

    def fake_request(client_id: str, refresh_token: str) -> dict:
        calls.append((client_id, refresh_token))
        return _payload(_jwt(21600))

    monkeypatch.setattr(grok_auth_refresh, "_request_new_tokens", fake_request)

    result = refresh_grok_auth(path)

    assert result == GrokRefreshResult(True)
    assert calls == [(CLIENT_ID, "refresh-1")]
    saved = json.loads(path.read_text(encoding="utf-8"))[SCOPE]
    assert saved["refresh_token"] == "refresh-2"
    assert not grok_auth_needs_refresh(saved["key"])
    assert saved["expires_at"].endswith("Z")
    # untouched profile fields survive the rewrite
    assert saved["email"] == "user@example.com"
    assert saved["principal_id"] == "principal"
    # grok CLI writes 2-space indented JSON
    assert path.read_text(encoding="utf-8").startswith('{\n  "')


def test_refresh_invalid_grant_asks_for_login(tmp_path, monkeypatch) -> None:
    path = tmp_path / "auth.json"
    _write_auth(path, key=_jwt(-60))

    def reject(_client_id: str, _refresh_token: str) -> dict:
        raise grok_auth_refresh._Unauthorized()

    monkeypatch.setattr(grok_auth_refresh, "_request_new_tokens", reject)

    result = refresh_grok_auth(path)

    assert result.refreshed is False
    assert result.needs_login is True
    assert "grok login" in (result.error or "").lower()


def test_refresh_defers_to_cli_when_token_already_rotated(tmp_path, monkeypatch) -> None:
    path = tmp_path / "auth.json"
    _write_auth(path, key=_jwt(-60))
    cli_key = _jwt(3600)

    def cli_wins(_client_id: str, _refresh_token: str) -> dict:
        # The grok CLI refreshes the same file while our request is in flight.
        _write_auth(path, key=cli_key, refresh_token="cli-refresh")
        return _payload(_jwt(21600), refresh="our-refresh")

    monkeypatch.setattr(grok_auth_refresh, "_request_new_tokens", cli_wins)

    result = refresh_grok_auth(path)

    assert result.refreshed is True
    saved = json.loads(path.read_text(encoding="utf-8"))[SCOPE]
    assert saved["key"] == cli_key
    assert saved["refresh_token"] == "cli-refresh"


def test_refresh_without_auth_file_needs_login(tmp_path) -> None:
    result = refresh_grok_auth(tmp_path / "missing.json")
    assert result.refreshed is False
    assert result.needs_login is True


def test_refresh_without_refresh_token_needs_login(tmp_path) -> None:
    path = tmp_path / "auth.json"
    _write_auth(path, key=_jwt(-60), refresh_token=None)
    assert grok_auth_has_refresh_token(path) is False
    result = refresh_grok_auth(path)
    assert result.needs_login is True


def test_refresh_network_error_is_not_a_logout(tmp_path, monkeypatch) -> None:
    path = tmp_path / "auth.json"
    _write_auth(path, key=_jwt(-60))

    def offline(_client_id: str, _refresh_token: str) -> dict:
        raise OSError("network down")

    monkeypatch.setattr(grok_auth_refresh, "_request_new_tokens", offline)

    result = refresh_grok_auth(path)

    assert result.refreshed is False
    assert result.needs_login is False
    assert "network down" in (result.error or "")


def test_valid_token_is_not_refreshed(tmp_path, monkeypatch) -> None:
    from grok_app_usage import _fresh_access_token

    path = tmp_path / "auth.json"
    good = _jwt(3600)
    _write_auth(path, key=good)

    def boom(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("should not refresh a valid token")

    monkeypatch.setattr(grok_auth_refresh, "_request_new_tokens", boom)

    assert _fresh_access_token(path, good) == good


def test_expired_token_refreshes_before_billing(tmp_path, monkeypatch) -> None:
    import grok_app_usage

    path = tmp_path / "auth.json"
    _write_auth(path, key=_jwt(-60))
    fresh = _jwt(21600)
    monkeypatch.setattr(grok_auth_refresh, "_request_new_tokens", lambda *_a: _payload(fresh))
    monkeypatch.setattr(grok_app_usage, "default_grok_auth_path", lambda: path)
    monkeypatch.setattr(grok_app_usage, "_fetch_grok_settings_tiers", lambda _t: (None, None))

    seen: list[str] = []

    def fake_billing(access: str) -> dict:
        seen.append(access)
        return {"config": {"creditUsagePercent": 42.0, "currentPeriod": {"end": None}}}

    monkeypatch.setattr(grok_app_usage, "_request_billing", fake_billing)

    usage = grok_app_usage.fetch_grok_app_usage(auth_path=str(path))

    assert usage.usage_percent == 42.0
    assert seen == [fresh]


def test_billing_401_triggers_one_retry(tmp_path, monkeypatch) -> None:
    import grok_app_usage

    path = tmp_path / "auth.json"
    original = _jwt(3600)
    _write_auth(path, key=original)
    fresh = _jwt(21600)
    monkeypatch.setattr(grok_auth_refresh, "_request_new_tokens", lambda *_a: _payload(fresh))
    monkeypatch.setattr(grok_app_usage, "default_grok_auth_path", lambda: path)
    monkeypatch.setattr(grok_app_usage, "_fetch_grok_settings_tiers", lambda _t: (None, None))

    calls: list[str] = []

    def fake_billing(access: str) -> dict:
        calls.append(access)
        if len(calls) == 1:
            raise grok_app_usage._Unauthorized()
        return {"config": {"creditUsagePercent": 12.5, "currentPeriod": {}}}

    monkeypatch.setattr(grok_app_usage, "_request_billing", fake_billing)

    usage = grok_app_usage.fetch_grok_app_usage(auth_path=str(path))

    assert usage.usage_percent == 12.5
    assert calls == [original, fresh]

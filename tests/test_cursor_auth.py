"""Cursor access-token resolution (plain JWT + sealed envelope)."""

from __future__ import annotations

import base64

import pytest

from cursor_auth import (
    SAFE_STORAGE_PREFIX,
    AuthError,
    resolve_access_token,
)


def test_resolve_plain_jwt_passthrough() -> None:
    token = "aaa.bbb.ccc"
    assert resolve_access_token(token) == token


def test_resolve_empty_raises() -> None:
    with pytest.raises(AuthError):
        resolve_access_token("   ")


def test_resolve_sealed_empty_payload_raises() -> None:
    with pytest.raises(AuthError):
        resolve_access_token(SAFE_STORAGE_PREFIX)


def test_resolve_sealed_invalid_base64_raises() -> None:
    with pytest.raises(AuthError):
        resolve_access_token(SAFE_STORAGE_PREFIX + "!!!not-base64!!!")


def test_decrypt_roundtrip_windows_v10(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit-level AES-GCM envelope without touching real Cursor files."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    import cursor_auth as mod

    key = b"0" * 32
    nonce = b"1" * 12
    plain = b"header.payload.signature"
    ciphertext = AESGCM(key).encrypt(nonce, plain, None)
    # cryptography returns ciphertext||tag
    blob = b"v10" + nonce + ciphertext
    sealed = SAFE_STORAGE_PREFIX + base64.b64encode(blob).decode("ascii")

    monkeypatch.setattr(mod, "_windows_os_crypt_key", lambda _path=None: key)
    monkeypatch.setattr(mod.sys, "platform", "win32")

    assert resolve_access_token(sealed) == plain.decode("utf-8")

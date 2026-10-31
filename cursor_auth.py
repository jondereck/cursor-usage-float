"""Read Cursor access token from local SQLite (never persisted by this app)."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
from pathlib import Path


class AuthError(Exception):
    """Raised when the Cursor token cannot be read."""


SAFE_STORAGE_PREFIX = "cursor-safe-storage:v1:"
_DPAPI_KEY_PREFIX = b"DPAPI"


def default_state_db_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AuthError("APPDATA is not set; cannot locate Cursor state database.")
    return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def default_local_state_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AuthError("APPDATA is not set; cannot locate Cursor Local State.")
    return Path(appdata) / "Cursor" / "Local State"


def _looks_like_jwt(token: str) -> bool:
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


def _dpapi_unprotect(blob: bytes) -> bytes:
    """Decrypt a DPAPI blob with CryptUnprotectData (Windows only)."""
    if sys.platform != "win32":
        raise AuthError("DPAPI decryption is only available on Windows.")

    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buf = ctypes.create_string_buffer(blob)
    in_blob = DATA_BLOB(len(blob), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise AuthError("Windows DPAPI could not decrypt Cursor's storage key.")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _windows_os_crypt_key(local_state_path: Path | None = None) -> bytes:
    path = local_state_path or default_local_state_path()
    if not path.is_file():
        raise AuthError(
            "Cursor Local State not found. Open Cursor once while signed in, then retry."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError(f"Could not read Cursor Local State: {exc}") from exc

    encrypted_b64 = (
        payload.get("os_crypt", {}).get("encrypted_key")
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(encrypted_b64, str) or not encrypted_b64:
        raise AuthError("Cursor Local State is missing os_crypt.encrypted_key.")

    try:
        encrypted = base64.b64decode(encrypted_b64)
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Cursor os_crypt.encrypted_key is not valid base64.") from exc

    if not encrypted.startswith(_DPAPI_KEY_PREFIX):
        raise AuthError("Cursor os_crypt key is not DPAPI-wrapped.")

    return _dpapi_unprotect(encrypted[len(_DPAPI_KEY_PREFIX) :])


def _decrypt_electron_v10(key: bytes, blob: bytes) -> str:
    """Decrypt Chromium/Electron OSCrypt v10 AES-256-GCM payload."""
    if not blob.startswith(b"v10"):
        # Older Electron builds stored raw DPAPI ciphertext.
        if sys.platform == "win32":
            return _dpapi_unprotect(blob).decode("utf-8")
        raise AuthError("Unsupported Cursor safeStorage ciphertext format.")

    if len(blob) < 3 + 12 + 16:
        raise AuthError("Cursor safeStorage ciphertext is truncated.")

    nonce = blob[3:15]
    tag = blob[-16:]
    ciphertext = blob[15:-16]

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise AuthError(
            "Missing dependency 'cryptography' for decrypting Cursor's sealed token."
        ) from exc

    try:
        plain = AESGCM(key).decrypt(nonce, ciphertext + tag, None)
    except Exception as exc:  # noqa: BLE001
        raise AuthError(
            "Could not decrypt Cursor access token. Open Cursor while signed in, then retry."
        ) from exc
    return plain.decode("utf-8")


def decrypt_cursor_safe_storage(sealed: str, local_state_path: Path | None = None) -> str:
    """
    Decrypt a Cursor 3.27+ ``cursor-safe-storage:v1:…`` token.

    On Windows this uses Local State's DPAPI-wrapped OSCrypt key + AES-GCM.
    """
    if not sealed.startswith(SAFE_STORAGE_PREFIX):
        return sealed

    encoded = sealed[len(SAFE_STORAGE_PREFIX) :].strip()
    if not encoded:
        raise AuthError("Cursor access token envelope is empty.")

    try:
        blob = base64.b64decode(encoded)
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Cursor sealed token is not valid base64.") from exc

    if sys.platform != "win32":
        raise AuthError(
            "Encrypted Cursor tokens need platform decrypt support "
            f"(unsupported OS: {sys.platform})."
        )

    key = _windows_os_crypt_key(local_state_path)
    return _decrypt_electron_v10(key, blob)


def resolve_access_token(raw: str, local_state_path: Path | None = None) -> str:
    """Return a usable Bearer token from a DB cell (plain JWT or sealed)."""
    token = raw.strip()
    if not token:
        raise AuthError("Cursor access token is empty. Sign in to Cursor again.")

    if token.startswith(SAFE_STORAGE_PREFIX):
        token = decrypt_cursor_safe_storage(token, local_state_path=local_state_path)

    token = token.strip()
    if not token:
        raise AuthError("Decrypted Cursor access token is empty.")
    return token


def get_access_token(db_path: Path | None = None) -> str:
    """
    Read cursorAuth/accessToken from Cursor's local state DB.

    Opens the DB read-only and does not copy or store the token.
    Cursor 3.27+ may store an encrypted ``cursor-safe-storage:v1:`` envelope;
    that is decrypted in-memory on Windows before use.
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

    return resolve_access_token(str(row[0]))

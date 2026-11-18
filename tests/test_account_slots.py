"""Account slot labels and cursor_auth helpers."""

from __future__ import annotations

import base64
import json

from account_slots import format_cursor_account_title, same_account_email, short_email_display
from cursor_auth import jwt_email_claim, token_fingerprint


def _jwt(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"aaa.{body}.sig"


def test_short_email_gmail() -> None:
    assert short_email_display("jonnifas@gmail.com") == "jonnifas@gmail"


def test_format_cursor_account_title() -> None:
    assert format_cursor_account_title("jonnifas@gmail.com") == "Cursor (jonnifas@gmail)"


def test_same_account_email_normalizes_case_and_spaces() -> None:
    assert same_account_email("  Jon@Example.com ", "jon@example.com") is True


def test_same_account_email_rejects_missing_or_different() -> None:
    assert same_account_email(None, "jon@example.com") is False
    assert same_account_email("jon@example.com", None) is False
    assert same_account_email("jon@example.com", "other@example.com") is False
    assert same_account_email("not-an-email", "not-an-email") is False


def test_jwt_email_claim() -> None:
    token = _jwt({"email": "jonnifas@gmail.com"})
    assert jwt_email_claim(token) == "jonnifas@gmail.com"


def test_token_fingerprint_stable() -> None:
    assert token_fingerprint("abc") == token_fingerprint("abc")
    assert token_fingerprint("abc") != token_fingerprint("abd")

"""Labels for Cursor account slots (live login vs saved token file)."""

from __future__ import annotations

from cursor_auth import AuthError, get_access_token, jwt_email_claim, read_access_token_from_file


def short_email_display(email: str) -> str:
    """Compact label: jonderecknifas@gmail.com → jonderecknifas@gmail."""
    text = (email or "").strip()
    lower = text.lower()
    if lower.endswith("@gmail.com"):
        return text[: -len(".com")]
    return text


def format_cursor_account_title(email: str | None, *, prefix: str = "Cursor") -> str:
    if not email or "@" not in email:
        return f"{prefix} Models"
    return f"{prefix} ({short_email_display(email)})"


def cursor_slot_label(
    *,
    prefix: str,
    token: str | None,
    override: str = "",
    auto_from_email: bool = True,
    fallback: str,
) -> str:
    custom = (override or "").strip()
    if custom:
        return custom
    if auto_from_email and token:
        email = jwt_email_claim(token)
        if email:
            return format_cursor_account_title(email, prefix=prefix)
    return fallback


def resolve_live_cursor_token() -> str:
    return get_access_token()


def resolve_file_cursor_token(path: str) -> str:
    if not (path or "").strip():
        raise AuthError("Secondary Cursor token file is not set.")
    return read_access_token_from_file(path)

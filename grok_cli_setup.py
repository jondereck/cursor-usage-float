"""Install Grok CLI and start login when grok.com usage has no local auth."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from grok_app_usage import GrokAppError, default_grok_auth_path, read_grok_access_token

GROK_NPM_PACKAGE = "@xai-official/grok"
LOGIN_COOLDOWN_S = 300.0


@dataclass
class _EnsureState:
    install_attempted: bool = False
    last_login_launch: float = 0.0
    last_status: str | None = None


_state = _EnsureState()


def find_grok_executable() -> Path | None:
    """Resolve grok CLI on PATH (Windows .cmd / .exe)."""
    for name in ("grok", "grok.exe", "grok.cmd"):
        found = shutil.which(name)
        if found:
            return Path(found)
    appdata = os.environ.get("APPDATA")
    if appdata:
        for name in ("grok.cmd", "grok.exe"):
            candidate = Path(appdata) / "npm" / name
            if candidate.is_file():
                return candidate
    return None


def _npm_on_path() -> Path | None:
    npm = shutil.which("npm")
    return Path(npm) if npm else None


def install_grok_cli_via_npm(*, timeout_s: int = 180) -> tuple[bool, str]:
    npm = _npm_on_path()
    if npm is None:
        return False, "Node.js/npm not on PATH — install from nodejs.org or run: npm i -g @xai-official/grok"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [str(npm), "install", "-g", GROK_NPM_PACKAGE],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run npm install: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        reason = tail[-1][:160] if tail else f"npm exit {proc.returncode}"
        return False, f"npm install {GROK_NPM_PACKAGE} failed: {reason}"
    if find_grok_executable() is None:
        return False, f"Installed {GROK_NPM_PACKAGE} but grok is still not on PATH (restart terminal or log out/in)."
    return True, f"Installed {GROK_NPM_PACKAGE}."


def launch_grok_login(*, grok: Path | None = None) -> tuple[bool, str]:
    exe = grok or find_grok_executable()
    if exe is None:
        return False, "grok CLI not found after install."
    now = time.monotonic()
    if now - _state.last_login_launch < LOGIN_COOLDOWN_S:
        return True, _state.last_status or "Finish grok login in your browser…"
    _state.last_login_launch = now
    cmd = f'"{exe}" login'
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "Grok login", "cmd", "/k", cmd],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return False, f"Could not open grok login: {exc}"
    msg = "Opened grok login — complete sign-in in the browser, then refresh."
    _state.last_status = msg
    return True, msg


def grok_auth_ready(auth_path: Path | None = None) -> bool:
    path = auth_path or default_grok_auth_path()
    try:
        read_grok_access_token(path)
        return True
    except GrokAppError:
        return False


def ensure_grok_auth_for_usage(
    token_file: str,
    *,
    allow_install: bool = True,
    allow_login: bool = True,
) -> str | None:
    """Return a short status for the UI, or None when auth is ready to fetch."""
    custom = (token_file or "").strip()
    auth_path = default_grok_auth_path()
    if custom:
        candidate = Path(custom).expanduser()
        try:
            read_grok_access_token(candidate)
            return None
        except GrokAppError:
            # Custom path set but invalid — don't auto-install over user choice.
            return None

    if grok_auth_ready(auth_path):
        return None

    grok = find_grok_executable()
    if grok is None and allow_install and not _state.install_attempted:
        _state.install_attempted = True
        ok, detail = install_grok_cli_via_npm()
        if not ok:
            return detail
        grok = find_grok_executable()

    if grok is None:
        return (
            "Grok login not found. Install CLI: npm i -g @xai-official/grok then grok login "
            "(creates ~/.grok/auth.json)."
        )

    if allow_login:
        _ok, msg = launch_grok_login(grok=grok)
        return msg
    return "Run grok login once (creates ~/.grok/auth.json)."

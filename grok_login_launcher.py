"""Open a terminal and run `grok login` (Windows-first)."""

from __future__ import annotations

import shutil
import subprocess
import sys


def launch_grok_login_terminal() -> tuple[bool, str]:
    """Return (ok, user_message_on_failure)."""
    grok = shutil.which("grok")
    if not grok:
        return (
            False,
            "grok CLI not found. Install: irm https://x.ai/cli/install.ps1 | iex",
        )
    try:
        if sys.platform == "win32":
            create_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(
                ["cmd.exe", "/k", grok, "login"],
                creationflags=create_flags,
            )
        else:
            subprocess.Popen([grok, "login"])
    except OSError as exc:
        return False, f"Could not open terminal: {exc}"
    return True, ""

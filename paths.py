"""Resource path resolution that works in dev and PyInstaller onefile builds."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> Path:
    """
    Resolve a bundled resource.

    In a PyInstaller onefile build, data files are unpacked to ``sys._MEIPASS``.
    In development, resolve relative to this source file.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base).joinpath(*parts)
    return Path(__file__).resolve().parent.joinpath(*parts)

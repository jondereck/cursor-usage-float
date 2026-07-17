"""Tests for frozen-aware resource + launch path resolution."""

from __future__ import annotations

import sys
from pathlib import Path

import paths
import win_startup


def test_resource_path_dev_uses_project_dir() -> None:
    """Without PyInstaller, resources resolve next to the source tree."""
    had_meipass = hasattr(sys, "_MEIPASS")
    old = getattr(sys, "_MEIPASS", None)
    if had_meipass:
        delattr(sys, "_MEIPASS")
    try:
        result = paths.resource_path("assets", "app.ico")
        assert result == Path(paths.__file__).resolve().parent / "assets" / "app.ico"
    finally:
        if had_meipass:
            sys._MEIPASS = old  # type: ignore[attr-defined]


def test_resource_path_frozen_uses_meipass(tmp_path: Path) -> None:
    """Under PyInstaller onefile, resources resolve under sys._MEIPASS."""
    old = getattr(sys, "_MEIPASS", None)
    sys._MEIPASS = str(tmp_path)  # type: ignore[attr-defined]
    try:
        result = paths.resource_path("assets", "app.ico")
        assert result == tmp_path / "assets" / "app.ico"
    finally:
        if old is None:
            delattr(sys, "_MEIPASS")
        else:
            sys._MEIPASS = old  # type: ignore[attr-defined]


def test_launch_command_frozen_uses_executable(monkeypatch, tmp_path: Path) -> None:
    """A frozen build autostarts the exe itself, not python + main.py."""
    exe = tmp_path / "CursorUsageFloat.exe"
    exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    assert win_startup.launch_command() == f'"{exe}"'

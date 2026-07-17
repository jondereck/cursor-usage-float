"""HKCU Run registry helpers for Start with Windows."""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CursorUsageFloat"


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def launch_command() -> str:
    """Absolute command used for the Run key (quoted paths)."""
    # Frozen (portable .exe): autostart the executable itself.
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'

    root = _project_root()
    main_py = root / "main.py"
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if pythonw.is_file():
        return f'"{pythonw}" "{main_py}"'
    # Fallback: pythonw on PATH (console-less when available)
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            exe = candidate
    return f'"{exe}" "{main_py}"'


def is_start_with_windows() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return isinstance(value, str) and bool(value.strip())
    except OSError:
        return False


def set_start_with_windows(enabled: bool) -> None:
    """Create or remove the HKCU Run entry for this app."""
    try:
        import winreg
    except ImportError:
        return
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        pass

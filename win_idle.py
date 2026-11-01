"""System-wide idle detection for adaptive polling.

``seconds_since_last_input`` reports how long the keyboard/mouse have been
untouched, so the floater can poll quickly while you are at the PC and back
off while you are away.
"""

from __future__ import annotations

import sys


def seconds_since_last_input() -> float | None:
    """Seconds since the last keyboard/mouse input, or None when unavailable."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class _LastInputInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("dwTime", ctypes.c_uint),
            ]

        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        # GetLastInputInfo reports a 32-bit tick count; GetTickCount64 wraps it,
        # so compare in 32-bit space (correct for any idle span under ~49 days).
        now_ms = int(ctypes.windll.kernel32.GetTickCount64())
        elapsed_ms = (now_ms - int(info.dwTime)) & 0xFFFFFFFF
        return elapsed_ms / 1000.0
    except Exception:
        return None

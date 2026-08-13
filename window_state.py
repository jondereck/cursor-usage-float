"""Local-only floater window position + mode (not synced via Drive)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WindowState:
    x: int
    y: int
    minimized: bool = False


def default_window_state_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return Path.home() / ".cursor-usage-float" / "window-state.json"
    return Path(appdata) / "cursor-usage-float" / "window-state.json"


def virtual_screen_bounds(fallback_w: int = 1920, fallback_h: int = 1080) -> tuple[int, int, int, int]:
    """Return (origin_x, origin_y, width, height) for the full virtual desktop.

    On multi-monitor Windows this spans all displays (x/y may be negative).
    """
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79
            ox = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
            oy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
            vw = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
            vh = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
            if vw > 0 and vh > 0:
                return ox, oy, vw, vh
        except Exception:
            pass
    return 0, 0, max(1, int(fallback_w)), max(1, int(fallback_h))


def clamp_position(
    x: int,
    y: int,
    *,
    width: int,
    height: int,
    screen_w: int,
    screen_h: int,
    origin_x: int = 0,
    origin_y: int = 0,
) -> tuple[int, int]:
    """Keep the window inside the virtual desktop (all monitors)."""
    w = max(1, int(width))
    h = max(1, int(height))
    ox = int(origin_x)
    oy = int(origin_y)
    vw = max(w, int(screen_w))
    vh = max(h, int(screen_h))
    min_x = ox
    min_y = oy
    max_x = ox + vw - w
    max_y = oy + vh - h
    return max(min_x, min(int(x), max_x)), max(min_y, min(int(y), max_y))


def load_window_state(path: Path | None = None) -> WindowState | None:
    settings_path = path or default_window_state_path()
    if not settings_path.is_file():
        return None
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    x = payload.get("x")
    y = payload.get("y")
    minimized = payload.get("minimized", False)
    if not isinstance(x, int) or not isinstance(y, int):
        return None
    if isinstance(x, bool) or isinstance(y, bool):
        # bool is a subclass of int — reject.
        return None
    if not isinstance(minimized, bool):
        return None
    return WindowState(x=x, y=y, minimized=minimized)


def save_window_state(state: WindowState, path: Path | None = None) -> None:
    settings_path = path or default_window_state_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(asdict(state), indent=2) + "\n",
        encoding="utf-8",
    )

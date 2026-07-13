"""Shared visual tokens for floater + settings UI."""

from __future__ import annotations

# Soft charcoal-on-cream system (calm, not generic toolkit blue)
BG = "#ECEAE6"
CARD = "#F7F6F3"
INNER = "#F7F6F3"  # same as card — separation via spacing, not nested boxes
TEXT = "#1C1917"
MUTED = "#78716C"
BAR_BG = "#E7E5E4"
BAR_FG = "#4ADE80"  # early usage (green); ramps via bar_color_for_percent
BORDER = "#D6D3D1"
ACCENT = "#44403C"
DOT_OK = "#16A34A"
DOT_ERR = "#DC2626"
DOT_UNKNOWN = "#A8A29E"
DOT_PULSE = "#CA8A04"
WARN = "#F59E0B"
CRITICAL = "#EF4444"
STALE_BG = "#FEF3C7"
STALE_FG = "#92400E"
SWITCH_ON = "#44403C"
SWITCH_OFF = "#D6D3D1"
HOVER = "#E7E5E4"
MARKER_80 = "#78716C"
USAGE_MARK = 80.0


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return f"#{int(round(r)):02X}{int(round(g)):02X}{int(round(b)):02X}"


def _lerp_color(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t)


def bar_color_for_percent(value: float) -> str:
    """
    Traffic-light ramp by usage position:
    0–40 green, 40–80 green→amber, 80–100 amber→red.
    """
    value = max(0.0, min(100.0, float(value)))
    if value < 40.0:
        return BAR_FG
    if value < USAGE_MARK:
        return _lerp_color(BAR_FG, WARN, (value - 40.0) / 40.0)
    return _lerp_color(WARN, CRITICAL, (value - USAGE_MARK) / 20.0)

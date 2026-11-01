"""Adaptive refresh cadence for the floater.

The widget should feel live while you are actually at the PC and burning
usage, and back off to a lazy cadence while you are away so we don't hammer
Cursor's (unofficial) usage endpoint.
"""

from __future__ import annotations

FAST_POLL_MS = 30 * 1000
MEDIUM_POLL_MS = 90 * 1000
SLOW_POLL_MS = 3 * 60 * 1000
POLL_TICK_MS = 10 * 1000  # cheap idle check between refreshes, no network

FAST_IDLE_S = 2 * 60  # input within the last 2 min → fast cadence
MEDIUM_IDLE_S = 10 * 60  # input within the last 10 min → medium cadence
CHANGE_BOOST_S = 3 * 60  # usage just moved (e.g. background agent) → fast


def poll_interval_ms(idle_s: float | None, since_change_s: float | None = None) -> int:
    """Pick a refresh interval from system idle time and last usage change.

    ``idle_s`` is seconds since the last keyboard/mouse input (``None`` when
    unknown). ``since_change_s`` is seconds since the last observed usage
    movement, so agent-driven usage stays snappy even without input.
    """
    if since_change_s is not None and since_change_s <= CHANGE_BOOST_S:
        return FAST_POLL_MS
    if idle_s is None:
        return SLOW_POLL_MS
    if idle_s <= FAST_IDLE_S:
        return FAST_POLL_MS
    if idle_s <= MEDIUM_IDLE_S:
        return MEDIUM_POLL_MS
    return SLOW_POLL_MS

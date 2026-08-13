"""Light-theme chrome for pill + expanded frame."""

from __future__ import annotations

from theme import (
    BORDER,
    CARD,
    CRITICAL,
    PACE_STOP_BG,
    PACE_STOP_FG,
    PACE_WARN_BG,
    PACE_WARN_FG,
    TEXT,
    WARN,
    frame_border_for_state,
    pill_border_for_state,
    pill_chrome,
)


def test_frame_border_follows_soft_stop_state() -> None:
    assert frame_border_for_state("OK") == BORDER
    assert frame_border_for_state("WARN") == WARN
    assert frame_border_for_state("STOP") == CRITICAL


def test_pill_ok_has_no_gray_outline() -> None:
    assert pill_border_for_state("OK") == CARD
    assert pill_border_for_state("WARN") == WARN
    assert pill_border_for_state("STOP") == CRITICAL


def test_pill_chrome_matches_now_warn_reference() -> None:
    chrome = pill_chrome(
        "WARN",
        used_label="2.8",
        fair_label="3.0",
        fill_pct=93.0,
    )
    assert chrome.text == "2.8%/3.0%"
    assert chrome.show_badge is True
    assert chrome.badge_text == "WARN"
    assert chrome.badge_bg == PACE_WARN_BG
    assert chrome.badge_fg == PACE_WARN_FG
    assert chrome.number_color == WARN
    assert chrome.ring_color == WARN
    assert chrome.border_color == WARN


def test_pill_chrome_ok_compact() -> None:
    chrome = pill_chrome(
        "OK",
        used_label="0.1",
        fair_label="2.9",
        fill_pct=3.0,
    )
    assert chrome.text == "0.1%/2.9%"
    assert chrome.number_color == TEXT
    assert chrome.show_badge is False
    assert chrome.border_color == CARD


def test_pill_chrome_stop_chip() -> None:
    chrome = pill_chrome(
        "STOP",
        used_label="3.2",
        fair_label="3.0",
        fill_pct=106.0,
    )
    assert chrome.text == "3.2%/3.0%"
    assert chrome.badge_text == "STOP"
    assert chrome.badge_bg == PACE_STOP_BG
    assert chrome.badge_fg == PACE_STOP_FG
    assert chrome.border_color == CRITICAL

"""Tests for system idle detection."""

from __future__ import annotations

import sys

import pytest

from win_idle import seconds_since_last_input


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_seconds_since_last_input_is_sane() -> None:
    value = seconds_since_last_input()
    assert value is None or value >= 0

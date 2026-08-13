"""Tests for Win32 window position helpers (multi-monitor safe)."""

from __future__ import annotations

import sys

import pytest

from win_clickthrough import get_window_pos, set_window_pos, toplevel_hwnd


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_get_set_window_pos_round_trip() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.geometry("120x80+100+120")
    root.update_idletasks()
    root.update()
    hwnd = toplevel_hwnd(root)
    assert hwnd

    assert set_window_pos(hwnd, 2100, 90)  # likely 2nd-monitor-ish on 3280 virt
    root.update()
    pos = get_window_pos(hwnd)
    assert pos is not None
    assert pos[0] == 2100
    assert pos[1] == 90

    root.destroy()

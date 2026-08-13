# Remember window position Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and restore the floater’s last `x`/`y` and pill vs expanded mode across restarts.

**Architecture:** Local-only `%APPDATA%\cursor-usage-float\window-state.json` via a small `window_state.py` helper (not synced). `main.py` saves on drag-end, mode toggle, and quit; restores on launch with screen clamp.

**Tech Stack:** Python 3.11, tkinter, pytest, existing settings APPDATA layout.

## Global Constraints

- Window state must NOT go into synced `settings.json`.
- Missing/corrupt state → top-right default; honor `start_minimized` only then.
- Off-screen coordinates must be clamped into the visible work area.

---

## File map

| File | Role |
|------|------|
| `window_state.py` | load/save/clamp helpers |
| `tests/test_window_state.py` | unit tests |
| `main.py` | restore on launch; save on drag-end / mode / destroy |
| `docs/DEVLOG.md` | note the behavior |

---

### Task 1: `window_state` module (TDD)

**Files:** `tests/test_window_state.py`, `window_state.py`

- [x] Write failing tests: round-trip save/load; corrupt → None; clamp off-screen
- [x] Implement `WindowState(x, y, minimized)`, `default_window_state_path()`, `load_window_state`, `save_window_state`, `clamp_position`
- [x] Run `pytest tests/test_window_state.py` — all green

### Task 2: Wire restore + save in `main.py`

**Files:** `main.py`

- [x] On init: load state; if present, place + set minimized; else `_place_top_right` + existing `start_minimized`
- [x] Save after drag release, collapse/expand, and `destroy`
- [x] Clamp using current window size + screen metrics

### Task 3: Verify + docs

- [x] Run full `pytest`
- [x] Update `docs/DEVLOG.md`

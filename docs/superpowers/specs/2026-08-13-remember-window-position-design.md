# Remember floater position + mode — Design

Date: 2026-08-13  
App: cursor-usage-float

## Goal

When the user quits and relaunches, the floater returns to its **last screen
position** and **last mode** (expanded vs pill).

## Behavior

| Event | Result |
|--------|--------|
| Drag floater, release | Persist `x`, `y` (current mode unchanged) |
| Collapse / expand (− / Escape / tray Show) | Persist `minimized` + current `x`, `y` |
| Quit (✕ / tray Quit) | Persist final `x`, `y`, `minimized` |
| Launch with saved state | Place at saved `x`,`y`; pill if `minimized` else expanded |
| Launch with no saved state | Current default: top-right; honor `start_minimized` |
| Saved position off-screen | Clamp into the primary work area |

`start_minimized` applies only when **no** window-state file exists yet.
After the first successful save, last-quit mode wins.

## Storage (Approach A)

Local-only file (not synced via Drive):

`%APPDATA%\cursor-usage-float\window-state.json`

```json
{
  "x": 1400,
  "y": 24,
  "minimized": false
}
```

- Do **not** put these fields in `settings.json` (sync folder would replay
  another PC’s coordinates).
- Corrupt / missing file → treat as “no saved state”.

## Implementation sketch

- New module `window_state.py`: `load_window_state()`, `save_window_state()`,
  `clamp_position(x, y, width, height, screen_w, screen_h)`.
- `main.py`:
  - Replace unconditional `_place_top_right()` with restore-or-default.
  - On drag end (`_on_drag` release / existing ButtonRelease): save.
  - On `_collapse_to_pill` / `_expand_from_pill` / `destroy`: save.
- Tests: round-trip JSON; clamp off-screen; missing file → defaults.

## Out of scope

- Per-monitor Windows display-config IDs
- Remembering Settings window position
- Animating to the restored position

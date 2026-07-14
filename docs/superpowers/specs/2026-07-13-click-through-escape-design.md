# Click-through escape (soft unlock + hotkey)

## Problem

With **click-through** enabled, mouse events pass through the floater. The user cannot open Settings (gear / right-click) or turn click-through off, and becomes locked out.

## Goals

1. While the Settings window is open, temporarily disable click-through on the floater (**soft unlock**). The saved `click_through` value in `settings.json` is unchanged.
2. Provide a global hotkey that **opens Settings** so the user can escape without clicking the floater (soft unlock applies while Settings is open; toggle click-through from the switch). Registration tries `Ctrl+Shift+U`, then `Ctrl+Alt+Shift+U`, then `Ctrl+Shift+F12` if the previous combo is already taken.
3. On Settings close, restore click-through if the saved setting is still on.

## Non-goals

- Pin button / always-pinned Settings UI
- System tray menu
- New third-party dependencies

## Behavior

| State | Effective click-through |
|-------|-------------------------|
| `click_through=false`, settings closed | off |
| `click_through=true`, settings closed | on |
| `click_through=true`, settings open | **off** (soft unlock) |
| `click_through=false`, settings open | off |

Hotkey opens Settings (soft unlock applies). Click-through is toggled from the Settings switch.

## Implementation

- Pure helper: `effective_click_through(click_through: bool, settings_open: bool) -> bool`
- `settings_ui.open_settings` / `SettingsWindow`: visibility callback (`True` on open/`lift`, `False` on destroy)
- `UsageFloater`: track `_settings_open`; apply `set_click_through(hwnd, effective_click_through(...))`
- `win_hotkey.py`: dedicated thread `RegisterHotKey` + `GetMessage` (Tk UI thread cannot see `WM_HOTKEY`); try fallback combos; unregister on destroy
- README / Settings subtitle: document the active hotkey

## Testing

- Unit tests for `effective_click_through` truth table
- Existing settings load/save tests unchanged

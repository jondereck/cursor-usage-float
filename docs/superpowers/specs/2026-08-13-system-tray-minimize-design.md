# System tray minimize — Design

Date: 2026-08-13  
App: cursor-usage-float

## Goal

App stays reachable from the Windows system tray (notification area) with no
taskbar button. Header **−** collapses to the on-screen pill. Right-click tray
opens a Mechvibes-style menu.

## Behavior

| Action | Result |
|--------|--------|
| Header **−** | Collapse to on-screen **pill** |
| App running | Tray icon only (no taskbar button) |
| Left-click tray | Expand/show floater (lift + focus) |
| Right-click tray | Context menu at cursor |
| Menu → Cursor Usage | Same as left-click (bring float up) |
| Menu → Settings | Open usage settings |
| Menu → Extras → Enable at Startup | Toggle + persist + HKCU Run |
| Menu → Extras → Start Minimized | Toggle `start_minimized` + persist |
| Menu → Quit | Destroy app (remove tray) |
| Escape | Collapses to on-screen pill |

## Menu layout (Mechvibes-style)

```
Cursor Usage
Settings
Extras ▶  ✓  Enable at Startup
          ✓  Start Minimized
Quit
```

## Implementation

- `win_tray.py`: Win32 `Shell_NotifyIconW` + native `TrackPopupMenu`
  (not Tk `tk_popup` — that auto-fires Quit when the menu opens under the
  cursor near the taskbar). SetForegroundWindow + PostMessage(WM_NULL).
- No new pip dependencies (keeps portable exe stdlib-friendly)
- Icon: existing `assets/app.ico`
- Main floater uses `WS_EX_TOOLWINDOW` so it never appears on the taskbar

## Out of scope

- Mute / volume items (Mechvibes-only)
- Taskbar button while running

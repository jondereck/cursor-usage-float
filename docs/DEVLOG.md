# Dev log — cursor-usage-float

## 2026-08-13

### Done
- Usage bars now match Cursor's dashboard: **Cursor Models** (auto pool,
  rounded to a whole percent) and **Other Models** (API pool). Removed the
  old blended Total that no longer exists in Cursor.
- Today's pace follows the higher of the two pools.
- Minimize keeps the float on screen (pill). Presence is **system tray only**
  — no taskbar button while the app is running.
- Pill matches NOW—WARN reference: ring + `2.8%/3.0%` + chip; tight
  left/right padding (sizes to content, no empty capsule length).
- Header **−** collapses to the on-screen **pill**. Tray left-click
  restores/expands; right-click menu (Mechvibes-style): **Cursor Usage**,
  **Settings**, **Extras** (Enable at Startup / Start Minimized), **Quit**.
- Tray click crash fixed: Win32 `WndProc` must not call Tk (`after`); clicks
  are queued and drained on the Tk poll (left/right no longer hard-exit).
- Remembers last floater **position + pill/expanded** in local
  `%APPDATA%\cursor-usage-float\window-state.json` (not Drive-synced).
  Multi-monitor: save/restore via Win32 GetWindowRect/SetWindowPos (Tk
  `winfo_x`/`geometry` was snapping 2nd-monitor positions back to primary).

## 2026-07-16

### Done
- Shared **Sync folder** (Google Drive / OneDrive) for `pace-history.json` + `settings.json` across PCs.

## 2026-07-16 (evening)

### Done
- Pill respects **Pill metric** (Total vs Today's pace); cannot turn off both Total and Today's pace.

## 2026-07-17

### Done
- **Today's pace** now uses an **equal daily split** (`(remaining + usedToday) / days left`) instead of weekday weights, so the daily allowance auto-rebalances toward the reset date.
- **Single portable `.exe`** via PyInstaller (`--onefile --windowed`). Added `build.bat`, `paths.py` (frozen-aware `resource_path` via `sys._MEIPASS`), and frozen-aware autostart (`win_startup.launch_command` runs the exe itself). Output: `dist\CursorUsageFloat.exe` (~10 MB), launches with no cmd/python console.

### Later / backlog
- Consider code-signing the exe to reduce antivirus false positives.

## 2026-07-19

### Done
- Added a Settings → Sync status indicator: green synced, yellow Drive
  unavailable/local fallback, red write error, and gray local-only.
- Shows the newest successful shared `settings.json` / `pace-history.json`
  write time and refreshes every 10 seconds while Settings is open.

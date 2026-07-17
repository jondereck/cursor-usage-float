# Dev log — cursor-usage-float

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

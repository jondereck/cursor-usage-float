# Cursor Usage Floater

Small **always-on-top** floating window for Windows that shows your Cursor plan usage:

- **Total** %
- **Auto + Composer** %
- **API** %
- **Today's pace / soft-stop** — equal daily budget that automatically
  rebalances so usage lasts to the end of the billing cycle

Portable personal-use tool. No installer. Data stays on your machine.

## Run

1. Sign in to Cursor (desktop app).
2. Double-click `run.bat`  
   (or: `python main.py` if you already have Python 3.10+).

First run creates a local `.venv` in this folder. You can copy the whole folder elsewhere.

## Portable .exe (no Python needed)

Build a single-file executable you can copy to any Windows PC:

1. Double-click `build.bat` (needs Python 3.10+ once, on the build machine).
2. Grab `dist\CursorUsageFloat.exe` — copy that one file to your work / home PC and double-click it. No Python or `.venv` required.

Notes: first launch is a bit slower (the onefile bundle self-extracts), some antivirus tools may flag unsigned PyInstaller exes, and settings / pace data still live in `%APPDATA%` (or your Sync folder).

## How it works

1. Reads your Cursor access token from the local SQLite DB:  
   `%APPDATA%\Cursor\User\globalStorage\state.vscdb`
2. Calls Cursor’s HTTPS usage endpoint only:  
   `https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage`
3. Draws the progress bars and refreshes about every **3 minutes** (↻ for manual refresh).
4. Splits the start-of-day remaining allowance equally across the calendar
   days through reset. Under-use carries forward and raises later daily
   budgets; over-use lowers them. Soft-stop states:
   - **OK** — under 80% of today’s fair share
   - **WARN** — ≥ 80% (“slow down”)
   - **STOP** — ≥ 100% (“Stop for now — save allotment for later in the cycle”)

Settings are stored in:

`%APPDATA%\cursor-usage-float\settings.json`

Pace history (for the daily baseline) is stored in:

`%APPDATA%\cursor-usage-float\pace-history.json`

To sync **Today's pace** and **settings** across PCs (work + home), open Settings → **Sync** → **Browse…** and pick the same Google Drive / OneDrive folder on both machines. Leave empty to keep data on this PC only.

That folder will contain:

- `pace-history.json` — daily burn / Today's pace baseline  
- `settings.json` — appearance / behavior prefs  

Each PC still stores its own Sync folder path locally (Drive paths can differ).

## Safety / privacy

- Token is read from disk on each refresh and **never saved** by this app.
- Token is sent **only** over HTTPS to `api2.cursor.sh` (Cursor’s servers).
- No third-party servers, analytics, or telemetry.
- Cursor does **not** publish a stable public usage API; this uses the same unofficial pattern as other open-source usage widgets. Cursor updates may break parsing until fixed.

## Controls

- Drag the **header** (or pill) to move the window.
- **●** green/red connection status (error cue text only when needed — Auth / Offline / Error).
- Click the **pill** to expand; **−** or **Esc** to collapse.
- Gear icon opens settings (Appearance / Behavior / Startup). Changes apply live.
- Global hotkey opens settings even with click-through on (tries `Ctrl+Shift+U`, then `Ctrl+Alt+Shift+U`, then `Ctrl+Shift+F12`).
- Opening Settings temporarily disables click-through until the window closes.
- **↻** refresh now (pulses while fetching).
- **✕** close.
- Right-click the floater to open settings (useful if the header is hidden).

Progress bars shift color by urgency: calm under 70%, warn 70–90%, critical at 90%+.

## Settings

| Group | Options |
|--------|---------|
| **Appearance** | Density (`Full` / `Compact` / `Pill`), pill metric, header, **Total** on/off, **Today's pace** on/off, reset countdown, stale badge |
| **Behavior** | Always on top, click-through |
| **Sync** | Shared folder for pace + settings (Google Drive / OneDrive) — empty = local only |
| **Startup** | Start with Windows (HKCU `Run` key `CursorUsageFloat`), Open hidden (pill) |

## Dev tests

```bat
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Requirements

- Windows
- Python 3.10+ on PATH
- Cursor installed and signed in

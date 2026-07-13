# Cursor Usage Floater

Small **always-on-top** floating window for Windows that shows your Cursor plan usage:

- **Total** %
- **Auto + Composer** %
- **API** %

Portable personal-use tool. No installer. Data stays on your machine.

## Run

1. Sign in to Cursor (desktop app).
2. Double-click `run.bat`  
   (or: `python main.py` if you already have Python 3.10+).

First run creates a local `.venv` in this folder. You can copy the whole folder elsewhere.

## How it works

1. Reads your Cursor access token from the local SQLite DB:  
   `%APPDATA%\Cursor\User\globalStorage\state.vscdb`
2. Calls Cursor’s HTTPS usage endpoint only:  
   `https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage`
3. Draws the progress bars and refreshes about every **3 minutes** (↻ for manual refresh).

Settings are stored in:

`%APPDATA%\cursor-usage-float\settings.json`

## Safety / privacy

- Token is read from disk on each refresh and **never saved** by this app.
- Token is sent **only** over HTTPS to `api2.cursor.sh` (Cursor’s servers).
- No third-party servers, analytics, or telemetry.
- Cursor does **not** publish a stable public usage API; this uses the same unofficial pattern as other open-source usage widgets. Cursor updates may break parsing until fixed.

## Controls

- Drag the **header** (or pill) to move the window.
- **●** connection status — green after a successful refresh, red on auth/API error.
- **−** minimize to a small pill (`● 42%`). Click the pill to expand again.
- Gear icon opens LAYOUT settings (changes apply live).
- **↻** refresh now.
- **✕** close.
- Right-click the floater to open settings (useful if the header is hidden).

## Settings (LAYOUT)

| Option | What it does |
|--------|----------------|
| **Density** | Full (Total + Auto + API), Compact (Total only), or Minimal (pill) |
| **Minimized %** | Which metric the pill shows: Total, Auto, API, or Worst |
| **Always on top** | Keep the floater above other windows |
| **Click-through** | Mouse clicks pass through the floater (settings window still works so you can turn this off) |
| **Show header** | Title and control buttons |
| **Show reset countdown** | Time until billing cycle end when the API provides it |
| **Show stale-data badge** | Warning when the last successful update is older than ~6 minutes |
| **Start minimized** | Open as the pill on launch |

## Dev tests

```bat
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests\test_settings.py -q
```

## Requirements

- Windows
- Python 3.10+ on PATH
- Cursor installed and signed in

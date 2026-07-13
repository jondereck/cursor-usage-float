@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3.10+ and try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating local virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )
)

REM Stdlib-only app; requirements.txt is intentionally empty of packages.
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo.
  echo Widget exited with an error.
  pause
)

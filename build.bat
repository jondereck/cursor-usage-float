@echo off
setlocal
cd /d "%~dp0"

REM Build a single portable Windows .exe with PyInstaller.
REM Output: dist\CursorUsageFloat.exe

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

set "PY=.venv\Scripts\python.exe"

echo Installing build dependencies...
"%PY%" -m pip install -r requirements-dev.txt -q
if errorlevel 1 (
  echo Failed to install build dependencies.
  pause
  exit /b 1
)

echo Building portable exe...
"%PY%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name CursorUsageFloat ^
  --icon "assets\app.ico" ^
  --add-data "assets\app.ico;assets" ^
  main.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Done. Portable exe: dist\CursorUsageFloat.exe
echo Copy that single file anywhere (work PC / home PC) and double-click to run.
pause

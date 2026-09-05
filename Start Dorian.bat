@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Dorian - Storage Analyzer - Starting up
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python was not found on your PATH.
    echo Please install Python 3.10+ from https://python.org
    echo and make sure to check "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

if not exist venv (
    echo First-time setup: creating a private Python environment for this app...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create the virtual environment. See errors above.
        pause
        exit /b 1
    )
)

if not exist venv\installed.flag (
    echo Installing required packages ^(this only happens once^)...
    venv\Scripts\python.exe -m pip install --upgrade pip >nul
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Failed to install dependencies. See errors above.
        pause
        exit /b 1
    )
    echo done > venv\installed.flag
)

echo Launching Dorian...

if exist venv\Scripts\pythonw.exe (
    start "" venv\Scripts\pythonw.exe main.py
) else (
    start "" venv\Scripts\python.exe main.py
)

exit /b 0

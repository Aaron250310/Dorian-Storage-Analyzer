@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Dorian - Storage Analyzer - Starting up
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python was not found on this computer. Attempting to install it
    echo automatically ^(this only happens once^)...
    echo.

    where winget >nul 2>nul
    if not errorlevel 1 (
        echo Installing Python via winget - please approve any prompt that appears...
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    ) else (
        echo winget isn't available on this system - downloading Python directly instead...
        powershell -NoProfile -Command ^
          "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe' -OutFile '%TEMP%\python-installer.exe'"
        if not exist "%TEMP%\python-installer.exe" (
            echo.
            echo Automatic download failed. Please install Python 3.10+ manually from
            echo https://python.org ^(check "Add python.exe to PATH" during setup^),
            echo then run this file again.
            echo.
            pause
            exit /b 1
        )
        echo Running the Python installer - please approve any prompt that appears...
        "%TEMP%\python-installer.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=0
    )

    echo.
    echo Python has been installed. Please close this window and double-click
    echo "Start Dorian.bat" again to finish setup and launch the app.
    echo.
    pause
    exit /b 0
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

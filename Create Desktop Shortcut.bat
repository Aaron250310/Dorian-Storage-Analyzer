@echo off
setlocal
cd /d "%~dp0"

echo Creating a Desktop shortcut for Dorian...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$shortcut = $ws.CreateShortcut(\"$env:USERPROFILE\Desktop\Dorian.lnk\");" ^
  "$shortcut.TargetPath = '%~dp0Start Dorian.bat';" ^
  "$shortcut.WorkingDirectory = '%~dp0';" ^
  "$shortcut.Description = 'Scan and clean up storage with Dorian';" ^
  "$shortcut.Save()"

if errorlevel 1 (
    echo Something went wrong creating the shortcut. See errors above.
) else (
    echo Done! A shortcut named "Dorian" was added to your Desktop.
    echo You can now double-click it any time to launch the app.
)

pause

@echo off
cd /d "%~dp0"
if exist "dist\Golyahki\Golyahki.exe" (
    start "" "dist\Golyahki\Golyahki.exe"
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m golyah
) else (
    echo Run scripts\setup.ps1 first.
    pause
)

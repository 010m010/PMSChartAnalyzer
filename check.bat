@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat --dev before running checks.
    exit /b 1
)
".venv\Scripts\python.exe" -B scripts\check.py %*
exit /b %errorlevel%

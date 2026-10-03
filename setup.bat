@echo off
setlocal
cd /d "%~dp0"

set "requirements_file=requirements.txt"
if /i "%~1"=="--dev" (
    set "requirements_file=requirements-dev.txt"
) else if not "%~1"=="" (
    goto usage
)
if not "%~2"=="" goto usage

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto failed
)

".venv\Scripts\python.exe" -m pip install -r "%requirements_file%"
if errorlevel 1 goto failed

echo Setup complete. Run run.bat to start the app.
if /i "%~1"=="--dev" echo Run check.bat to check the project.
exit /b 0

:usage
echo Usage: setup.bat [--dev]
exit /b 2

:failed
echo Setup failed. Fix the error above and run setup.bat again.
exit /b 1

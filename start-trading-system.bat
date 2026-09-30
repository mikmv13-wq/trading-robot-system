@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Trading Robot System

echo ============================================
echo   Trading Robot System
echo ============================================
echo.

set "PYTHON_CMD="

rem Prefer the Windows Python launcher with Python 3.12+.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)

rem Fall back to python from PATH.
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD goto :python_missing

set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "TRADER=%VENV_DIR%\Scripts\trader.exe"
set "DESKTOP=%VENV_DIR%\Scripts\trader-desktop.exe"

if not exist "%VENV_PYTHON%" (
    echo [1/4] Creating Python virtual environment...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 goto :failed
) else (
    echo [1/4] Virtual environment: OK
)

if not exist "%DESKTOP%" (
    echo [2/4] Installing application and dependencies...
    "%VENV_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 goto :failed

    "%VENV_PYTHON%" -m pip install -e .
    if errorlevel 1 goto :failed
) else (
    echo [2/4] Application installation: OK
)

echo [3/4] Preparing local databases...
"%TRADER%" bootstrap
if errorlevel 1 goto :failed

echo [4/4] Starting desktop application...
echo.
start "" "%DESKTOP%"
if errorlevel 1 goto :failed

exit /b 0

:python_missing
echo.
echo ERROR: Python 3.12 or newer was not found.
echo Install Python 3.12+ from python.org and enable "Add Python to PATH".
echo Then run this file again.
echo.
pause
exit /b 1

:failed
echo.
echo ERROR: Trading Robot System could not be started.
echo Review the messages above for details.
echo.
pause
exit /b 1

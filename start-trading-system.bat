@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Trading Robot System

echo ============================================
echo   Trading Robot System
echo ============================================
echo.

set "PYTHON_CMD="
set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "TRADER=%VENV_DIR%\Scripts\trader.exe"
set "DESKTOP=%VENV_DIR%\Scripts\trader-desktop.exe"

rem First try python.exe from PATH. Any Python >= 3.12 is acceptable.
where python >nul 2>nul
if errorlevel 1 goto :check_py_launcher

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :check_py_launcher

set "PYTHON_CMD=python"
goto :python_ready

:check_py_launcher
rem Then try the Windows Python launcher and its default installed runtime.
where py >nul 2>nul
if errorlevel 1 goto :python_missing

py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py"
    goto :python_ready
)

rem New Windows Python Install Manager can install the missing runtime itself.
echo Python 3.12+ is not installed.
echo Attempting to install Python 3.12 automatically...
echo.
py install 3.12
if errorlevel 1 goto :python_missing

py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :python_missing

set "PYTHON_CMD=py -3.12"

:python_ready
if exist "%VENV_PYTHON%" goto :venv_ready

rem Remove an incomplete environment left by an interrupted/failed first run.
if exist "%VENV_DIR%" (
    echo Removing incomplete virtual environment...
    rmdir /s /q "%VENV_DIR%"
)

echo [1/4] Creating Python virtual environment...
%PYTHON_CMD% -m venv "%VENV_DIR%"

rem Do not rely only on ERRORLEVEL: verify that the environment was really created.
if not exist "%VENV_PYTHON%" goto :venv_failed
goto :install_check

:venv_ready
echo [1/4] Virtual environment: OK

:install_check
if exist "%DESKTOP%" if exist "%TRADER%" goto :application_ready

echo [2/4] Installing application and dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :failed

"%VENV_PYTHON%" -m pip install -e .
if errorlevel 1 goto :failed

if not exist "%DESKTOP%" goto :install_failed
if not exist "%TRADER%" goto :install_failed
goto :bootstrap

:application_ready
echo [2/4] Application installation: OK

:bootstrap
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
echo ERROR: Python 3.12 or newer is required and could not be installed automatically.
echo.
echo If you have the new Windows Python launcher, run:
echo     py install 3.12
echo.
echo Otherwise install Python 3.12+ from:
echo     https://www.python.org/downloads/windows/
echo.
echo After installation, run start-trading-system.bat again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo ERROR: Python was found, but the virtual environment could not be created.
echo Command used: %PYTHON_CMD% -m venv "%VENV_DIR%"
echo.
pause
exit /b 1

:install_failed
echo.
echo ERROR: Dependencies were installed, but application launchers were not created.
echo Try deleting the .venv folder and run this file again.
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

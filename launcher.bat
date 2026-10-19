@echo off
title CC-Toolbox Open
cd /d "%~dp0"
setlocal

set "VENV_DIR=%~dp0venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

:: ---- 1) First-run setup: create venv and install dependencies ----
:: Ready check: skip setup only when venv exists AND deps import OK.
:: File-exist alone is not enough: if the first pip run failed, the venv is
:: already created and exist-only check would skip install forever.
if not exist "%VENV_PY%" goto SETUP
"%VENV_PY%" -c "import flask" >nul 2>nul
if not errorlevel 1 goto STOP_CHECK
echo [WARN] venv exists but dependencies missing, reinstalling...

:SETUP
echo [1/3] Creating virtual environment (skip if exists)...
if exist "%VENV_PY%" goto DEPS_INSTALL
python -m venv "%VENV_DIR%"
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to create venv. Is Python 3.9+ installed and on PATH?
  echo         Download: https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist "%VENV_PY%" (
  echo [ERROR] venv was created but python.exe is missing: %VENV_PY%
  pause
  exit /b 1
)

:DEPS_INSTALL
echo [2/3] Installing dependencies via Tsinghua mirror (may take 1-3 min)...
"%VENV_PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check --no-warn-script-location
if errorlevel 1 (
  echo.
  echo [WARN] Mirror install failed, retrying with default PyPI...
  "%VENV_PY%" -m pip install -r requirements.txt --disable-pip-version-check --no-warn-script-location
  if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed. Check your network, then try again.
    pause
    exit /b 1
  )
)
echo [3/3] Setup finished.
echo.

:STOP_CHECK
:: ---- 2) Second click = stop (PID file decides) ----
if not exist "%~dp0.launcher.pid" goto START_SERVER
set /p PID=<"%~dp0.launcher.pid"
tasklist /FI "PID eq %PID%" 2>nul | find /I "python.exe" >nul
if errorlevel 1 (
  del "%~dp0.launcher.pid" 2>nul
  goto START_SERVER
)
echo [STOP] Stopping CC-Toolbox (PID %PID%)...
taskkill /F /PID %PID% >nul 2>nul
del "%~dp0.launcher.pid" "%~dp0.server_addr.txt" 2>nul
echo [OK] Stopped. Press any key to close.
pause >nul
exit /b 0

:START_SERVER
:: ---- 3) Start server in a minimized window ----
del "%~dp0.server_addr.txt" 2>nul
echo [START] Launching CC-Toolbox (minimized window keeps it running)...
start "CC-Toolbox Open Server" /MIN "%VENV_PY%" app.py

:: ---- 4) Wait for server_addr.txt (max 25s), then open browser ----
set /a WAITED=0
:WAITLOOP
if exist "%~dp0.server_addr.txt" goto READY
timeout /t 1 /nobreak >nul
set /a WAITED+=1
if %WAITED% lss 25 goto WAITLOOP
echo.
echo [ERROR] Server did not start within 25 seconds.
echo         The minimized "CC-Toolbox Open Server" window may show the error.
echo         You can also check server.log after using start_server.py.
pause
exit /b 1

:READY
set /p ADDR=<"%~dp0.server_addr.txt"
echo.
echo [OK] CC-Toolbox is running at:
echo      %ADDR%
echo.
echo      A minimized window keeps the server alive (close it to stop).
echo      Or double-click this launcher again to stop.
echo      Opening browser now...
start "" "%ADDR%"
timeout /t 2 /nobreak >nul
exit /b 0

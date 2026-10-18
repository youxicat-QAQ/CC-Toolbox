@echo off
title CC-Toolbox Open
cd /d "%~dp0"

:: 1) Locate Python: local venv first, then system python
set "PY="
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY (where python >nul 2>nul && set "PY=python")

if not defined PY (
  echo [ERROR] Python not found. Install Python 3.9+ and retry.
  pause & exit /b 1
)

:: 2) First run: create venv + install deps (with CN mirror, fallback to default)
if not exist "%~dp0venv\Scripts\python.exe" (
  echo [SETUP] Creating virtual environment...
  "%PY%" -m venv "%~dp0venv" || (echo [ERROR] venv create failed & pause & exit /b 1)
  set "PY=%~dp0venv\Scripts\python.exe"
  echo [SETUP] Installing dependencies (CN mirror)...
  "%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || (
    echo [WARN] Mirror failed, trying default PyPI...
    "%PY%" -m pip install -r requirements.txt || (echo [ERROR] pip install failed & pause & exit /b 1)
  )
)

:: 3) Stop if already running (PID file)
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
echo [OK] Stopped.
timeout /t 2 /nobreak >nul
exit /b 0

:START_SERVER
:: 4) Start server in new minimized window (venv guaranteed by step 2)
del "%~dp0.server_addr.txt" 2>nul
echo [START] Launching CC-Toolbox...
start "CC-Toolbox Open Server" /MIN "%~dp0venv\Scripts\python.exe" app.py

:: 5) Wait for server_addr.txt (max 20s) then open browser
set /a WAITED=0
:WAITLOOP
if exist "%~dp0.server_addr.txt" goto READY
timeout /t 1 /nobreak >nul
set /a WAITED+=1
if %WAITED% lss 20 goto WAITLOOP
echo [ERROR] Server did not start in 20s. Check messages above.
pause & exit /b 1

:READY
set /p ADDR=<"%~dp0.server_addr.txt"
echo [OK] CC-Toolbox started at %ADDR%
start "" "%ADDR%"
timeout /t 3 /nobreak >nul
exit /b 0

@echo off
title CC-Toolbox Setup
cd /d "%~dp0"
setlocal

set "VENV_DIR=%~dp0venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

echo ============================================
echo   CC-Toolbox  One-time Setup
echo   1/3 Create virtual environment
echo   2/3 Install dependencies
echo   3/3 Create desktop shortcut
echo ============================================
echo.

if exist "%VENV_PY%" goto INSTALL
echo [1/3] Creating virtual environment (one-time, may take ~30s)...
python -m venv "%VENV_DIR%"
if errorlevel 1 (
  echo [ERROR] Failed to create venv. Is Python 3.9+ installed and on PATH?
  pause
  exit /b 1
)
if not exist "%VENV_PY%" (
  echo [ERROR] venv python missing: %VENV_PY%
  pause
  exit /b 1
)

:INSTALL
echo [2/3] Installing dependencies via Tsinghua mirror (skip if already installed)...
"%VENV_PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check --no-warn-script-location
if errorlevel 1 (
  echo [WARN] Mirror failed, retrying with default PyPI...
  "%VENV_PY%" -m pip install -r requirements.txt --disable-pip-version-check --no-warn-script-location
  if errorlevel 1 (
    echo [ERROR] pip install failed. Check your network, then try again.
    pause
    exit /b 1
  )
)

echo [3/3] Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"
if errorlevel 1 (
  echo [ERROR] Shortcut creation failed.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   [OK] Setup finished!
echo   Double-click the "CC-Toolbox" icon on your
echo   desktop to start/stop the tool (no window).
echo.
echo   First double-click will open your browser
echo   at the app address automatically.
echo ============================================
pause
exit /b 0

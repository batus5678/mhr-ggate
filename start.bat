@echo off
setlocal EnableDelayedExpansion
title mhr-ggate Launcher

echo.
echo  ============================================================
echo    mhr-ggate ^| Windows Quick Start
echo  ============================================================
echo.

:: ── Check Python ────────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo  [!] Python not found in PATH.
    echo      Download from https://python.org and re-run this script.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  Python : %%v

:: ── Change to project root ───────────────────────────────────────────────────
cd /d "%~dp0"
echo  Root   : %CD%
echo.

:: ── Install pip deps ─────────────────────────────────────────────────────────
echo  [1/3] Checking Python dependencies...
python -c "import fastapi, uvicorn, httpx, cryptography" >nul 2>&1
if errorlevel 1 (
    echo  Installing: fastapi uvicorn httpx cryptography
    python -m pip install --quiet fastapi uvicorn httpx cryptography
    if errorlevel 1 (
        echo  [!] pip install failed. Run manually:
        echo      pip install fastapi uvicorn httpx cryptography
        pause
        exit /b 1
    )
    echo  Dependencies installed.
) else (
    echo  All dependencies present.
)
echo.

:: ── Check config ─────────────────────────────────────────────────────────────
echo  [2/3] Checking config.json...
if not exist config.json (
    if exist config.example.json (
        echo  config.json not found — copying from config.example.json
        copy /y config.example.json config.json >nul
        echo  [!] Edit config.json and fill in your script_id and auth_key!
        notepad config.json
        pause
    ) else (
        echo  [!] config.json not found.
        echo      Copy config.example.json to config.json and fill in your values.
        pause
        exit /b 1
    )
)

:: Quick validation — check for placeholder values
findstr /c:"PASTE_YOUR" config.json >nul 2>&1
if not errorlevel 1 (
    echo  [!] config.json still contains placeholder values.
    echo      Please edit it before starting.
    notepad config.json
    pause
)
echo  Config OK.
echo.

:: ── Launch GUI Launcher ───────────────────────────────────────────────────────
echo  [3/3] Launching GUI...
echo.
echo  ============================================================
echo    Close this window to stop all services.
echo  ============================================================
echo.

python launcher.py --config config.json
pause

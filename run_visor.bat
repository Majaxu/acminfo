@echo off
REM ============================================================================
REM  Server local del visor acminfo (LAN + Tailscale). Se relanza si se cae.
REM ============================================================================
cd /d "%~dp0"
if exist "%~dp0venv\Scripts\python.exe" (set "PY=%~dp0venv\Scripts\python.exe") else (set "PY=python")
:loop
"%PY%" "%~dp0serve_visor.py"
echo [visor] el server se corto (rc=%errorlevel%); reinicio en 15s...
timeout /t 15 /nobreak >nul
goto loop

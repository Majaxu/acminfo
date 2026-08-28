@echo off
REM ============================================================================
REM  Cifra el data.js y publica el visor a GitHub Pages (rama gh-pages).
REM  Lo corre la tarea "ZonapropWeb" tras el scrape; tambien a mano.
REM ============================================================================
cd /d "%~dp0"
if exist "%~dp0venv\Scripts\python.exe" (set "PY=%~dp0venv\Scripts\python.exe") else (set "PY=python")
"%PY%" "%~dp0publicar_web.py"
exit /b %errorlevel%

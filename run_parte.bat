@echo off
REM ============================================================================
REM  Arma y (si esta configurado) manda el parte diario de Zonaprop.
REM  No abre navegador: solo lee la base y los logs. Lo lanza la tarea
REM  "ZonapropParteDiario" cada manana. Tambien lo podes correr a mano.
REM ============================================================================
cd /d "%~dp0"
if exist "%~dp0venv\Scripts\python.exe" (set "PY=%~dp0venv\Scripts\python.exe") else (set "PY=python")
"%PY%" "%~dp0parte_diario.py"
exit /b %errorlevel%

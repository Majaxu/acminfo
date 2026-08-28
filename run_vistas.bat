@echo off
REM ============================================================================
REM  Barrido de vistas de Zonaprop, con auto-reinicio ante caidas.
REM  Lo lanza la tarea programada "ZonapropVistas". Se corta solo cuando python
REM  devuelve 0 (ventana cerrada / cola al dia / otra instancia activa) y se
REM  relanza solo si el proceso se cae (python devuelve != 0), hasta 20 veces.
REM ============================================================================
cd /d "%~dp0"
REM Usa el mismo Python del venv que el resto de los .bat (ahi estan nodriver, bs4, etc.)
if exist "%~dp0venv\Scripts\python.exe" (set "PY=%~dp0venv\Scripts\python.exe") else (set "PY=python")
setlocal enabledelayedexpansion
set /a intentos=0
:loop
"%PY%" "%~dp0zonaprop.py" vistas
set rc=!errorlevel!
if "!rc!"=="0" goto fin
set /a intentos+=1
if !intentos! GEQ 20 (
  echo [run_vistas] demasiados reinicios seguidos; corto.
  goto fin
)
echo [run_vistas] salida !rc!; reinicio !intentos!/20 en 60s...
timeout /t 60 /nobreak >nul
goto loop
:fin
endlocal

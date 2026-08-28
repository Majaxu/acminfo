@echo off
rem Corrida diaria del scraper. Pensado para la tarea programada (al iniciar la PC).
rem Con --daily sale enseguida si ya corrio hoy con exito.
cd /d "%~dp0"
if exist venv\Scripts\python.exe (
    set PY=venv\Scripts\python.exe
) else (
    set PY=python
)
%PY% zonaprop.py scrape --daily
exit /b %errorlevel%

@echo off
rem Corrida UNICA de cobertura completa (por tipos). Plena, sin --daily,
rem para garantizar que corra aunque ya haya corrido ese dia.
cd /d "%~dp0"
if exist venv\Scripts\python.exe (set PY=venv\Scripts\python.exe) else (set PY=python)
%PY% zonaprop.py scrape
exit /b %errorlevel%

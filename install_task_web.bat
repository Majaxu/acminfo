@echo off
REM ============================================================================
REM  Instala la tarea que publica el visor cifrado a GitHub Pages, diaria 09:15
REM  (despues del scrape de la manana). Requiere PC encendida + sesion iniciada.
REM ============================================================================
cd /d "%~dp0"
schtasks /Create /TN "ZonapropWeb" /TR "\"%~dp0run_publicar_web.bat\"" /SC DAILY /ST 09:15 /RU "%USERNAME%" /IT /F
echo.
if %errorlevel%==0 (
  echo Tarea 'ZonapropWeb' instalada (diaria, 09:15).
  echo   Probar ahora:  schtasks /Run    /TN "ZonapropWeb"
  echo   Quitar:        schtasks /Delete /TN "ZonapropWeb" /F
) else (
  echo Error creando la tarea. Avisame y lo adapto.
)
pause

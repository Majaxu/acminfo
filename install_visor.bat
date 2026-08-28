@echo off
REM ============================================================================
REM  Instala la tarea que mantiene vivo el server del visor (arranca al iniciar
REM  sesion, oculto). Requiere PC encendida + tu usuario con sesion iniciada.
REM ============================================================================
cd /d "%~dp0"
schtasks /Create /TN "ZonapropVisor" /TR "wscript.exe \"%~dp0run_visor_hidden.vbs\"" /SC ONLOGON /RU "%USERNAME%" /IT /F
echo.
if %errorlevel%==0 (
  echo Tarea 'ZonapropVisor' instalada (arranca al iniciar sesion, oculta).
  echo   Probar ahora:  schtasks /Run    /TN "ZonapropVisor"
  echo   Quitar:        schtasks /Delete /TN "ZonapropVisor" /F
) else (
  echo Hubo un error creando la tarea. Avisame y lo adapto.
)
pause

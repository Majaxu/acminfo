@echo off
REM ============================================================================
REM  Instala la tarea programada que mantiene vivo el barrido de vistas.
REM  Corre cada 1 hora, oculta; el propio script decide si esta dentro de la
REM  ventana (semana 18-09, finde 24h) y si ya hay otra corrida activa (lock),
REM  asi que la mayoria de las veces sale al instante sin abrir el navegador.
REM  Requiere: PC encendida + tu usuario con sesion iniciada (Chrome visible).
REM ============================================================================
cd /d "%~dp0"
schtasks /Create /TN "ZonapropVistas" /TR "wscript.exe \"%~dp0run_vistas_hidden.vbs\"" /SC HOURLY /MO 1 /RU "%USERNAME%" /IT /F
echo.
echo Tarea 'ZonapropVistas' instalada (horaria, oculta, interactiva).
echo   Ver:     schtasks /Query  /TN "ZonapropVistas"
echo   Correr:  schtasks /Run    /TN "ZonapropVistas"
echo   Quitar:  schtasks /Delete /TN "ZonapropVistas" /F
pause

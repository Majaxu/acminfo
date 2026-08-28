@echo off
REM ============================================================================
REM  Instala la tarea diaria que arma y manda el parte de la manana (08:45).
REM  No abre navegador; solo lee la base y los logs, asi que es liviana.
REM  Requiere PC encendida y tu usuario con sesion iniciada (igual que las otras).
REM ============================================================================
cd /d "%~dp0"
schtasks /Create /TN "ZonapropParteDiario" /TR "\"%~dp0run_parte.bat\"" /SC DAILY /ST 08:45 /RU "%USERNAME%" /IT /F
echo.
if %errorlevel%==0 (
  echo Tarea 'ZonapropParteDiario' instalada (diaria, 08:45).
  echo   Probar ahora:  schtasks /Run    /TN "ZonapropParteDiario"
  echo   Ver:           schtasks /Query  /TN "ZonapropParteDiario"
  echo   Quitar:        schtasks /Delete /TN "ZonapropParteDiario" /F
) else (
  echo Hubo un error creando la tarea. Avisame y te paso el comando adaptado.
)
pause

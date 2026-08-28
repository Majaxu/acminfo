@echo off
rem Crea una tarea UNICA para el 23/07/2026 a las 08:00 que corre la corrida
rem completa (run_once.bat). Interactiva: requiere PC prendida y sesion iniciada
rem (para que se pueda abrir la ventana de Chrome).
cd /d "%~dp0"
schtasks /create /tn "Zonaprop Corrida Unica 8am" /tr "\"%~dp0run_once.bat\"" /sc ONCE /st 08:00 /sd 23/07/2026 /it /f
echo.
if %errorlevel%==0 (
  echo Tarea "Zonaprop Corrida Unica 8am" creada para el 23/07/2026 a las 08:00.
  echo Se ejecuta una sola vez. Podes borrarla despues desde el Programador de tareas.
) else (
  echo Hubo un error creando la tarea. Si el problema es el formato de fecha,
  echo avisame y te paso el comando adaptado a tu Windows.
)
pause

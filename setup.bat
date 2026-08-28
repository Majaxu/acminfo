@echo off
rem Instalacion inicial: crea el entorno virtual, instala dependencias
rem y descarga el navegador Chromium que usa Playwright.
cd /d "%~dp0"
where python >nul 2>nul || (echo No se encontro Python en el PATH. Instalalo desde python.org & pause & exit /b 1)
if not exist venv (
    echo Creando entorno virtual...
    python -m venv venv
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Instalando el Chromium parcheado de patchright (~150 MB, una sola vez)...
python -m patchright install chromium
echo.
echo (Fallback) Descargando tambien el Chromium de Playwright, por si desactivas
echo el canal 'chrome' en config.json (canal: null)...
python -m playwright install chromium
echo.
echo NOTA: por defecto el scraper usa el Google Chrome instalado (canal 'chrome'),
echo que es lo mas indetectable. Si no tenes Chrome, edita config.json y poné
echo   "canal": null   para usar el Chromium descargado aca.
echo.
echo Listo. Proba con:  run_daily.bat   (o "venv\Scripts\python zonaprop.py scrape")
pause

# acminfo — puesta en marcha

Sistema de inteligencia de mercado inmobiliario de Córdoba: scraper diario de
Zonaprop, captura de **visualizaciones** (señal de demanda), visor con filtros y
**parte diario** por mail.

> **Qué NO está en el repo (a propósito):** la base de datos (`output/zonaprop.db`),
> la data del visor (`output/data.js`), los perfiles del navegador y el
> `email_config.json` con tu contraseña. Son datos locales/sensibles y viven en
> la PC que corre el scraper, dentro de `output/`. El repo tiene solo el **código**.

## Componentes

- **`zonaprop.py`** — scraper principal. Sub-comandos:
  - `scrape` — corrida diaria de precios (todos los segmentos, con resume).
  - `vistas` — barrido rotativo de visualizaciones. Autónomo: respeta la ventana
    horaria, le cede el turno al scrape de precios y **se autocura** si el perfil
    de Chrome quedó tomado por un cierre sucio.
  - `enrich` / `publish` / `compare` — auxiliares.
- **`parser.py`**, **`db.py`**, **`publish.py`** — parseo, base SQLite y armado del visor.
- **`parte_diario.py`** — arma el parte de la mañana (estado del scrape + vistas,
  cobertura, pendientes y top movimientos) y lo manda por mail.
- **`viewer.html`** — visor con filtros.

## Correr a mano

    venv\Scripts\python.exe zonaprop.py scrape
    venv\Scripts\python.exe zonaprop.py vistas --ahora --limite 5
    venv\Scripts\python.exe parte_diario.py

## Tareas programadas (Windows)

- `install_task_vistas.bat` — barrido de vistas horario (se autolimita a su ventana).
- `install_parte_diario.bat` — parte diario a las 08:45.
- `install_task_8am.bat` + `run_once.bat` — corrida de precios.

## Mail del parte

1. Copiá `email_config.example.json` a `email_config.json`.
2. Google Workspace: `smtp.gmail.com`, puerto `587`, `starttls`. Generá una
   **contraseña de aplicación** en https://myaccount.google.com/apppasswords
   (requiere verificación en 2 pasos) y pegala en `password`. Poné `"activar": true`.
3. `email_config.json` está en `.gitignore`: **nunca se sube al repo**.

## Requisitos / instalación limpia

    python -m venv venv
    venv\Scripts\pip install -r requirements.txt

Para el detalle de cómo se sortea el challenge de Cloudflare (técnica de tandas),
ver `README.md`.

# Zonaprop Córdoba — Scraper diario + visor en red

Snapshot diario de todas las propiedades publicadas en Zonaprop para Córdoba
Capital (venta, alquiler y alquiler temporal), con base histórica de precios,
visor con filtros para toda la red interna, y modo "enriquecer" para traer el
detalle de avisos puntuales.

## Cómo funciona la descarga

Zonaprop está detrás de Cloudflare con un challenge de JavaScript (la pantalla
"Un momento…"). Un cliente HTTP común (requests, curl, curl_cffi) no lo pasa
porque no ejecuta ese JS. Un navegador manejado por Playwright/patchright pasa
las primeras páginas pero **en la página ~10 Cloudflare escala a un managed
challenge interactivo (Turnstile con tilde "no soy un robot") que ningún
navegador automatizado resuelve — entra en loop**. La solución que sí funciona,
de forma desatendida, combina dos cosas:

- **Motor `nodriver`**: maneja un Chrome real por CDP sin las huellas de
  automatización de Playwright (no filtra la secuencia `Runtime.enable` /
  `Target.setAutoAttach` del protocolo de control, que es lo que el Turnstile
  fichea). Por eso el challenge inicial lo pasa "auto", sin pedir tilde.
- **Descarga en TANDAS (la clave)**: Cloudflare da un clearance que rinde ~9
  páginas y después re-verifica. Si se llega a esa re-verificación navegando en
  serie, sale el tilde interactivo. Para evitarlo, el scraper **refresca el
  clearance volviendo a pasar por la home cada `refresco_cada_paginas` páginas**
  (por defecto 8), *antes* de agotar ese presupuesto. Así nunca se llega al muro.

Abre cada página en ese navegador, deja que el clearance vigente la resuelva, y
lee el HTML ya renderizado. Se apoya en un **perfil persistente**
(`output\nodriver_profile`) que guarda el clearance entre páginas y entre
corridas.

**Importante**: durante la corrida se abre una ventana de Chrome que se va
moviendo sola entre páginas. Es normal — no la cierres mientras corre. Por eso
conviene que corra de noche (20:00), cuando no estás usando la PC.

## Instalación (una sola vez)

1. Tener Python 3.9+ instalado (con "Add to PATH" tildado) y **Google Chrome**
   instalado (nodriver usa el Chrome real del sistema).
2. Doble clic en `setup.bat` — crea el entorno virtual e instala dependencias
   (`nodriver`, más `patchright`/`playwright` que quedan como respaldo).
3. Doble clic en `install_task_20hs.bat` — registra la tarea programada
   ("Zonaprop Scraper Diario") para que corra todos los días a las 20:00 (con la
   PC prendida y sesión iniciada). Alternativa: `install_task.bat` la corre 2
   minutos después de cada inicio de sesión.
4. Para la primera corrida sin esperar: doble clic en `run_daily.bat`.

La corrida completa tarda alrededor de **2h30m** (unas 900-950 páginas para toda
Córdoba, cada una cargada en el navegador con pausas de 3 a 6 segundos, más los
refrescos de clearance de las tandas). Abre una ventana de Chrome visible que se
mueve sola — dejala tranquila. Consume unos 300-500 MB de RAM porque hay un
Chrome abierto. Si se corta (apagás la máquina, corte de internet, bloqueo
persistente), la próxima corrida del día retoma desde donde quedó.

## Cobertura (limitación conocida de Zonaprop)

Zonaprop deja de paginar pasado cierto punto: aunque una búsqueda anuncie 28.000
avisos, corta la paginación alrededor de la página ~670 y sirve solo una parte
(~63% en venta). No es un límite del scraper sino del sitio. Para acercarse al
100% hay que **partir cada operación en búsquedas más chicas** (por barrio y/o
por tipo de propiedad) que individualmente no toquen ese techo; la base
deduplica por `id`, así que las búsquedas que se solapen no cuentan doble. Se
configura en `segmentos` (ver Configuración). A más búsquedas, más páginas
totales y más tiempo por corrida.

## Qué queda en la carpeta de red (`\\servernt\serverd\MsDocs2\Zonaprop`)

| Archivo | Qué es |
|---|---|
| `viewer.html` | El visor. Doble clic desde cualquier máquina de la red. |
| `data.js` | Los datos que carga el visor. Se pisa en cada corrida (copia atómica: nunca queda a medias). |

El visor permite filtrar por operación, tipo, barrio, moneda, rango de precio,
m², ambientes y dormitorios; muestra promedios, medianas y USD/m²; marca los
avisos que bajaron de precio, los nuevos y los días publicados; y exporta lo
filtrado a CSV. El visor busca el `data.js` en la misma carpeta o en `output\`,
así que se puede abrir tanto la copia de red como `output\viewer.html` local.

## Qué queda en esta carpeta (`output\`)

| Archivo | Qué es |
|---|---|
| `zonaprop.db` | Base SQLite maestra: todos los avisos + historial de precios + corridas. |
| `snapshots\snapshot_AAAA-MM-DD.jsonl.gz` | La foto cruda de cada día (un aviso por línea, comprimido). |
| `data.js` | Copia local de lo publicado. |
| `viewer.html` | Copia del visor junto al data.js (para abrir en local). |
| `nodriver_profile\` | Perfil persistente de Chrome con el clearance de Cloudflare. |
| `logs\run_AAAA-MM-DD.log` | Log de cada corrida. |

## Comandos

```bat
venv\Scripts\python zonaprop.py scrape           :: corrida completa (con resume)
venv\Scripts\python zonaprop.py scrape --daily   :: idem, sale si ya corrió hoy
venv\Scripts\python zonaprop.py publish          :: regenerar data.js y copiar a la red
venv\Scripts\python zonaprop.py compare 2026-07-20 2026-08-20  :: comparar fechas
```

### Modo enriquecer

Trae de la ficha individual: descripción completa, antigüedad, amenities y
publicador. Pensado para usarlo sobre pocos avisos (1 request por aviso):

```bat
venv\Scripts\python zonaprop.py enrich --where "barrio LIKE '%Cerro%' AND operacion='venta'" --limit 40
venv\Scripts\python zonaprop.py enrich --ids 56018750,59634840
```

El `--where` es SQL sobre la tabla `avisos` (columnas: operacion, tipo, barrio,
precio, moneda, m2_total, ambientes, dormitorios, etc.).

## Configuración (`config.json`)

- `carpeta_red`: adónde publicar (poné `"publicar_a_red": false` para desactivar).
- `segmentos`: qué búsquedas scrapear. El `slug` es la parte de la URL sin
  `.html`; la paginación se agrega sola. Para más cobertura, agregá segmentos
  más específicos (por barrio o por tipo de propiedad).
- `motor`: `"nodriver"` (el que pasa el Cloudflare de Zonaprop de forma
  desatendida). Los valores `"patchright"`/`"playwright"` quedaron del historial
  pero NO pasan el managed challenge (ver Historial).
- `refresco_cada_paginas`: cada cuántas páginas se refresca el clearance por la
  home (default 8). No subirlo: si se pasa de ~9 aparece el tilde interactivo.
- `espera_challenge_seg`: cuánto espera a que un challenge se resuelva antes de
  refrescar/reintentar (default 120).
- `chrome_path` (opcional): ruta a `chrome.exe` si nodriver no lo autodetecta.
- `delay_min_seg` / `delay_max_seg`: pausas entre páginas. No bajarlos.
- `max_paginas_por_segmento`: 0 = sin límite. Útil para pruebas (ej: 3 o 12).

## Consultas SQL directas

La base es SQLite común: se abre con [DB Browser for SQLite](https://sqlitebrowser.org/)
o desde Python/pandas. Ejemplo — promedio USD/m² por barrio:

```sql
SELECT barrio, COUNT(*) n, ROUND(AVG(precio * 1.0 / m2_total)) usd_m2
FROM avisos
WHERE activo=1 AND operacion='venta' AND moneda='USD' AND m2_total > 0
GROUP BY barrio HAVING n >= 10 ORDER BY usd_m2 DESC;
```

## Notas

- **Ritmo**: el scraper carga ~1 página cada 3-6 segundos, como un usuario
  navegando, con descansos largos periódicos y un refresco de clearance cada 8
  páginas. Si una corrida junta menos de 100 avisos, o si una página falla
  definitivamente a mitad de camino, la corrida se aborta y NO pisa la base ni
  lo publicado (el checkpoint queda para retomar).
- **El perfil se ensucia**: si empezara a fallar seguido, borrá la carpeta
  `output\nodriver_profile` y volvé a correr — arranca con un perfil limpio (la
  primera corrida puede pedir el tilde una vez para sembrar el clearance).
- **Términos de uso**: scrapear va contra los ToS de Zonaprop. Uso personal,
  ritmo bajo, una corrida por día. No redistribuir los datos fuera de la red interna.
- **Cambios en el sitio**: si Zonaprop rediseña el HTML, el parser puede dejar
  de encontrar tarjetas (lo ves en el log como corridas con 0 avisos). Los
  selectores están todos en `parser.py`.

## Historial de enfoques de descarga (qué se probó)

El desafío de este proyecto no fue parsear los datos —eso salió a la primera—
sino pasar el Cloudflare de Zonaprop en modo desatendido. Registro de intentos,
del más liviano al que finalmente funcionó:

1. **`curl_cffi` (HTTP con TLS de Chrome imitado).** ❌ Falló.
   Imita la huella TLS de Chrome pero no ejecuta el JavaScript del challenge.
   Pasaba las primeras ~9 páginas y en la página 10 recibía `HTTP 403`
   consistentemente. El problema no era el ritmo: no ejecuta el challenge.

2. **Playwright con Chromium *headless*, perfil nuevo por corrida.** ❌ Falló.
   Bloqueo con `HTTP 403` ya en la página 2. Un navegador headless recién creado
   tiene huellas típicas de bot que Cloudflare fichea aún más rápido.

3. **Playwright *visible* + perfil persistente + calentamiento + parches
   anti-detección (`navigator.webdriver`, etc.).** ❌ Falló. Bloqueo en la página
   2 y **Turnstile en loop**: al tildar "confirmo que soy humano" lo volvía a
   pedir sin dejar pasar. Los parches de la capa JavaScript no alcanzan: el
   Turnstile detecta la capa de protocolo de control (CDP).

4. **patchright (fork drop-in de Playwright que tapa la fuga de CDP) + Chrome
   real + perfil persistente.** ❌ Falló, pero llegó más lejos. Pasó las páginas
   1 a 9 limpias y **en la 10 apareció el managed challenge interactivo, que
   loopeó** igual que el intento 3. Confirmó que tapar la fuga de CDP no alcanza
   contra el managed challenge de Zonaprop cuando se navega en serie.

5. **nodriver (Chrome por CDP, sin el shim de Playwright).** ❌ Igual que
   patchright: 1 a 9 perfectas, muro en la 10. Mismo patrón con los dos mejores
   motores → el problema no era el motor, sino el **presupuesto de ~9 páginas por
   clearance**.

6. **nodriver + TANDAS (la solución). ✅** Refrescar el clearance volviendo a la
   home cada 8 páginas, *antes* de llegar al muro de la 10. Testeado: cruza la
   página 10 de forma consistente y baja toda Córdoba (~930 requests, ~2h30m,
   cero bloqueos, sin pedir tilde). Es lo que corre hoy.

### Lo que descartamos
- **Teoría "es la reputación de la IP".** La misma IP abría Zonaprop bien en el
  Chrome normal el mismo día. Nunca fue la IP: es detección de automatización +
  el presupuesto por clearance.
- **Subir pausas / renovar sesión.** No movió la aguja: el problema no era el ritmo.

## Costo de la opción API (quedó como respaldo, no se usa)

La ruta gratis (nodriver + tandas) resolvió la descarga, así que la API pagó
quedó solo como plan B por si Zonaprop endurece el Cloudflare a futuro. Para
referencia: APIs por request (ScraperAPI, ScrapingBee, ZenRows) rondan USD
30-150/mes según frecuencia; los actores de Zonaprop en Apify (memo23,
crawlerbros) cobran por resultado (~USD 36 por snapshot completo con memo23).
Los precios cambian; verificá antes de contratar.

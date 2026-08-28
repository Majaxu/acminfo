# -*- coding: utf-8 -*-
"""Scraper de Zonaprop para Córdoba Capital — snapshot diario + visor en red.

Uso:
    python zonaprop.py scrape            # corrida completa del día (con resume)
    python zonaprop.py scrape --daily    # idem, pero sale sin hacer nada si ya corrió hoy
    python zonaprop.py enrich --where "barrio LIKE '%Cerro%'" --limit 50
    python zonaprop.py enrich --ids 56018750,59634840
    python zonaprop.py vistas            # barrido rotativo de visualizaciones (autónomo)
    python zonaprop.py publish           # regenerar data.js y copiar a la red
    python zonaprop.py compare 2026-07-20 2026-08-20   # comparador (secundario)
"""

import argparse
import asyncio
import gzip
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import db as dbmod
import parser as prs
import publish

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"
LOGS = OUT / "logs"
SNAPS = OUT / "snapshots"
DB_PATH = OUT / "zonaprop.db"
CHECKPOINT = OUT / "checkpoint.json"
LAST_RUN = OUT / "last_run.txt"
LOCK_VISTAS = OUT / "vistas.lock"
SCRAPE_LOCK = OUT / "scrape.lock"   # el scrape lo marca mientras corre; las vistas le ceden el turno

log = logging.getLogger("zonaprop")


# ------------------------------------------------------------------ utilidades

def cargar_config():
    with open(BASE / "config.json", encoding="utf-8") as f:
        return json.load(f)


def setup_logging(fecha, prefijo="run"):
    LOGS.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(LOGS / "{}_{}.log".format(prefijo, fecha), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


def hoy():
    return datetime.now().strftime("%Y-%m-%d")


# ------------------------------------------------------------------ descarga

# Selector que confirma que la página de listado renderizó de verdad
# (si aparece, el challenge de Cloudflare ya fue resuelto por el navegador).
SEL_LISTADO = '[data-qa="posting PROPERTY"]'
# Perfil propio de nodriver (el mismo que sembraron los spikes con el clearance).
BROWSER_PROFILE = OUT / "nodriver_profile"
# El barrido de vistas usa su PROPIO perfil para no chocar con el scrape de precios:
# dos Chrome sobre el mismo user-data-dir se traban al abrir.
BROWSER_PROFILE_VISTAS = OUT / "nodriver_profile_vistas"


FICHA_MARKERS = ("longDescription", "reactDescription",
                 "section-icon-features-property")

# Selector que confirma que una ficha individual renderizó (enrich / vistas).
SEL_FICHA = "#reactDescription, #longDescription, #section-icon-features-property"
# Patrón que confirma que el número de vistas (lo pinta el JS del cliente) ya salió.
RE_VISTAS_LISTO = r"[\d.]+\s*visualizaciones"


class Cliente:
    """Descarga con nodriver (Chrome real por CDP) + la técnica de TANDAS.

    Historia (ver README): un cliente HTTP no pasa el challenge JS; y tanto
    patchright como nodriver pasan ~9 páginas con un clearance, pero en la 10
    Cloudflare escala a un managed challenge INTERACTIVO (tilde) que ningún
    navegador automatizado resuelve — loopea. Lo que SÍ funciona: refrescar el
    clearance visitando la home cada pocas páginas (`refresco_cada_paginas`),
    ANTES de agotar ese presupuesto de ~9 páginas. Así nunca se llega al muro.

    nodriver maneja Chrome por CDP sin las huellas de automatización de
    Playwright, por eso el challenge inicial pasa 'auto' (sin tilde). Expone una
    interfaz sincrónica (get/pausa/close) para no tocar el resto del scraper;
    por dentro maneja el event loop async de nodriver."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.requests_hechos = 0
        self.delay_extra = 0.0
        self._hasta_descanso = random.randint(20, 35)
        self._desde_refresco = 0
        self._perfil = Path(cfg.get("_perfil_navegador") or BROWSER_PROFILE)
        cada = cfg.get("refresco_cada_paginas", 8)
        log.info("Motor de descarga: nodriver (tandas de %s páginas, perfil %s)",
                 cada, self._perfil.name)
        import nodriver  # import diferido
        self._uc = nodriver
        self._loop = nodriver.loop()
        self._perfil.mkdir(parents=True, exist_ok=True)
        # timeout de arranque: si Chrome se cuelga al abrir (perfil tomado por otra
        # instancia, etc.) no nos congelamos para siempre. _lanzar_navegador
        # además autocura el perfil si un cierre sucio anterior lo dejó tomado.
        self._browser = self._lanzar_navegador()
        self._refrescar_clearance()  # clearance inicial via home

    # -- infraestructura async -----------------------------------------------
    def _run(self, coro):
        """Corre una corrutina en el loop de nodriver (puente sync -> async)."""
        return self._loop.run_until_complete(coro)

    async def _start(self):
        kwargs = dict(headless=self.cfg.get("headless", False),
                      user_data_dir=str(self._perfil))
        ejec = self.cfg.get("chrome_path")  # opcional: ruta a chrome.exe si no lo autodetecta
        if ejec:
            kwargs["browser_executable_path"] = ejec
        return await self._uc.start(**kwargs)

    # -- arranque con autocuración del perfil --------------------------------
    def _lanzar_navegador(self):
        """Arranca Chrome. Si falla la conexión —el caso típico es que un cierre
        sucio anterior (PC forzada a apagarse, Chrome colgado) dejó el perfil
        TOMADO por un chrome.exe zombie o CORRUPTO— hace autocuración: mata el
        Chrome que tenga abierto NUESTRO perfil, aparta el perfil y reintenta una
        vez con carpeta limpia. Así el barrido no queda en crash-loop eterno."""
        t = self.cfg.get("timeout_arranque_seg", 90)
        try:
            return self._run(asyncio.wait_for(self._start(), t))
        except Exception as e:
            log.warning("El navegador no arrancó (%s). Autocuro el perfil y reintento…", e)
            self._matar_chrome_del_perfil()
            time.sleep(3)
            self._reciclar_perfil()
            return self._run(asyncio.wait_for(self._start(), t))

    def _matar_chrome_del_perfil(self):
        """Mata SOLO el chrome.exe que tenga abierto nuestro perfil (lo identifica
        por la línea de comando --user-data-dir), sin tocar el Chrome personal del
        usuario ni el del otro barrido. Solo Windows; en otros SO no hace nada."""
        if os.name != "nt":
            return
        marca = self._perfil.name  # p. ej. nodriver_profile_vistas
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
              "Where-Object { $_.CommandLine -like '*" + marca + "*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
              "-ErrorAction SilentlyContinue }")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           timeout=30, capture_output=True)
            log.info("Cerré el Chrome zombie del perfil %s (si había alguno).", marca)
        except Exception as e:
            log.warning("No pude cerrar el Chrome del perfil (%s); sigo igual.", e)

    def _reciclar_perfil(self):
        """Aparta el perfil actual (posible corrupción o lock) y prepara uno
        limpio. Si Windows no deja renombrar por un lock todavía vivo, cae a una
        carpeta nueva única para no chocar con el lock."""
        p = self._perfil
        apartado = p.with_name(p.name + "_corrupto")
        try:
            if apartado.exists():
                shutil.rmtree(apartado, ignore_errors=True)
            if p.exists():
                p.rename(apartado)
            p.mkdir(parents=True, exist_ok=True)
            log.info("Perfil %s apartado a %s y recreado limpio.", p.name, apartado.name)
        except Exception as e:
            alt = p.with_name(p.name + "_nuevo")
            i = 2
            while alt.exists():
                alt = p.with_name("%s_nuevo%d" % (p.name, i))
                i += 1
            alt.mkdir(parents=True, exist_ok=True)
            self._perfil = alt
            log.warning("No pude apartar el perfil (%s); uso carpeta nueva %s.",
                        e, alt.name)

    async def _cargo(self, tab, es_listado, espera_regex=None):
        """Espera el contenido real. Devuelve el HTML si cargó (o si es una
        página vacía/última válida), o None si sigue el challenge tras el máximo.
        Sondea sobre el HTML (no usa la API de selectores de nodriver).

        `espera_regex`: en fichas, además de confirmar que renderizó, espera (con
        una gracia corta) a que aparezca ese patrón — para valores que pinta el JS
        del cliente después de cargar (p. ej. el número de visualizaciones)."""
        pat = re.compile(espera_regex, re.I) if espera_regex else None
        limite = time.time() + self.cfg.get("espera_challenge_seg", 120)
        margen_vacio = time.time() + 18  # ventana para que rendericen las tarjetas
        gracia = self.cfg.get("espera_valor_seg", 10)
        listo_desde = None
        avisado = False
        while time.time() < limite:
            await asyncio.sleep(2)
            try:
                # timeout: si Chrome se cuelga en un challenge, no bloquear para siempre
                html = await asyncio.wait_for(tab.get_content(), 20)
            except Exception:  # noqa: BLE001  (incluye TimeoutError: página colgada)
                continue
            if prs.es_pagina_bloqueo(html):
                if not avisado:
                    log.info("Challenge de Cloudflare; espero/refresco clearance…")
                    avisado = True
                continue
            if es_listado:
                if html.count('data-qa="posting PROPERTY"') > 0:
                    return html
                # sin tarjetas y la página ya cargó (h1) => fin de segmento / vacía
                if time.time() > margen_vacio and "<h1" in html.lower():
                    return html
            else:
                if any(m in html for m in FICHA_MARKERS):
                    if pat is None or pat.search(html):
                        return html
                    # ficha lista pero el valor (client-rendered) todavía no; doy gracia
                    if listo_desde is None:
                        listo_desde = time.time()
                    elif time.time() - listo_desde > gracia:
                        return html
        return None

    async def _refrescar_clearance_async(self):
        """Vuelve a pasar por la home para renovar el token de Cloudflare."""
        nav_to = self.cfg.get("timeout_nav_seg", 60)
        try:
            tab = await asyncio.wait_for(self._browser.get(self.cfg["base_url"]), nav_to)
            limite = time.time() + self.cfg.get("espera_challenge_seg", 120)
            avisado = False
            while time.time() < limite:
                await asyncio.sleep(2)
                try:
                    html = await asyncio.wait_for(tab.get_content(), 20)
                except Exception:  # noqa: BLE001
                    continue
                if not prs.es_pagina_bloqueo(html) and "<h1" in html.lower():
                    break
                if not avisado:
                    log.info("Refrescando clearance en la home (si aparece el tilde, "
                             "resolvelo una vez en la ventana)…")
                    avisado = True
            await asyncio.sleep(random.uniform(3, 6))
        except Exception as e:  # noqa: BLE001
            log.info("No pude refrescar clearance (sigo igual): %s", str(e)[:80])
        self._desde_refresco = 0

    def _refrescar_clearance(self):
        self._run(self._refrescar_clearance_async())

    async def _get_async(self, url, es_listado, espera_regex=None):
        nav_to = self.cfg.get("timeout_nav_seg", 60)
        for intento in range(1, self.cfg["max_reintentos"] + 1):
            # refresco preventivo por tandas, antes de agotar el presupuesto
            if self._desde_refresco >= self.cfg.get("refresco_cada_paginas", 8):
                await self._refrescar_clearance_async()
            try:
                # timeout de navegación: si la página se cuelga (Turnstile trabado),
                # cortamos y reintentamos en vez de congelarnos toda la noche.
                tab = await asyncio.wait_for(self._browser.get(url), nav_to)
                self.requests_hechos += 1
                html = await self._cargo(tab, es_listado, espera_regex)
                if html is not None:
                    self._desde_refresco += 1
                    return html
                log.warning("Challenge no resuelto en %s (intento %s/%s).",
                            url, intento, self.cfg["max_reintentos"])
            except asyncio.TimeoutError:
                log.warning("Navegación COLGADA >%ss en %s (intento %s/%s) — la destrabo "
                            "con un refresco de clearance.", nav_to, url, intento,
                            self.cfg["max_reintentos"])
            except Exception as e:  # noqa: BLE001 - red/navegador inestable, reintentar
                log.warning("Error de navegador en %s: %s (intento %s)", url, e, intento)
            await self._refrescar_clearance_async()
            await asyncio.sleep(3 * intento)
        return None

    def get(self, url, espera_sel=SEL_LISTADO, espera_regex=None):
        """Devuelve el HTML renderizado o None tras los reintentos.

        `espera_sel`: decide entre listado (tarjetas) o ficha según el selector.
        `espera_regex`: si se pasa, en fichas espera (con gracia) a que ese patrón
        aparezca — para valores que pinta el JS después de cargar (p. ej. vistas)."""
        return self._run(self._get_async(url, espera_sel == SEL_LISTADO, espera_regex))

    def pausa(self):
        time.sleep(random.uniform(self.cfg["delay_min_seg"], self.cfg["delay_max_seg"])
                   + self.delay_extra)
        # cada tanto, un descanso largo (parece una persona mirando avisos)
        self._hasta_descanso -= 1
        if self._hasta_descanso <= 0:
            self._hasta_descanso = random.randint(20, 35)
            descanso = random.uniform(20, 45)
            log.info("Descanso de %.0fs", descanso)
            time.sleep(descanso)

    def close(self):
        try:
            res = self._browser.stop()
            if asyncio.iscoroutine(res):
                self._run(res)
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ scrape

def url_pagina(base, slug, pagina):
    if pagina <= 1:
        return "{}/{}.html".format(base, slug)
    return "{}/{}-pagina-{}.html".format(base, slug, pagina)


def leer_checkpoint(fecha):
    if CHECKPOINT.exists():
        try:
            cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
            if cp.get("fecha") == fecha:
                return cp
        except ValueError:
            pass
    return {"fecha": fecha, "segmentos_completos": [], "segmento_actual": None,
            "proxima_pagina": 1, "ids_vistos": []}


def guardar_checkpoint(cp):
    CHECKPOINT.write_text(json.dumps(cp), encoding="utf-8")


def snapshot_path(fecha):
    return SNAPS / "snapshot_{}.jsonl.gz".format(fecha)


def cmd_scrape(args):
    cfg = cargar_config()
    fecha = hoy()
    piloto = getattr(args, "piloto", None)

    if args.daily and piloto is None and LAST_RUN.exists() and LAST_RUN.read_text().strip() == fecha:
        print("Ya corrió hoy ({}). Nada que hacer.".format(fecha))
        return 0

    setup_logging(fecha)
    inicio = datetime.now().isoformat(timespec="seconds")
    if piloto is not None:
        log.info("=== PILOTO de scrape %s: %s página(s) por segmento, NO toca la base ===", fecha, piloto)
    else:
        log.info("=== Corrida %s ===", fecha)

    OUT.mkdir(parents=True, exist_ok=True)
    SNAPS.mkdir(parents=True, exist_ok=True)
    _scrape_lock_touch()  # avisar a las vistas que el scrape está corriendo (tiene prioridad)
    cp = leer_checkpoint(fecha)
    ids_vistos = set(cp["ids_vistos"])
    cliente = Cliente(cfg)
    detalle = {}
    max_pag = cfg.get("max_paginas_por_segmento") or 10 ** 6
    if piloto is not None:
        max_pag = piloto

    snap_file = gzip.open(snapshot_path(fecha), "at", encoding="utf-8")
    corrida_ok = True
    paginas_falladas = 0  # páginas fallidas en toda la corrida (tolerancia antes de abortar)
    fallos_seguidos = 0   # fallos consecutivos (para detectar navegador caído y reiniciarlo)
    try:
        for seg in cfg["segmentos"]:
            slug, oper = seg["slug"], seg["operacion"]
            if slug in cp["segmentos_completos"]:
                log.info("Segmento %s ya completo (resume), salto", slug)
                continue
            pagina = cp["proxima_pagina"] if cp["segmento_actual"] == slug else 1
            total_seg = 0
            paginas_vacias = 0
            total_anunciado = None

            while pagina <= max_pag:
                _scrape_lock_touch()  # heartbeat: mantengo el turno mientras scrapeo
                html = cliente.get(url_pagina(cfg["base_url"], slug, pagina))
                if html is None:
                    if pagina == 1:
                        log.warning("Segmento %s inaccesible (¿no existe?), salto", slug)
                        break
                    paginas_falladas += 1
                    fallos_seguidos += 1
                    if paginas_falladas > cfg.get("max_paginas_falladas", 20):
                        log.error("Demasiadas páginas fallidas (%s) — parece bloqueo real. "
                                  "Aborto y guardo el checkpoint para retomar.", paginas_falladas)
                        corrida_ok = False
                        break
                    # Si el navegador se cayó (varios fallos seguidos: 'Connection closed' /
                    # 'no close frame received'), lo REINICIO y reintento la misma página.
                    if fallos_seguidos >= 3:
                        log.warning("El navegador parece caído (%s fallos seguidos). Lo reinicio "
                                    "y reintento…", fallos_seguidos)
                        try:
                            cliente.close()
                        except Exception:  # noqa: BLE001
                            pass
                        cliente = Cliente(cfg)
                        fallos_seguidos = 0
                        continue
                    # Fallo puntual: salteo la página y sigo (no aborto toda la corrida).
                    log.warning("Página %s de %s falló; la salteo y sigo (fallos acumulados: %s).",
                                pagina, slug, paginas_falladas)
                    cp.update({"segmento_actual": slug, "proxima_pagina": pagina + 1,
                               "ids_vistos": sorted(ids_vistos)})
                    guardar_checkpoint(cp)
                    pagina += 1
                    cliente.pausa()
                    continue
                fallos_seguidos = 0  # página OK: reseteo el contador de caídas
                if total_anunciado is None:
                    total_anunciado = prs.parse_total_avisos(html)
                    log.info("Segmento %s: %s avisos anunciados", slug, total_anunciado)

                avisos = prs.parse_listado(html, operacion=oper)
                nuevos_en_pagina = [a for a in avisos if a["id"] not in ids_vistos]
                if not avisos or not nuevos_en_pagina:
                    paginas_vacias += 1
                    # la última página suele repetirse al pedir más allá del final
                    if paginas_vacias >= 2:
                        log.info("Fin del segmento %s en página %s", slug, pagina)
                        break
                else:
                    paginas_vacias = 0
                    for a in nuevos_en_pagina:
                        a["fecha"] = fecha
                        ids_vistos.add(a["id"])
                        snap_file.write(json.dumps(a, ensure_ascii=False) + "\n")
                    total_seg += len(nuevos_en_pagina)

                if pagina % 25 == 0:
                    log.info("%s: página %s, %s avisos acumulados", slug, pagina, total_seg)
                    snap_file.flush()
                cp.update({"segmento_actual": slug, "proxima_pagina": pagina + 1,
                           "ids_vistos": sorted(ids_vistos)})
                guardar_checkpoint(cp)
                pagina += 1
                cliente.pausa()

            if not corrida_ok:
                break
            detalle[slug] = {"avisos": total_seg, "anunciados": total_anunciado,
                             "paginas": pagina - 1}
            cobertura = (100.0 * total_seg / total_anunciado) if total_anunciado else 0
            log.info("Segmento %s listo: %s avisos (%.0f%% de lo anunciado)",
                     slug, total_seg, cobertura)
            if total_anunciado and cobertura < 70:
                log.warning("Cobertura baja en %s (%.0f%%): revisá el log", slug, cobertura)
            cp["segmentos_completos"].append(slug)
            cp["segmento_actual"] = None
            cp["proxima_pagina"] = 1
            guardar_checkpoint(cp)
    finally:
        snap_file.close()
        cliente.close()  # cerrar el navegador pase lo que pase
        _scrape_lock_soltar()  # liberar el turno para las vistas

    if not corrida_ok:
        log.error("Corrida incompleta: NO actualizo la base ni publico. "
                  "El checkpoint quedó guardado; la próxima corrida de hoy retoma solo.")
        return 1

    if piloto is not None:
        tot = sum(d.get("avisos", 0) for d in detalle.values())
        log.info("=== PILOTO OK: %s/%s segmentos abiertos, ~%s avisos parseados en %s pág/segmento. "
                 "Chrome abrió y scrapeó bien. NO toco la base (es prueba). ===",
                 len(detalle), len(cfg["segmentos"]), tot, piloto)
        CHECKPOINT.unlink(missing_ok=True)   # que la corrida real de hoy arranque limpia
        return 0

    # volcar snapshot completo a la base
    log.info("Actualizando base de datos...")
    con = dbmod.conectar(DB_PATH)
    todos = []
    with gzip.open(snapshot_path(fecha), "rt", encoding="utf-8") as f:
        vistos = set()
        for linea in f:
            try:
                a = json.loads(linea)
            except ValueError:
                continue
            if a["id"] not in vistos:   # dedup por si hubo resume
                vistos.add(a["id"])
                todos.append(a)
    if len(todos) < 100:
        log.error("Solo %s avisos scrapeados: corrida sospechosa, NO actualizo la base "
                  "ni publico. Revisá el log.", len(todos))
        return 1

    nuevos, cambios = dbmod.upsert_avisos(con, todos, fecha)
    retirados = dbmod.marcar_retirados(con, fecha)
    fin = datetime.now().isoformat(timespec="seconds")
    dbmod.registrar_corrida(con, fecha, inicio, fin, len(todos), nuevos, retirados,
                            cambios, detalle)
    log.info("Base actualizada: %s avisos activos, %s nuevos, %s retirados, %s cambios de precio",
             len(todos), nuevos, retirados, cambios)

    _publicar(cfg, con)
    con.close()
    LAST_RUN.write_text(fecha, encoding="utf-8")
    CHECKPOINT.unlink(missing_ok=True)
    log.info("=== Corrida %s terminada (%s requests) ===", fecha, cliente.requests_hechos)
    return 0


# ------------------------------------------------------------------ publish

def _publicar(cfg, con):
    datos = dbmod.datos_para_visor(con)
    mi = [k.lower() for k in cfg.get("mi_inmobiliaria", [])]
    for a in datos["avisos"]:
        d = a.get("descripcion")
        if d and len(d) > cfg.get("descripcion_max_chars", 160):
            a["descripcion"] = d[:cfg["descripcion_max_chars"]] + "…"
        # es_mia: el publicador contiene TODAS las palabras clave de mi inmobiliaria.
        # (particular = publicador None; lo deriva el visor.)
        pub = (a.get("publicador") or "").lower()
        a["es_mia"] = bool(mi) and all(k in pub for k in mi)
    publish.generar_datajs(datos, OUT / "data.js")
    # Dejar output\ auto-suficiente: copiar el visor al lado del data.js, así
    # también se puede abrir output\viewer.html en local (no solo desde la red).
    try:
        shutil.copy2(BASE / "viewer.html", OUT / "viewer.html")
    except OSError as e:  # noqa: BLE001
        log.warning("No pude copiar viewer.html a output\\: %s", e)
    if cfg.get("publicar_a_red"):
        publish.publicar_a_red(OUT, cfg["carpeta_red"], ["data.js"])
        # el visor se copia desde la raíz del proyecto
        publish.publicar_a_red(BASE, cfg["carpeta_red"], ["viewer.html"])


def cmd_publish(_args):
    cfg = cargar_config()
    setup_logging(hoy())
    con = dbmod.conectar(DB_PATH)
    _publicar(cfg, con)
    con.close()
    return 0


# ------------------------------------------------------------------ enrich

def cmd_enrich(args):
    cfg = cargar_config()
    fecha = hoy()
    setup_logging(fecha)
    con = dbmod.conectar(DB_PATH)

    if args.ids:
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
        filas = [con.execute("SELECT id, url FROM avisos WHERE id=?", (i,)).fetchone()
                 for i in ids]
        filas = [f for f in filas if f]
    else:
        where = args.where or "1=1"
        sql = ("SELECT id, url FROM avisos WHERE activo=1 AND enriquecido IS NULL "
               "AND ({}) LIMIT ?".format(where))
        try:
            filas = con.execute(sql, (args.limit,)).fetchall()
        except Exception as e:  # noqa: BLE001
            print("Filtro SQL inválido: {}".format(e))
            return 1

    if not filas:
        print("No hay avisos que enriquecer con ese filtro.")
        return 0
    log.info("Enriqueciendo %s avisos...", len(filas))
    # selector que confirma que la ficha individual renderizó
    sel_ficha = "#reactDescription, #longDescription, #section-icon-features-property"
    cliente = Cliente(cfg)
    ok = 0
    try:
        for f in filas:
            url = f["url"]
            if url.startswith("/"):
                url = cfg["base_url"] + url
            html = cliente.get(url, espera_sel=sel_ficha)
            if html:
                datos = prs.parse_ficha(html)
                dbmod.actualizar_enriquecido(con, f["id"], datos, fecha)
                ok += 1
                log.info("Enriquecido %s (%s/%s)", f["id"], ok, len(filas))
            cliente.pausa()
    finally:
        cliente.close()
    log.info("Listo: %s/%s fichas enriquecidas", ok, len(filas))
    _publicar(cfg, con)
    con.close()
    return 0


# ------------------------------------------------------------------ vistas

def dentro_de_ventana(cfg, ahora=None):
    """¿Estamos dentro de la ventana de scrapeo? Semana: 18:00-09:00 (cruza
    medianoche). Fin de semana: 24 h. Todo configurable."""
    ahora = ahora or datetime.now()
    if ahora.weekday() >= 5:                       # sábado / domingo
        return bool(cfg.get("vistas_finde_24h", True))
    ini = cfg.get("vistas_hora_inicio", 18)
    fin = cfg.get("vistas_hora_fin", 9)
    h = ahora.hour
    return h >= ini or h < fin


def _dias_publicado(fecha_pub, fecha_ref):
    """Antigüedad del aviso (días) para normalizar las vistas por edad."""
    if not fecha_pub:
        return None
    try:
        d0 = datetime.strptime(fecha_pub, "%Y-%m-%d")
        d1 = datetime.strptime(fecha_ref, "%Y-%m-%d")
        return max(0, (d1 - d0).days)
    except ValueError:
        return None


def _lock_vistas_activo():
    """True si otra corrida de vistas está viva (lock reciente < 3 min)."""
    try:
        return LOCK_VISTAS.exists() and (time.time() - LOCK_VISTAS.stat().st_mtime) < 180
    except OSError:
        return False


def _lock_vistas_touch():
    try:
        LOCK_VISTAS.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    except OSError:
        pass


def _lock_vistas_soltar():
    try:
        LOCK_VISTAS.unlink(missing_ok=True)
    except OSError:
        pass


def _scrape_lock_touch():
    try:
        SCRAPE_LOCK.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    except OSError:
        pass


def _scrape_lock_soltar():
    try:
        SCRAPE_LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def _scrape_activo():
    """True si el scrape de precios está corriendo (lock fresco < 10 min). Las vistas
    le ceden el turno para no solapar dos Chrome sobre la misma IP."""
    try:
        return SCRAPE_LOCK.exists() and (time.time() - SCRAPE_LOCK.stat().st_mtime) < 600
    except OSError:
        return False


def cmd_vistas(args):
    """Barrido rotativo de fichas para capturar visualizaciones (serie temporal).

    Autónomo y reanudable: toma de la cola los avisos activos sin lectura reciente
    (cadencia semanal), respeta la ventana horaria, se frena solo ante bloqueos
    (sin resolver CAPTCHAs) y reinicia el navegador si se cae. Guarda los átomos
    crudos (vistas + nuestras visitas de 30 días) para corregir la contaminación
    al leer. Códigos de salida: 0 = fin limpio (ventana cerrada / cola vacía / otra
    instancia activa); != 0 = crash (el .bat lo relanza)."""
    cfg = cargar_config()
    fecha = hoy()
    setup_logging(fecha, "run_vistas")

    if _lock_vistas_activo():
        print("Otra corrida de vistas ya está activa; salgo.")
        return 0
    if not getattr(args, "ahora", False) and not dentro_de_ventana(cfg):
        print("Fuera de la ventana horaria de scrapeo de vistas; salgo. (usá --ahora para forzar)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    con = dbmod.conectar(DB_PATH)
    limite_fecha = (datetime.now() - timedelta(days=cfg.get("vistas_cadencia_dias", 7))
                    ).strftime("%Y-%m-%d")
    tope = args.limite if getattr(args, "limite", None) is not None else cfg.get("vistas_max_por_corrida", 0)
    cola = dbmod.avisos_pendientes_vistas(con, limite_fecha, tope)
    if not cola:
        log.info("Vistas: no hay fichas pendientes (todo fresco). Nada que hacer.")
        con.close()
        return 0

    log.info("=== Barrido de vistas %s: %s fichas pendientes ===", fecha, len(cola))
    # ritmo gentil propio del barrido de fichas (más lento que el listado)
    cfg["delay_min_seg"] = cfg.get("vistas_delay_min_seg", 8)
    cfg["delay_max_seg"] = cfg.get("vistas_delay_max_seg", 20)
    cfg["_perfil_navegador"] = str(BROWSER_PROFILE_VISTAS)  # perfil propio: no chocar con el scrape
    reiniciar_cada = cfg.get("vistas_reiniciar_navegador_cada", 300)
    max_ch = cfg.get("vistas_backoff_challenges", 4)
    pausa_ch = cfg.get("vistas_backoff_pausa_seg", 900)

    _lock_vistas_touch()
    cliente = None
    hechas = fallos_seguidos = challenges_seguidos = 0
    rc = 0

    def _en_ventana():
        return getattr(args, "ahora", False) or dentro_de_ventana(cfg)

    try:
        for item in cola:
            if not _en_ventana():
                log.info("Se cerró la ventana horaria; corto acá y retomo en la próxima.")
                break
            # PRIORIDAD AL SCRAPE DE PRECIOS: si está corriendo, cierro Chrome y espero
            # (cero solapamiento: nunca dos Chrome sobre la misma IP a la vez).
            cedido = False
            while _scrape_activo() and _en_ventana():
                if cliente is not None:
                    log.info("Vistas: el scrape de precios está corriendo — cierro Chrome y le cedo el turno.")
                    try:
                        cliente.close()
                    except Exception:  # noqa: BLE001
                        pass
                    cliente = None
                    cedido = True
                _lock_vistas_touch()
                time.sleep(60)
            if not _en_ventana():
                log.info("Se cerró la ventana mientras cedía el turno al scrape; retomo en la próxima.")
                break
            if cliente is None:
                cliente = Cliente(cfg)
                if cedido:
                    log.info("Vistas: el scrape terminó — retomo el barrido.")
            _lock_vistas_touch()
            url = item["url"] or ""
            if url.startswith("/"):
                url = cfg["base_url"] + url
            html = cliente.get(url, espera_sel=SEL_FICHA, espera_regex=RE_VISTAS_LISTO)
            ts = datetime.now().isoformat(timespec="seconds")

            if html is None:
                fallos_seguidos += 1
                challenges_seguidos += 1
                # freno de alerta temprana: si se acumulan challenges, pauso y bajo el
                # ritmo. NUNCA intento resolver el CAPTCHA; simplemente me hago a un lado.
                if challenges_seguidos >= max_ch:
                    log.warning("Vistas: %s challenges seguidos — freno %s min y bajo el ritmo "
                                "(no intento resolver el CAPTCHA).", challenges_seguidos, pausa_ch // 60)
                    cliente.delay_extra += 3.0
                    _lock_vistas_touch()
                    time.sleep(pausa_ch)
                    challenges_seguidos = 0
                if fallos_seguidos >= 3:
                    log.warning("Vistas: navegador caído (%s fallos) — lo reinicio.", fallos_seguidos)
                    try:
                        cliente.close()
                    except Exception:  # noqa: BLE001
                        pass
                    cliente = Cliente(cfg)
                    fallos_seguidos = 0
                cliente.pausa()
                continue

            fallos_seguidos = challenges_seguidos = 0
            # Contamos nuestras visitas PREVIAS dentro de la ventana de 30 días (la de
            # ahora todavía no está logueada) y recién después registramos la de ahora.
            n30 = dbmod.nuestras_visitas_30d(con, item["id"], ts)
            dbmod.log_visita_scraper(con, item["id"], ts)
            datos = prs.parse_ficha(html)
            vistas = datos.get("visualizaciones")
            # Antigüedad del aviso: preferimos la de la ficha ("Publicado hace N días");
            # si no aparece, la derivamos de fecha_publicacion del listado.
            dias_pub = datos.get("dias_publicado")
            if dias_pub is None:
                dias_pub = _dias_publicado(item.get("fecha_publicacion"), fecha)
            dbmod.registrar_vistas(con, item["id"], fecha, vistas, n30, dias_pub)
            # De paso completamos la superficie cubierta (solo esta en la ficha),
            # para que el visor la muestre. Se llena a medida que barremos fichas.
            dbmod.actualizar_medidas(con, item["id"],
                                     m2_cubierto=datos.get("m2_cubierto"),
                                     m2_total=datos.get("m2_total"))
            hechas += 1
            if hechas % 50 == 0:
                log.info("Vistas: %s/%s fichas (%s requests)", hechas, len(cola),
                         cliente.requests_hechos)
            # reinicio preventivo del navegador para mantenerlo fresco en corridas largas
            if reiniciar_cada and hechas % reiniciar_cada == 0:
                log.info("Vistas: reinicio preventivo del navegador (%s fichas).", hechas)
                try:
                    cliente.close()
                except Exception:  # noqa: BLE001
                    pass
                cliente = Cliente(cfg)
            cliente.pausa()
    except Exception as e:  # noqa: BLE001 — crash inesperado => el .bat lo relanza
        log.exception("Vistas: error inesperado (%s). Pido relanzamiento.", e)
        rc = 5
    finally:
        if cliente is not None:
            try:
                cliente.close()
            except Exception:  # noqa: BLE001
                pass
        con.close()
        _lock_vistas_soltar()
    log.info("=== Barrido de vistas %s: %s fichas tomadas ===", fecha, hechas)
    return rc


# ------------------------------------------------------------------ compare

def cmd_compare(args):
    con = dbmod.conectar(DB_PATH)
    f1, f2 = args.fecha1, args.fecha2

    def precios(fecha):
        filas = con.execute(
            """SELECT h.aviso_id, h.moneda, h.precio FROM historial_precios h
               WHERE h.fecha = (SELECT MAX(fecha) FROM historial_precios
                                WHERE aviso_id = h.aviso_id AND fecha <= ?)""", (fecha,)).fetchall()
        return {r["aviso_id"]: (r["moneda"], r["precio"]) for r in filas}

    p1, p2 = precios(f1), precios(f2)
    act1 = {r["id"] for r in con.execute("SELECT id FROM avisos WHERE primera_vez<=? AND ultima_vez>=?", (f1, f1))}
    act2 = {r["id"] for r in con.execute("SELECT id FROM avisos WHERE primera_vez<=? AND ultima_vez>=?", (f2, f2))}

    nuevos = act2 - act1
    retirados = act1 - act2
    bajas, subas = [], []
    for aid in act1 & act2:
        m1p = p1.get(aid)
        m2p = p2.get(aid)
        if m1p and m2p and m1p[0] == m2p[0] and m1p[1] and m2p[1] and m1p[1] != m2p[1]:
            delta = 100.0 * (m2p[1] - m1p[1]) / m1p[1]
            (bajas if delta < 0 else subas).append((aid, m1p[1], m2p[1], delta))

    print("Comparación {} -> {}".format(f1, f2))
    print("  Avisos nuevos:    {}".format(len(nuevos)))
    print("  Avisos retirados: {}".format(len(retirados)))
    print("  Bajaron precio:   {}".format(len(bajas)))
    print("  Subieron precio:  {}".format(len(subas)))
    bajas.sort(key=lambda x: x[3])
    print("\nMayores bajas:")
    for aid, a, b, d in bajas[:20]:
        fila = con.execute("SELECT tipo, barrio, url FROM avisos WHERE id=?", (aid,)).fetchone()
        print("  {:>+6.1f}%  {:>12,} -> {:>12,}  {} en {}  {}".format(
            d, a, b, fila["tipo"], fila["barrio"], fila["url"]))
    con.close()
    return 0


# ------------------------------------------------------------------ main

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scrape", help="corrida completa del día")
    p.add_argument("--daily", action="store_true",
                   help="salir sin hacer nada si ya corrió hoy (para la tarea programada)")
    p.add_argument("--piloto", nargs="?", type=int, const=2, default=None, metavar="N",
                   help="modo prueba: N páginas por segmento (default 2) y NO toca la base")
    p.set_defaults(fn=cmd_scrape)

    p = sub.add_parser("enrich", help="traer descripción/amenities de fichas individuales")
    p.add_argument("--where", help="filtro SQL sobre la tabla avisos, ej: \"barrio LIKE '%%Cerro%%'\"")
    p.add_argument("--ids", help="lista de IDs separados por coma")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_enrich)

    p = sub.add_parser("vistas", help="barrido rotativo de fichas para capturar visualizaciones (autónomo)")
    p.add_argument("--ahora", action="store_true", help="ignorar la ventana horaria (para probar a mano)")
    p.add_argument("--limite", type=int, default=None, help="tope de fichas en esta corrida (para probar)")
    p.set_defaults(fn=cmd_vistas)

    p = sub.add_parser("publish", help="regenerar data.js y copiar a la red")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("compare", help="comparar dos fechas")
    p.add_argument("fecha1")
    p.add_argument("fecha2")
    p.set_defaults(fn=cmd_compare)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()

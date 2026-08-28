# -*- coding: utf-8 -*-
"""Base SQLite maestra: avisos, historial de precios y corridas."""

import json
import sqlite3
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS avisos (
    id            TEXT PRIMARY KEY,
    url           TEXT,
    operacion     TEXT,
    tipo          TEXT,
    barrio        TEXT,
    ciudad        TEXT,
    direccion     TEXT,
    m2_total      INTEGER,
    m2_cubierto   INTEGER,
    ambientes     INTEGER,
    dormitorios   INTEGER,
    banos         INTEGER,
    cocheras      INTEGER,
    imagen        TEXT,
    descripcion   TEXT,
    moneda        TEXT,
    precio        INTEGER,
    expensas      INTEGER,
    fecha_publicacion TEXT,        -- datePosted de Zonaprop (inicio de publicación)
    primera_vez   TEXT NOT NULL,   -- fecha primera aparición (primera vez que LO vimos)
    ultima_vez    TEXT NOT NULL,   -- fecha última aparición
    activo        INTEGER NOT NULL DEFAULT 1,
    -- campos del modo enriquecer
    descripcion_full TEXT,
    antiguedad    INTEGER,
    amenities     TEXT,            -- JSON array
    publicador    TEXT,
    enriquecido   TEXT             -- fecha de enriquecimiento
);
CREATE INDEX IF NOT EXISTS idx_avisos_barrio ON avisos(barrio);
CREATE INDEX IF NOT EXISTS idx_avisos_oper   ON avisos(operacion, tipo);

CREATE TABLE IF NOT EXISTS historial_precios (
    aviso_id  TEXT NOT NULL,
    fecha     TEXT NOT NULL,
    moneda    TEXT,
    precio    INTEGER,
    PRIMARY KEY (aviso_id, fecha)
);

CREATE TABLE IF NOT EXISTS corridas (
    fecha       TEXT PRIMARY KEY,
    inicio      TEXT,
    fin         TEXT,
    total       INTEGER,
    nuevos      INTEGER,
    retirados   INTEGER,
    cambios_precio INTEGER,
    detalle     TEXT              -- JSON con stats por segmento
);

CREATE TABLE IF NOT EXISTS historial_vistas (
    aviso_id             TEXT NOT NULL,
    fecha                TEXT NOT NULL,   -- fecha de la toma (YYYY-MM-DD)
    vistas_raw           INTEGER,         -- "personas en los últimos 30 días" tal cual (incluye nuestras visitas)
    nuestras_visitas_30d INTEGER,         -- visitas del scraper a este aviso en los últimos 30 días (para corregir)
    dias_publicado       INTEGER,         -- antigüedad del aviso a la fecha (para normalizar por edad)
    PRIMARY KEY (aviso_id, fecha)
);
CREATE INDEX IF NOT EXISTS idx_hv_aviso ON historial_vistas(aviso_id);

CREATE TABLE IF NOT EXISTS visitas_scraper (
    aviso_id  TEXT NOT NULL,
    ts        TEXT NOT NULL              -- timestamp ISO de cada visita del scraper (incluye reintentos)
);
CREATE INDEX IF NOT EXISTS idx_vs_aviso ON visitas_scraper(aviso_id, ts);
"""

CAMPOS_LISTADO = ["url", "operacion", "tipo", "barrio", "ciudad", "direccion",
                  "m2_total", "m2_cubierto", "ambientes", "dormitorios", "banos",
                  "cocheras", "imagen", "descripcion", "moneda", "precio", "expensas",
                  "publicador", "fecha_publicacion"]


def conectar(ruta_db):
    # timeout=30: si otra corrida (p. ej. scrape + vistas a la vez) está escribiendo,
    # esperar hasta 30s por el lock en vez de fallar con "database is locked".
    con = sqlite3.connect(str(ruta_db), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # Migraciones: columnas agregadas después de la creación original de la base.
    # (CREATE TABLE IF NOT EXISTS no agrega columnas a una tabla que ya existe.)
    for col, tipo in [("fecha_publicacion", "TEXT")]:
        try:
            con.execute("ALTER TABLE avisos ADD COLUMN {} {}".format(col, tipo))
        except sqlite3.OperationalError:
            pass  # la columna ya existe
    con.commit()
    return con


def upsert_avisos(con, avisos, fecha):
    """Inserta/actualiza avisos de una corrida. Devuelve (nuevos, cambios_precio)."""
    nuevos = 0
    cambios = 0
    cur = con.cursor()
    for a in avisos:
        fila = cur.execute("SELECT moneda, precio FROM avisos WHERE id=?", (a["id"],)).fetchone()
        if fila is None:
            nuevos += 1
            cur.execute(
                "INSERT INTO avisos (id,{},primera_vez,ultima_vez,activo) VALUES ({},?,?,1)".format(
                    ",".join(CAMPOS_LISTADO), ",".join("?" * (len(CAMPOS_LISTADO) + 1))),
                [a["id"]] + [a.get(c) for c in CAMPOS_LISTADO] + [fecha, fecha])
            cur.execute("INSERT OR REPLACE INTO historial_precios VALUES (?,?,?,?)",
                        (a["id"], fecha, a.get("moneda"), a.get("precio")))
        else:
            precio_cambio = (fila["precio"] != a.get("precio") or fila["moneda"] != a.get("moneda"))
            if precio_cambio:
                cambios += 1
                cur.execute("INSERT OR REPLACE INTO historial_precios VALUES (?,?,?,?)",
                            (a["id"], fecha, a.get("moneda"), a.get("precio")))
            sets = ",".join("{}=?".format(c) for c in CAMPOS_LISTADO)
            cur.execute("UPDATE avisos SET {} , ultima_vez=?, activo=1 WHERE id=?".format(sets),
                        [a.get(c) for c in CAMPOS_LISTADO] + [fecha, a["id"]])
    con.commit()
    return nuevos, cambios


def marcar_retirados(con, fecha):
    """Marca como inactivos los avisos que no aparecieron en la corrida de hoy."""
    cur = con.execute(
        "UPDATE avisos SET activo=0 WHERE activo=1 AND ultima_vez < ?", (fecha,))
    con.commit()
    return cur.rowcount


def registrar_corrida(con, fecha, inicio, fin, total, nuevos, retirados, cambios, detalle):
    con.execute("INSERT OR REPLACE INTO corridas VALUES (?,?,?,?,?,?,?,?)",
                (fecha, inicio, fin, total, nuevos, retirados, cambios,
                 json.dumps(detalle, ensure_ascii=False)))
    con.commit()


# --- Vistas / visualizaciones (serie temporal + corrección de contaminación) ---

def log_visita_scraper(con, aviso_id, ts):
    """Registra que el scraper abrió la ficha de un aviso en 'ts' (ISO)."""
    con.execute("INSERT INTO visitas_scraper (aviso_id, ts) VALUES (?,?)", (aviso_id, ts))
    con.commit()


def nuestras_visitas_30d(con, aviso_id, hasta_ts):
    """Cuenta las visitas del scraper a un aviso en la ventana (hasta_ts - 30 días, hasta_ts]."""
    try:
        desde = (datetime.fromisoformat(hasta_ts) - timedelta(days=30)).isoformat()
    except (ValueError, TypeError):
        desde = ""
    row = con.execute(
        "SELECT COUNT(*) AS n FROM visitas_scraper WHERE aviso_id=? AND ts>? AND ts<=?",
        (aviso_id, desde, hasta_ts)).fetchone()
    return row["n"] if row else 0


def registrar_vistas(con, aviso_id, fecha, vistas_raw, nuestras_30d, dias_publicado):
    """Guarda la toma de vistas del día (átomos crudos; la corrección se deriva al leer)."""
    con.execute(
        """INSERT OR REPLACE INTO historial_vistas
           (aviso_id, fecha, vistas_raw, nuestras_visitas_30d, dias_publicado)
           VALUES (?,?,?,?,?)""",
        (aviso_id, fecha, vistas_raw, nuestras_30d, dias_publicado))
    con.commit()


def actualizar_medidas(con, aviso_id, m2_cubierto=None, m2_total=None):
    """Completa medidas que solo trae la ficha (superficie cubierta) cuando el
    barrido de vistas visita el aviso. m2_cubierto se pisa con el valor de la
    ficha; m2_total solo se completa si faltaba (el listado ya suele traerlo)."""
    if m2_cubierto is None and m2_total is None:
        return
    con.execute(
        "UPDATE avisos SET m2_cubierto = COALESCE(?, m2_cubierto), "
        "m2_total = COALESCE(m2_total, ?) WHERE id=?",
        (m2_cubierto, m2_total, aviso_id))
    con.commit()


def avisos_pendientes_vistas(con, fecha_limite, limite=0):
    """Avisos activos sin toma de vistas desde 'fecha_limite' (o nunca), para el barrido rotativo.

    Devuelve dicts {id, url, fecha_publicacion}. Primero los que nunca se tomaron,
    después los de toma más vieja."""
    q = """
        SELECT a.id, a.url, a.fecha_publicacion
        FROM avisos a
        LEFT JOIN (SELECT aviso_id, MAX(fecha) AS ult
                   FROM historial_vistas GROUP BY aviso_id) h ON h.aviso_id = a.id
        WHERE a.activo = 1 AND (h.ult IS NULL OR h.ult < ?)
        ORDER BY (h.ult IS NULL) DESC, h.ult ASC
    """
    if limite and int(limite) > 0:
        q += " LIMIT {}".format(int(limite))
    return [dict(r) for r in con.execute(q, (fecha_limite,))]


def actualizar_enriquecido(con, aviso_id, datos, fecha):
    con.execute(
        """UPDATE avisos SET descripcion_full=?, antiguedad=?, amenities=?,
           publicador=?, enriquecido=? WHERE id=?""",
        (datos.get("descripcion_full"), datos.get("antiguedad"),
         json.dumps(datos.get("amenities"), ensure_ascii=False) if datos.get("amenities") else None,
         datos.get("publicador"), fecha, aviso_id))
    con.commit()


def datos_para_visor(con):
    """Arma la estructura que consume el visor (data.js)."""
    avisos = []
    hoy_rows = con.execute("SELECT MAX(fecha) AS f FROM corridas").fetchone()
    actualizado = hoy_rows["f"]
    # Ultima antiguedad real (dias_publicado, del "Publicado hace N dias" de la
    # ficha) capturada por el barrido de vistas, por aviso.
    ult_dp = {}
    for h in con.execute(
            "SELECT h.aviso_id AS id, h.fecha AS f, h.dias_publicado AS dp "
            "FROM historial_vistas h JOIN (SELECT aviso_id, MAX(fecha) mf "
            "FROM historial_vistas WHERE dias_publicado IS NOT NULL GROUP BY aviso_id) m "
            "ON m.aviso_id = h.aviso_id AND m.mf = h.fecha"):
        ult_dp[h["id"]] = (h["f"], h["dp"])
    for r in con.execute("SELECT * FROM avisos WHERE activo=1"):
        a = dict(r)
        a.pop("descripcion_full", None)
        hist = con.execute(
            "SELECT fecha, moneda, precio FROM historial_precios WHERE aviso_id=? ORDER BY fecha",
            (r["id"],)).fetchall()
        if len(hist) > 1:
            prev, ult = hist[-2], hist[-1]
            if prev["moneda"] == ult["moneda"] and prev["precio"] and ult["precio"]:
                a["precio_anterior"] = prev["precio"]
                a["fecha_cambio"] = ult["fecha"]
        if a.get("amenities"):
            try:
                a["amenities"] = json.loads(a["amenities"])
            except ValueError:
                a["amenities"] = None
        # antiguedad real (dias_publicado) ajustada a la fecha de la ultima corrida
        dp = ult_dp.get(r["id"])
        if dp and dp[1] is not None:
            try:
                d0 = datetime.fromisoformat(dp[0][:10])
                dH = datetime.fromisoformat(actualizado[:10])
                extra = max(0, (dH - d0).days)
            except (ValueError, TypeError):
                extra = 0
            a["dias_publicado"] = dp[1] + extra
        else:
            a["dias_publicado"] = None
        avisos.append(a)
    corridas = [dict(r) for r in con.execute(
        "SELECT fecha, total, nuevos, retirados, cambios_precio FROM corridas ORDER BY fecha")]
    return {"actualizado": hoy_rows["f"], "avisos": avisos, "corridas": corridas}

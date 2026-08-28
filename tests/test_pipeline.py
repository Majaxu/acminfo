# -*- coding: utf-8 -*-
"""Test del pipeline completo: parser -> DB -> data.js (sin red)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import parser as prs
import publish

BASE = Path(__file__).resolve().parent
html = (BASE / "fixture_listado.html").read_text(encoding="utf-8")

# --- parser de listado
assert prs.parse_total_avisos(html) == 28394, "total h1"
avisos = prs.parse_listado(html, operacion="venta")
assert len(avisos) == 3, "cantidad de tarjetas: {}".format(len(avisos))

casa = avisos[0]
assert casa["id"] == "56018750"
assert casa["moneda"] == "USD" and casa["precio"] == 250000
assert casa["m2_total"] == 470 and casa["m2_cubierto"] == 330
assert casa["ambientes"] == 10 and casa["dormitorios"] == 4
assert casa["banos"] == 3 and casa["cocheras"] == 3
assert casa["barrio"] == "El Refugio" and casa["ciudad"] == "Córdoba"
assert casa["direccion"] == "Juan de dios Correa"
assert casa["tipo"] == "Casa"
assert casa["expensas"] is None
assert casa["imagen"].startswith("https://imgar")

depto = avisos[1]
assert depto["moneda"] == "ARS" and depto["precio"] == 145000000
assert depto["expensas"] == 236000
assert depto["tipo"] == "Departamento"
assert depto["ambientes"] == 2 and depto["banos"] == 1

lote = avisos[2]
assert lote["moneda"] is None and lote["precio"] is None
assert lote["m2_total"] == 360
assert lote["tipo"] == "Terreno", lote["tipo"]  # fallback desde URL

# --- detección de challenge
assert prs.es_pagina_bloqueo('<html><head><title>Un momento…</title><script src="/cdn-cgi/challenge-platform/x.js"></script>')
assert not prs.es_pagina_bloqueo(html)

# --- DB: alta, cambio de precio, retiro
dbfile = BASE / "test.db"
dbfile.unlink(missing_ok=True)
con = dbmod.conectar(dbfile)

nuevos, cambios = dbmod.upsert_avisos(con, avisos, "2026-07-20")
assert (nuevos, cambios) == (3, 0)
ret = dbmod.marcar_retirados(con, "2026-07-20")
assert ret == 0
dbmod.registrar_corrida(con, "2026-07-20", "a", "b", 3, nuevos, ret, cambios, {})

# día 2: la casa baja de precio, el lote desaparece
avisos2 = [dict(casa, precio=230000), dict(depto)]
nuevos, cambios = dbmod.upsert_avisos(con, avisos2, "2026-07-21")
assert (nuevos, cambios) == (0, 1), (nuevos, cambios)
ret = dbmod.marcar_retirados(con, "2026-07-21")
assert ret == 1
dbmod.registrar_corrida(con, "2026-07-21", "a", "b", 2, nuevos, ret, cambios, {})

datos = dbmod.datos_para_visor(con)
assert datos["actualizado"] == "2026-07-21"
assert len(datos["avisos"]) == 2
casa_v = next(a for a in datos["avisos"] if a["id"] == "56018750")
assert casa_v["precio"] == 230000 and casa_v["precio_anterior"] == 250000
assert casa_v["primera_vez"] == "2026-07-20"
assert len(datos["corridas"]) == 2

# --- data.js
publish.generar_datajs(datos, BASE / "data.js")
txt = (BASE / "data.js").read_text(encoding="utf-8")
assert txt.startswith("window.ZONAPROP_DATA = ")
json.loads(txt[len("window.ZONAPROP_DATA = "):].rstrip().rstrip(";"))

con.close()
dbfile.unlink()
(BASE / "data.js").unlink()
print("TODOS LOS TESTS OK")

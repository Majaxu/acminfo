# -*- coding: utf-8 -*-
"""Parte diario de Zonaprop: un resumen de cómo corrió todo (scrape de precios +
barrido de vistas) para leer a la mañana.

- SIEMPRE escribe output/parte_diario.txt y output/parte_diario.html.
- Si publicar_a_red está activo en config.json, copia el .html a la carpeta de red
  (al lado del visor), así lo ves sin depender del mail.
- Si existe email_config.json y está activado, además lo manda por mail.

No maneja credenciales: el usuario pone su app-password en email_config.json.
Pensado para correr todos los días ~08:30 por el Programador de tareas. Nunca
tira error hacia afuera (si algo falla, lo dice en el parte y sale con 0), para
no generar falsos crash-loops.
"""

import json
import sqlite3
import ssl
import smtplib
import sys
import traceback
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"
LOGS = OUT / "logs"
DB_PATH = OUT / "zonaprop.db"
PARTE_TXT = OUT / "parte_diario.txt"
PARTE_HTML = OUT / "parte_diario.html"
EMAIL_CFG = BASE / "email_config.json"
PLACEHOLDER = "PONE-ACA-TU-APP-PASSWORD"


def cargar_config():
    try:
        with open(BASE / "config.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def dias_desde(fecha_str):
    try:
        d = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def fmt_int(n):
    try:
        return "{:,}".format(int(n)).replace(",", ".")
    except Exception:
        return str(n)


# ----------------------------------------------------------------- recolección

def recolectar(con):
    """Devuelve un dict con todas las métricas del parte. Cada bloque va en su
    propio try para que un dato que falte no tumbe el resto del parte."""
    d = {}
    hoy = date.today().isoformat()
    ayer = (date.today() - timedelta(days=1)).isoformat()
    d["hoy"] = hoy
    d["ayer"] = ayer

    # --- scrape de precios ---
    try:
        r = con.execute(
            "SELECT fecha, inicio, fin, total, nuevos, retirados, cambios_precio "
            "FROM corridas ORDER BY fecha DESC LIMIT 1").fetchone()
        d["ult_corrida"] = dict(r) if r else None
        d["dias_sin_scrape"] = dias_desde(r["fecha"]) if r else None
    except Exception:
        d["ult_corrida"] = None
        d["dias_sin_scrape"] = None
    try:
        d["corridas_recientes"] = [dict(x) for x in con.execute(
            "SELECT fecha, total, nuevos, retirados, cambios_precio "
            "FROM corridas ORDER BY fecha DESC LIMIT 5").fetchall()]
    except Exception:
        d["corridas_recientes"] = []

    # --- inventario ---
    try:
        d["activos"] = con.execute(
            "SELECT COUNT(*) n FROM avisos WHERE activo=1").fetchone()["n"]
    except Exception:
        d["activos"] = None

    # --- vistas / visualizaciones ---
    try:
        d["tomas_hoy"] = con.execute(
            "SELECT COUNT(*) n FROM historial_vistas WHERE fecha=?", (hoy,)).fetchone()["n"]
        d["tomas_ayer"] = con.execute(
            "SELECT COUNT(*) n FROM historial_vistas WHERE fecha=?", (ayer,)).fetchone()["n"]
    except Exception:
        d["tomas_hoy"] = d["tomas_ayer"] = None
    try:
        d["avisos_con_alguna"] = con.execute(
            "SELECT COUNT(DISTINCT aviso_id) n FROM historial_vistas").fetchone()["n"]
        d["avisos_con_serie"] = con.execute(
            "SELECT COUNT(*) n FROM (SELECT aviso_id FROM historial_vistas "
            "GROUP BY aviso_id HAVING COUNT(*)>=2)").fetchone()["n"]
    except Exception:
        d["avisos_con_alguna"] = d["avisos_con_serie"] = None
    # cobertura de los últimos 7 días (sobre activos)
    try:
        hace7 = (date.today() - timedelta(days=7)).isoformat()
        con7 = con.execute(
            "SELECT COUNT(DISTINCT h.aviso_id) n FROM historial_vistas h "
            "JOIN avisos a ON a.id=h.aviso_id AND a.activo=1 "
            "WHERE h.fecha>=?", (hace7,)).fetchone()["n"]
        d["cobertura_7d"] = con7
        d["cobertura_7d_pct"] = (100.0 * con7 / d["activos"]) if d["activos"] else None
    except Exception:
        d["cobertura_7d"] = d["cobertura_7d_pct"] = None
    # pendientes: activos sin toma nunca o con toma más vieja que la cadencia
    try:
        cad = int(cfg.get("vistas_cadencia_dias", 7))
        limite = (date.today() - timedelta(days=cad)).isoformat()
        d["pendientes"] = con.execute(
            "SELECT COUNT(*) n FROM avisos a "
            "LEFT JOIN (SELECT aviso_id, MAX(fecha) ult FROM historial_vistas "
            "           GROUP BY aviso_id) h ON h.aviso_id=a.id "
            "WHERE a.activo=1 AND (h.ult IS NULL OR h.ult < ?)",
            (limite,)).fetchone()["n"]
    except Exception:
        d["pendientes"] = None

    # --- top movimientos (provisional: neto = raw - nuestras visitas) ---
    try:
        d["movimientos"] = top_movimientos(con)
    except Exception:
        d["movimientos"] = []

    return d


def top_movimientos(con, tope=5):
    """De los avisos con ≥2 lecturas, compara las dos últimas y calcula el salto
    de vistas netas (descontando nuestras propias visitas) y el ritmo por día.
    Es un adelanto: recién con ~1 semana de datos el número se vuelve firme."""
    filas = con.execute(
        "SELECT h.aviso_id, h.fecha, h.vistas_raw, h.nuestras_visitas_30d "
        "FROM historial_vistas h "
        "JOIN (SELECT aviso_id FROM historial_vistas GROUP BY aviso_id "
        "      HAVING COUNT(*)>=2) m ON m.aviso_id=h.aviso_id "
        "ORDER BY h.aviso_id, h.fecha").fetchall()
    por_aviso = {}
    for f in filas:
        por_aviso.setdefault(f["aviso_id"], []).append(f)
    movs = []
    for aid, lecturas in por_aviso.items():
        prev, ult = lecturas[-2], lecturas[-1]
        neto_prev = (prev["vistas_raw"] or 0) - (prev["nuestras_visitas_30d"] or 0)
        neto_ult = (ult["vistas_raw"] or 0) - (ult["nuestras_visitas_30d"] or 0)
        delta = neto_ult - neto_prev
        try:
            dt = (datetime.strptime(ult["fecha"][:10], "%Y-%m-%d").date()
                  - datetime.strptime(prev["fecha"][:10], "%Y-%m-%d").date()).days
        except Exception:
            dt = 0
        ritmo = (delta / dt) if dt else 0.0
        movs.append({"aviso_id": aid, "delta": delta, "dias": dt, "ritmo": ritmo,
                     "de": neto_prev, "a": neto_ult})
    movs.sort(key=lambda m: m["delta"], reverse=True)
    top = movs[:tope]
    # enriquecer con barrio / precio para que se lea
    for m in top:
        try:
            a = con.execute(
                "SELECT barrio, tipo, operacion, moneda, precio, url "
                "FROM avisos WHERE id=?", (m["aviso_id"],)).fetchone()
            if a:
                m.update({"barrio": a["barrio"], "tipo": a["tipo"],
                          "operacion": a["operacion"], "moneda": a["moneda"],
                          "precio": a["precio"], "url": a["url"]})
        except Exception:
            pass
    return top


def salud_logs(hoy):
    """Mira el log de vistas del día para detectar crash-loop o autocuración."""
    info = {"errores_vistas": 0, "tomas_log": 0, "autocuro": False,
            "hay_log_vistas": False, "hay_log_scrape": False}
    lv = LOGS / "run_vistas_{}.log".format(hoy)
    if lv.exists():
        info["hay_log_vistas"] = True
        try:
            txt = lv.read_text(encoding="utf-8", errors="ignore")
            info["errores_vistas"] = (txt.count("error inesperado")
                                      + txt.count("Failed to connect"))
            info["tomas_log"] = txt.count("fichas tomadas")
            info["autocuro"] = ("Autocuro el perfil" in txt
                                or "apartado a" in txt
                                or "carpeta nueva" in txt)
        except Exception:
            pass
    for nombre in ("run_{}.log".format(hoy), "run_scrape_{}.log".format(hoy)):
        if (LOGS / nombre).exists():
            info["hay_log_scrape"] = True
            break
    return info


# ------------------------------------------------------------------- veredicto

def evaluar(d, logs):
    """Devuelve (estado, titular, alertas[])."""
    alertas = []
    estado = "OK"

    dss = d.get("dias_sin_scrape")
    if dss is None:
        alertas.append("No encuentro ninguna corrida de precios en la base.")
        estado = "PROBLEMA"
    elif dss >= 3:
        alertas.append("El scrape de precios no corre hace {} días.".format(dss))
        estado = "PROBLEMA"
    elif dss >= 2:
        alertas.append("El scrape de precios no corre desde hace {} días "
                       "(¿PC apagada / sin sesión?).".format(dss))
        estado = peor(estado, "ATENCIÓN")

    th = d.get("tomas_hoy") or 0
    ta = d.get("tomas_ayer") or 0
    if logs["errores_vistas"] >= 3 and (th + ta) == 0:
        alertas.append("El barrido de vistas está en crash-loop "
                       "({} errores de arranque hoy, 0 fichas).".format(logs["errores_vistas"]))
        estado = "PROBLEMA"
    elif (th + ta) == 0 and d.get("pendientes"):
        alertas.append("El barrido de vistas no tomó ninguna ficha entre ayer y hoy.")
        estado = peor(estado, "ATENCIÓN")

    if logs["autocuro"]:
        alertas.append("El navegador se recuperó solo (autocuración del perfil). "
                       "Está andando, pero conviene mirar por qué se ensució.")
        estado = peor(estado, "ATENCIÓN")

    cp = d.get("cobertura_7d_pct")
    if cp is not None and cp < 50 and d.get("avisos_con_alguna"):
        alertas.append("Cobertura de vistas de los últimos 7 días baja: "
                       "{:.0f}% de los activos.".format(cp))
        estado = peor(estado, "ATENCIÓN")

    return estado, alertas


def peor(a, b):
    orden = {"OK": 0, "ATENCIÓN": 1, "PROBLEMA": 2}
    return a if orden.get(a, 0) >= orden.get(b, 0) else b


# ------------------------------------------------------------------- redacción

def redactar_txt(d, logs, estado, alertas):
    L = []
    L.append("PARTE DIARIO ZONAPROP — {}".format(
        datetime.now().strftime("%A %d/%m/%Y %H:%M")))
    L.append("Estado general: {}".format(estado))
    L.append("=" * 56)

    if alertas:
        L.append("")
        L.append("ATENCIÓN:")
        for a in alertas:
            L.append("  - " + a)

    # Scrape
    L.append("")
    L.append("SCRAPE DE PRECIOS")
    c = d.get("ult_corrida")
    if c:
        dss = d.get("dias_sin_scrape")
        cuando = ("hoy" if dss == 0 else "ayer" if dss == 1
                  else "hace {} días".format(dss) if dss is not None else "?")
        L.append("  Última corrida: {} ({}).".format(c["fecha"], cuando))
        L.append("  Avisos activos: {}".format(fmt_int(d.get("activos"))))
        L.append("  Esa corrida: {} nuevos, {} retirados, {} cambios de precio.".format(
            fmt_int(c.get("nuevos")), fmt_int(c.get("retirados")),
            fmt_int(c.get("cambios_precio"))))
    else:
        L.append("  Sin datos de corridas todavía.")
    if len(d.get("corridas_recientes", [])) > 1:
        L.append("  Últimas corridas (fecha · total · nuevos · retirados · Δprecio):")
        for r in d["corridas_recientes"]:
            L.append("    {} · {} · +{} · -{} · {}".format(
                r["fecha"], fmt_int(r["total"]), fmt_int(r["nuevos"]),
                fmt_int(r["retirados"]), fmt_int(r["cambios_precio"])))

    # Vistas
    L.append("")
    L.append("BARRIDO DE VISTAS")
    L.append("  Fichas tomadas: {} hoy · {} ayer.".format(
        fmt_int(d.get("tomas_hoy")), fmt_int(d.get("tomas_ayer"))))
    L.append("  Avisos con al menos una lectura: {}".format(fmt_int(d.get("avisos_con_alguna"))))
    L.append("  Avisos con serie (≥2 lecturas, ya comparables): {}".format(
        fmt_int(d.get("avisos_con_serie"))))
    if d.get("cobertura_7d_pct") is not None:
        L.append("  Cobertura últimos 7 días: {} avisos ({:.0f}% de los activos).".format(
            fmt_int(d.get("cobertura_7d")), d["cobertura_7d_pct"]))
    L.append("  Pendientes (nunca vistos o vencidos por cadencia): {}".format(
        fmt_int(d.get("pendientes"))))
    if logs["errores_vistas"]:
        L.append("  Errores de arranque en el log de hoy: {}".format(logs["errores_vistas"]))

    # Movimientos
    movs = d.get("movimientos") or []
    if movs:
        L.append("")
        L.append("TOP MOVIMIENTOS DE VISTAS (provisional — netas, últimas 2 lecturas)")
        for m in movs:
            etq = "{} {} en {}".format(
                (m.get("tipo") or "").capitalize(), (m.get("operacion") or ""),
                m.get("barrio") or "?").strip()
            precio = ""
            if m.get("precio"):
                precio = " · {} {}".format(m.get("moneda") or "", fmt_int(m.get("precio")))
            L.append("    +{} en {}d ({:.1f}/día) · {}{} · id {}".format(
                m["delta"], m["dias"], m["ritmo"], etq, precio, m["aviso_id"]))
        L.append("  (Adelanto: el número se afirma con ~1 semana de datos por aviso.)")

    L.append("")
    L.append("-" * 56)
    L.append("Parte automático. Se genera solo todas las mañanas.")
    return "\n".join(L)


def redactar_html(d, logs, estado, alertas, texto):
    color = {"OK": "#1a7f37", "ATENCIÓN": "#9a6700", "PROBLEMA": "#b91c1c"}.get(estado, "#333")
    movs = d.get("movimientos") or []
    filas_mov = ""
    for m in movs:
        etq = "{} {} · {}".format((m.get("tipo") or "").capitalize(),
                                  (m.get("operacion") or ""), m.get("barrio") or "?")
        precio = "{} {}".format(m.get("moneda") or "", fmt_int(m.get("precio"))) if m.get("precio") else "—"
        url = m.get("url") or "#"
        filas_mov += (
            "<tr><td style='text-align:right;font-weight:600;color:#1a7f37'>+{delta}</td>"
            "<td style='text-align:right'>{dias}d</td>"
            "<td style='text-align:right'>{ritmo:.1f}/día</td>"
            "<td>{etq}</td><td>{precio}</td>"
            "<td><a href='{url}'>{aid}</a></td></tr>"
        ).format(delta=m["delta"], dias=m["dias"], ritmo=m["ritmo"],
                 etq=etq, precio=precio, url=url, aid=m["aviso_id"])
    tabla_mov = ""
    if filas_mov:
        tabla_mov = (
            "<h3 style='margin:18px 0 6px'>Top movimientos de vistas "
            "<span style='font-weight:400;color:#777;font-size:12px'>(provisional)</span></h3>"
            "<table style='border-collapse:collapse;width:100%;font-size:13px'>"
            "<tr style='color:#777;text-align:left'>"
            "<th style='text-align:right'>Δ netas</th><th style='text-align:right'>Lapso</th>"
            "<th style='text-align:right'>Ritmo</th><th>Aviso</th><th>Precio</th><th>id</th></tr>"
            + filas_mov + "</table>"
            "<p style='color:#999;font-size:11px;margin:4px 0 0'>El número se afirma con "
            "~1 semana de datos por aviso.</p>")

    alertas_html = ""
    if alertas:
        items = "".join("<li>{}</li>".format(a) for a in alertas)
        alertas_html = ("<div style='background:#fff8e1;border-left:4px solid #9a6700;"
                        "padding:10px 14px;margin:14px 0;border-radius:4px'>"
                        "<b>Atención</b><ul style='margin:6px 0 0'>" + items + "</ul></div>")

    c = d.get("ult_corrida") or {}
    dss = d.get("dias_sin_scrape")
    cuando = ("hoy" if dss == 0 else "ayer" if dss == 1
              else "hace {} días".format(dss) if dss is not None else "?")

    filas_corr = ""
    for r in d.get("corridas_recientes", []):
        filas_corr += (
            "<tr><td>{f}</td><td style='text-align:right'>{t}</td>"
            "<td style='text-align:right;color:#1a7f37'>+{n}</td>"
            "<td style='text-align:right;color:#b91c1c'>-{r}</td>"
            "<td style='text-align:right'>{c}</td></tr>").format(
            f=r["fecha"], t=fmt_int(r["total"]), n=fmt_int(r["nuevos"]),
            r=fmt_int(r["retirados"]), c=fmt_int(r["cambios_precio"]))

    return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#222;
max-width:720px;margin:0 auto;padding:18px;background:#fff">
  <div style="border-bottom:2px solid #eee;padding-bottom:10px">
    <span style="font-size:13px;color:#777">{fechahora}</span>
    <h2 style="margin:4px 0">Parte diario Zonaprop
      <span style="font-size:14px;background:{color};color:#fff;padding:2px 10px;
      border-radius:12px;vertical-align:middle">{estado}</span></h2>
  </div>
  {alertas}
  <h3 style="margin:18px 0 6px">Scrape de precios</h3>
  <p style="margin:0">Última corrida: <b>{cf}</b> ({cuando}) ·
     <b>{activos}</b> avisos activos.<br>
     Esa corrida: <b>{nuevos}</b> nuevos, <b>{retirados}</b> retirados,
     <b>{cambios}</b> cambios de precio.</p>
  <table style="border-collapse:collapse;width:100%;font-size:13px;margin-top:8px">
    <tr style="color:#777;text-align:left"><th>Fecha</th><th style="text-align:right">Total</th>
    <th style="text-align:right">Nuevos</th><th style="text-align:right">Retirados</th>
    <th style="text-align:right">Δprecio</th></tr>{filas_corr}
  </table>
  <h3 style="margin:18px 0 6px">Barrido de vistas</h3>
  <p style="margin:0">Fichas tomadas: <b>{th}</b> hoy · <b>{ta}</b> ayer.<br>
     Con serie (≥2 lecturas): <b>{serie}</b> · con alguna lectura: <b>{alguna}</b>.<br>
     Cobertura 7 días: <b>{cob}</b> ({cobpct}) · pendientes: <b>{pend}</b>.</p>
  {tabla_mov}
  <p style="color:#aaa;font-size:11px;margin-top:22px;border-top:1px solid #eee;padding-top:8px">
    Parte automático · se genera solo todas las mañanas.</p>
</body></html>""".format(
        fechahora=datetime.now().strftime("%A %d/%m/%Y %H:%M"),
        color=color, estado=estado, alertas=alertas_html,
        cf=c.get("fecha", "—"), cuando=cuando, activos=fmt_int(d.get("activos")),
        nuevos=fmt_int(c.get("nuevos")), retirados=fmt_int(c.get("retirados")),
        cambios=fmt_int(c.get("cambios_precio")), filas_corr=filas_corr,
        th=fmt_int(d.get("tomas_hoy")), ta=fmt_int(d.get("tomas_ayer")),
        serie=fmt_int(d.get("avisos_con_serie")), alguna=fmt_int(d.get("avisos_con_alguna")),
        cob=fmt_int(d.get("cobertura_7d")),
        cobpct=("{:.0f}%".format(d["cobertura_7d_pct"]) if d.get("cobertura_7d_pct") is not None else "—"),
        pend=fmt_int(d.get("pendientes")), tabla_mov=tabla_mov)


# --------------------------------------------------------------------- entrega

def publicar_a_red(cfg):
    if not cfg.get("publicar_a_red"):
        return None
    carpeta = cfg.get("carpeta_red")
    if not carpeta:
        return None
    try:
        import shutil
        destino = Path(carpeta) / "parte_diario.html"
        shutil.copy2(PARTE_HTML, destino)
        return str(destino)
    except Exception as e:
        print("[parte] no pude copiar a la red:", e)
        return None


def cargar_email_cfg():
    if not EMAIL_CFG.exists():
        return None
    try:
        with open(EMAIL_CFG, encoding="utf-8") as f:
            m = json.load(f)
    except Exception as e:
        print("[parte] email_config.json ilegible:", e)
        return None
    if not m.get("activar"):
        return None
    # Google muestra el app-password como "xxxx xxxx xxxx xxxx"; el login SMTP
    # quiere los 16 caracteres sin espacios. Lo limpiamos por las dudas.
    if isinstance(m.get("password"), str):
        m["password"] = m["password"].replace(" ", "").strip()
    if not m.get("password") or m.get("password") == PLACEHOLDER:
        print("[parte] falta el app-password en email_config.json; no mando mail.")
        return None
    if not m.get("smtp_host") or not m.get("para"):
        print("[parte] email_config.json incompleto (smtp_host/para); no mando mail.")
        return None
    return m


def enviar_mail(m, asunto, texto, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = m.get("de", m["usuario"])
    para = m["para"] if isinstance(m["para"], list) else [m["para"]]
    msg["To"] = ", ".join(para)
    msg.attach(MIMEText(texto, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    host = m["smtp_host"]
    port = int(m.get("smtp_port", 587))
    seg = str(m.get("seguridad", "starttls")).lower()
    if seg == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(m["usuario"], m["password"])
            s.sendmail(msg["From"], para, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            if seg == "starttls":
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            s.login(m["usuario"], m["password"])
            s.sendmail(msg["From"], para, msg.as_string())


def asunto_de(d, estado):
    th = (d.get("tomas_hoy") or 0) + (d.get("tomas_ayer") or 0)
    dss = d.get("dias_sin_scrape")
    scr = ("scrape hoy" if dss == 0 else "scrape ayer" if dss == 1
           else "scrape hace {}d".format(dss) if dss is not None else "sin scrape")
    return "Parte Zonaprop {} — {} ({}, {} vistas)".format(
        date.today().strftime("%d/%m"), estado, scr, fmt_int(th))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    global cfg
    cfg = cargar_config()
    hoy = date.today().isoformat()

    d = {}
    logs = salud_logs(hoy)
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(str(DB_PATH), timeout=30)
            con.row_factory = sqlite3.Row
            d = recolectar(con)
            con.close()
        except Exception:
            d = {"error": traceback.format_exc()}
    else:
        d = {"error": "No encuentro la base {}.".format(DB_PATH)}

    if "error" in d:
        estado, alertas = "PROBLEMA", ["No pude leer la base: " + str(d.get("error"))[:200]]
        d.setdefault("hoy", hoy)
    else:
        estado, alertas = evaluar(d, logs)

    texto = redactar_txt(d, logs, estado, alertas) if "error" not in d else \
        "PARTE DIARIO ZONAPROP — {}\nEstado: PROBLEMA\n\n{}".format(
            datetime.now().strftime("%d/%m/%Y %H:%M"), alertas[0])
    html = redactar_html(d, logs, estado, alertas, texto) if "error" not in d else \
        "<pre>{}</pre>".format(texto)

    try:
        PARTE_TXT.write_text(texto, encoding="utf-8")
        PARTE_HTML.write_text(html, encoding="utf-8")
        print("[parte] escrito:", PARTE_TXT.name, "y", PARTE_HTML.name)
    except Exception as e:
        print("[parte] no pude escribir el parte:", e)

    destino = publicar_a_red(cfg)
    if destino:
        print("[parte] copiado a la red:", destino)

    m = cargar_email_cfg()
    if m:
        try:
            enviar_mail(m, asunto_de(d, estado), texto, html)
            print("[parte] mail enviado a:", m.get("para"))
        except Exception as e:
            print("[parte] fallo al enviar el mail:", e)
    else:
        print("[parte] mail no configurado (o sin app-password): quedó el archivo/red.")

    print("\n" + texto)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(0)  # nunca crash-loop por el parte

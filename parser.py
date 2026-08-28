# -*- coding: utf-8 -*-
"""Parser de páginas de listados y fichas de Zonaprop.

Basado en la estructura real del sitio (verificada 2026-07):
- Tarjetas: div[data-qa="posting PROPERTY"] con data-id y data-to-posting
- Precio: [data-qa="POSTING_CARD_PRICE"]  ->  "USD 250.000" | "$ 350.000" | "Consultar precio"
- Expensas: [data-qa="expensas"]          ->  "$ 236.000 Expensas"
- Features: [data-qa="POSTING_CARD_FEATURES"] -> "470 m² tot.330 m² cub.10 amb.4 dorm.3 baños3 coch."
- Ubicación: [data-qa="POSTING_CARD_LOCATION"] -> "Barrio, Ciudad"
- Dirección: h4/div con clase *location-address*
- Cada tarjeta incluye un <script type="application/ld+json"> con @type y name ("Casa · 330m² · ...")
"""

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

# Mapeo de @type de schema.org a tipo de propiedad en castellano (fallback)
LD_TYPE_MAP = {
    "Apartment": "Departamento",
    "House": "Casa",
    "SingleFamilyResidence": "Casa",
    "Land": "Terreno",
    "Store": "Local comercial",
    "Office": "Oficina",
    "ParkingFacility": "Cochera",
    "Warehouse": "Depósito",
    "Hotel": "Hotel",
    "Residence": "Propiedad",
}

RE_NUM = re.compile(r"[\d.]+")


def _to_int(txt):
    """'250.000' -> 250000 ; '1.200' -> 1200 ; None si no hay número."""
    if not txt:
        return None
    m = RE_NUM.search(txt.replace(" ", " "))
    if not m:
        return None
    try:
        return int(m.group(0).replace(".", ""))
    except ValueError:
        return None


def _clean(txt):
    return re.sub(r"\s+", " ", txt or "").strip()


def parse_precio(texto):
    """Devuelve (moneda, monto). 'USD 250.000' -> ('USD', 250000);
    '$ 350.000' -> ('ARS', 350000); 'Consultar precio' -> (None, None)."""
    t = _clean(texto)
    if not t or "consultar" in t.lower():
        return None, None
    moneda = None
    if "USD" in t.upper() or "U$S" in t.upper():
        moneda = "USD"
    elif "$" in t:
        moneda = "ARS"
    monto = _to_int(t)
    if monto is None:
        return None, None
    return moneda, monto


def parse_features(texto):
    """Extrae métricas del texto de features de la tarjeta o ficha."""
    t = _clean(texto)
    out = {"m2_total": None, "m2_cubierto": None, "ambientes": None,
           "dormitorios": None, "banos": None, "cocheras": None}
    if not t:
        return out
    m = re.search(r"([\d.]+)\s*m²\s*tot", t)
    if m:
        out["m2_total"] = _to_int(m.group(1))
    m = re.search(r"([\d.]+)\s*m²\s*cub", t)
    if m:
        out["m2_cubierto"] = _to_int(m.group(1))
    # si solo dice "70 m²" sin tot/cub, tomarlo como total
    if out["m2_total"] is None and out["m2_cubierto"] is None:
        m = re.search(r"([\d.]+)\s*m²", t)
        if m:
            out["m2_total"] = _to_int(m.group(1))
    m = re.search(r"(\d+)\s*amb", t)
    if m:
        out["ambientes"] = int(m.group(1))
    if re.search(r"monoamb", t, re.I):
        out["ambientes"] = out["ambientes"] or 1
    m = re.search(r"(\d+)\s*dorm", t)
    if m:
        out["dormitorios"] = int(m.group(1))
    m = re.search(r"(\d+)\s*bañ", t)
    if m:
        out["banos"] = int(m.group(1))
    m = re.search(r"(\d+)\s*coch", t)
    if m:
        out["cocheras"] = int(m.group(1))
    return out


def parse_ubicacion(texto):
    """'El Refugio, Córdoba' -> (barrio='El Refugio', ciudad='Córdoba')."""
    t = _clean(texto)
    if not t:
        return None, None
    partes = [p.strip() for p in t.split(",") if p.strip()]
    if len(partes) == 1:
        return partes[0], None
    return ", ".join(partes[:-1]), partes[-1]


def parse_total_avisos(html_o_soup):
    """Extrae el total de avisos del <h1> ('28.394 Propiedades e inmuebles...')."""
    soup = html_o_soup if isinstance(html_o_soup, BeautifulSoup) else BeautifulSoup(html_o_soup, "lxml")
    h1 = soup.find("h1")
    if not h1:
        return None
    return _to_int(h1.get_text())


def es_pagina_bloqueo(html):
    """Detecta el challenge de Cloudflare."""
    if not html:
        return True
    low = html[:4000].lower()
    return ("un momento" in low and "cf-" in low) or "challenge-platform" in low \
        or "just a moment" in low or "cf-chl" in low


RE_LOGO_PUB = re.compile(r'/empresas/.+/logo_(.+?)_\d+(?:_\d+)?\.\w+$')


def _publicador_de_logo(src):
    """Nombre de la inmobiliaria a partir de la URL del logo del publicador.

    Ej: '.../empresas/.../logo_grupo-forte_1652125387581.jpg' -> 'Grupo Forte'.
    Si la tarjeta no tiene logo, el aviso es de un PARTICULAR (publicador=None)."""
    if not src:
        return None
    m = RE_LOGO_PUB.search(src)
    if not m:
        m = re.search(r'/logo_(.+?)\.\w+$', src)
    if not m:
        return None
    return m.group(1).replace("-", " ").strip().title() or None


# Best-effort: si no hay logo, deducir la inmobiliaria del arranque de la
# descripción. ALTA PRECISIÓN a propósito: solo devuelve nombre cuando hay un
# término inequívoco de inmobiliaria al principio; si no, None (probable
# particular). Preferimos dejar alguna inmobiliaria en rojo antes que inventar
# agencias falsas.
RE_VENTA_VERBO = re.compile(
    r'\b(ofrec\w+|presenta\w*|vende\w*|comercializa\w*|te\s+acerca|le\s+acerca|'
    r'pone\s+(?:a|en)\s+(?:la\s+)?venta|dispone\w*|promociona\w*|'
    r'tiene\s+el\s+agrado|te\s+ofrece)\b', re.I)
RE_AGENCIA = re.compile(
    r'(inmobiliaria|propiedades|bienes\s+ra[ií]ces|(?:&|y)\s+asociados|'
    r'negocios\s+inmob\w*|gesti[oó]n\s+inmob\w*|servicios\s+inmob\w*|'
    r'desarrollos\s+inmob\w*|grupo\s+inmob\w*|realty|real\s+estate)', re.I)


def _publicador_de_descripcion(desc):
    """Nombre de inmobiliaria deducido del inicio de la descripción, o None.

    Ej: 'Musitano & Asociados Inmobiliaria ofrece…' -> 'Musitano & Asociados
    Inmobiliaria'. 'Alquilo depto amoblado…' -> None (particular)."""
    if not desc:
        return None
    ini = desc.strip()[:90]
    m = RE_VENTA_VERBO.search(ini)
    cand = (ini[:m.start()] if m else ini).strip(" .,:;-—|·\t")
    cand = re.sub(r'^(el\s+equipo\s+de\s+|la\s+firma\s+|desde\s+|somos\s+)', "",
                  cand, flags=re.I).strip()
    if not RE_AGENCIA.search(cand):
        return None                       # sin señal de inmobiliaria
    if not (1 < len(cand.split()) <= 7) or len(cand) > 55:
        return None                       # muy corto/largo: poco confiable
    if not re.match(r'^[A-ZÁÉÍÓÚÑ0-9]', cand):
        return None                       # no arranca como nombre propio
    return cand


def _parse_fecha_posted(s):
    """'7/22/26' (M/D/AA de Zonaprop) -> '2026-07-22'."""
    if not s:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _fechas_publicacion(soup):
    """Mapa {id_aviso: fecha_publicacion_iso} desde el JSON-LD de la página.

    La fecha de publicación (datePosted) no está en la tarjeta sino en un
    <script ld+json> de página (@type RealEstateListing -> mainEntity), con la
    url de cada aviso. Mapeamos por el id que va al final de la url."""
    mapa = {}
    for s in soup.find_all("script", type="application/ld+json"):
        t = s.string or ""
        if "datePosted" not in t:
            continue
        try:
            d = json.loads(t)
        except (ValueError, TypeError):
            continue
        items = d.get("mainEntity") if isinstance(d, dict) else None
        if not isinstance(items, list):
            continue
        for it in items:
            obj = it.get("item") if isinstance(it, dict) and "item" in it else it
            if not isinstance(obj, dict):
                continue
            m = re.search(r'-(\d+)\.html', obj.get("url", "") or "")
            fecha = _parse_fecha_posted(obj.get("datePosted"))
            if m and fecha:
                mapa[m.group(1)] = fecha
    return mapa


def parse_listado(html, operacion=None):
    """Parsea una página de listados. Devuelve lista de dicts (un aviso por tarjeta)."""
    soup = BeautifulSoup(html, "lxml")
    fechas_pub = _fechas_publicacion(soup)
    avisos = []
    for card in soup.select('[data-qa="posting PROPERTY"]'):
        aviso = {"operacion": operacion}
        aviso["id"] = card.get("data-id")
        url = card.get("data-to-posting") or ""
        if not url:
            a = card.find("a", href=True)
            url = a["href"] if a else ""
        aviso["url"] = url.split("?")[0]

        el = card.select_one('[data-qa="POSTING_CARD_PRICE"]')
        aviso["moneda"], aviso["precio"] = parse_precio(el.get_text() if el else "")

        el = card.select_one('[data-qa="expensas"]')
        aviso["expensas"] = _to_int(el.get_text()) if el else None

        el = card.select_one('[data-qa="POSTING_CARD_FEATURES"]')
        aviso.update(parse_features(el.get_text() if el else ""))

        el = card.select_one('[data-qa="POSTING_CARD_LOCATION"]')
        aviso["barrio"], aviso["ciudad"] = parse_ubicacion(el.get_text() if el else "")

        el = card.select_one('[class*="location-address"]')
        aviso["direccion"] = _clean(el.get_text()) if el else None

        el = card.select_one('[data-qa="POSTING_CARD_DESCRIPTION"]')
        aviso["descripcion"] = _clean(el.get_text()) if el else None

        # JSON-LD embebido en la tarjeta: tipo de propiedad e imagen
        aviso["tipo"] = None
        aviso["imagen"] = None
        ld_tag = card.find("script", type="application/ld+json")
        if ld_tag:
            try:
                ld = json.loads(ld_tag.string or "{}")
                nombre = ld.get("name") or ""
                if "·" in nombre:
                    aviso["tipo"] = nombre.split("·")[0].strip() or None
                if not aviso["tipo"]:
                    aviso["tipo"] = LD_TYPE_MAP.get(ld.get("@type"))
                img = ld.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                aviso["imagen"] = img
            except (ValueError, TypeError):
                pass
        if not aviso["tipo"]:
            aviso["tipo"] = _tipo_desde_url(aviso["url"])

        # Publicador: 1) el logo de la inmobiliaria (img data-qa=POSTING_CARD_PUBLISHER);
        # 2) si no hay logo, best-effort desde el inicio de la descripción; 3) si
        # tampoco, queda None => particular (rojo en el visor).
        pub_img = card.select_one('img[data-qa="POSTING_CARD_PUBLISHER"]')
        aviso["publicador"] = (_publicador_de_logo(pub_img.get("src"))
                               if pub_img and pub_img.get("src") else None)
        if not aviso["publicador"]:
            aviso["publicador"] = _publicador_de_descripcion(aviso.get("descripcion"))

        # fecha de inicio de publicación (datePosted del JSON-LD de página)
        aviso["fecha_publicacion"] = fechas_pub.get(aviso["id"])

        if aviso["id"]:
            avisos.append(aviso)
    return avisos


def _tipo_desde_url(url):
    """Fallback: deducir tipo desde la URL del aviso."""
    u = (url or "").lower()
    for pat, tipo in [("departamento", "Departamento"), ("casa", "Casa"),
                      ("ph-", "PH"), ("terreno", "Terreno"), ("lote", "Terreno"),
                      ("local", "Local comercial"), ("oficina", "Oficina"),
                      ("cochera", "Cochera"), ("deposito", "Depósito"),
                      ("galpon", "Depósito")]:
        if pat in u:
            return tipo
    return None


def parse_ficha(html):
    """Parsea una ficha individual (modo enriquecer).

    Estructura verificada: #longDescription, #section-icon-features-property,
    #reactGeneralFeatures, #reactPublisherData / #react-publisher-card.
    """
    soup = BeautifulSoup(html, "lxml")
    out = {}

    el = soup.select_one("#longDescription")
    out["descripcion_full"] = _clean(el.get_text(" ")) if el else None

    # features con ícono: incluye antigüedad ("25 años" / "A estrenar")
    icon_txts = [_clean(li.get_text()) for li in
                 soup.select("#section-icon-features-property li")]
    if not icon_txts:
        el = soup.select_one("#section-icon-features-property")
        icon_txts = [_clean(el.get_text(" "))] if el else []
    out.update({k: v for k, v in parse_features(" ".join(icon_txts)).items() if v is not None})
    out["antiguedad"] = None
    for t in icon_txts:
        m = re.search(r"(\d+)\s*años", t)
        if m and "m²" not in t:
            out["antiguedad"] = int(m.group(1))
        elif re.search(r"estrenar", t, re.I):
            out["antiguedad"] = 0

    # amenities / características generales
    amenities = []
    for el in soup.select("#reactGeneralFeatures span, #reactGeneralFeatures li"):
        t = _clean(el.get_text())
        if t and len(t) < 45 and t.lower() not in ("características generales",
                                                   "ambientes", "características", "servicios"):
            amenities.append(t)
    out["amenities"] = sorted(set(amenities)) or None

    el = soup.select_one("#reactPublisherData h2, #react-publisher-card h2, "
                         "#reactPublisherData h3, #react-publisher-card h3")
    if el:
        out["publicador"] = _clean(el.get_text())
    else:
        el = soup.select_one("#reactPublisherData, #react-publisher-card")
        txt = _clean(el.get_text(" ")) if el else ""
        out["publicador"] = re.sub(r"\d+", "", txt.split("Ver tel")[0]).strip() or None if txt else None

    # Visualizaciones — número del módulo userViews de la ficha: "54 visualizaciones"
    # (tooltip: "N personas vieron este aviso en los últimos 30 días"). Lo pinta el JS
    # del cliente, así que requiere la ficha RENDERIZADA. Apuntamos primero al elemento
    # específico; el fallback saca <script>/<style> para no capturar el diccionario i18n.
    out["visualizaciones"] = None
    mods = soup.select('[class*="post-antiquity-views"], [class*="userViews"]')
    textos = [_clean(el.get_text(" ")) for el in mods]
    if not textos:
        for tag in soup(["script", "style", "noscript"]):
            tag.extract()
        textos = [soup.get_text(" ")]
    for t in textos:
        m = (re.search(r"([\d.]+)\s*visualizaciones", t, re.I)
             or re.search(r"([\d.]+)\s*personas?\s+vieron", t, re.I))
        if m:
            out["visualizaciones"] = _to_int(m.group(1))
            break

    # Antigüedad de la PUBLICACIÓN (no del inmueble): "Publicado hace 228 días".
    # Sale del mismo módulo userViews de la ficha; sirve para normalizar las vistas
    # por edad del aviso. Lo capturamos acá porque es un dato que cambia con el tiempo.
    out["dias_publicado"] = None
    tpub = " ".join(textos) if textos else soup.get_text(" ")
    mp = re.search(r"publicad\w*\s+(hoy|ayer|hace\s+(?:m[áa]s\s+de\s+)?(\d+|un[oa]?)\s*"
                   r"(d[ií]a|hora|hs|semana|mes|añ?o)s?)", tpub, re.I)
    if mp:
        cab = mp.group(1).lower()
        if cab.startswith("hoy"):
            out["dias_publicado"] = 0
        elif cab.startswith("ayer"):
            out["dias_publicado"] = 1
        else:
            g2 = (mp.group(2) or "").lower()
            n = 1 if g2.startswith("un") else int(g2)
            u = mp.group(3).lower()
            key = "s" if u.startswith("sem") else u[0]   # d/h/s(em)/m(es)/a(ño)
            out["dias_publicado"] = n * {"h": 0, "d": 1, "s": 7, "m": 30, "a": 365}[key]

    return out

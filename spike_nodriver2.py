# -*- coding: utf-8 -*-
"""SPIKE 2: probar la idea de scrapear en TANDAS.

Cloudflare da un clearance que rinde ~9 paginas y en la 10 escala a un managed
challenge interactivo. Hipotesis: si ANTES de llegar al muro volvemos a pasar
por la home (que da un token nuevo "auto", sin tilde), se resetea el contador y
podemos seguir. Este spike refresca el clearance cada CHUNK paginas y reporta
hasta donde llega.

NO toca la base. Uso:
    venv\\Scripts\\python spike_nodriver2.py
"""
import asyncio
from pathlib import Path

import nodriver as uc
import parser as prs

BASE = "https://www.zonaprop.com.ar"
SLUG = "inmuebles-venta-cordoba-cb"
HASTA = 25            # cuantas paginas intentar en total
CHUNK = 8             # refrescar el clearance (home) cada CHUNK paginas
PAUSA = 5             # seg entre paginas
ESPERA = 60          # seg esperando tarjetas antes de dar la pagina por bloqueada
PROFILE = str((Path(__file__).resolve().parent / "output" / "nodriver_profile"))


def url_pagina(p):
    if p <= 1:
        return "{}/{}.html".format(BASE, SLUG)
    return "{}/{}-pagina-{}.html".format(BASE, SLUG, p)


async def _contenido_ok(tab, espera):
    """Espera a que cargue contenido real. Devuelve (ok, hubo_challenge)."""
    challenge = False
    for _ in range(max(1, espera // 2)):
        await asyncio.sleep(2)
        try:
            html = await tab.get_content()
        except Exception:  # noqa: BLE001
            continue
        if not prs.es_pagina_bloqueo(html):
            if html.count('data-qa="posting PROPERTY"') > 0:
                return True, challenge   # pagina de listado con tarjetas
            if "<h1" in html.lower():
                return True, challenge   # home u otra pagina valida sin tarjetas
        else:
            challenge = True
    return False, challenge


async def refrescar_clearance(browser):
    """Vuelve a pasar por la home para renovar el token de Cloudflare."""
    tab = await browser.get(BASE)
    await asyncio.sleep(6)
    ok, _ = await _contenido_ok(tab, espera=30)
    return ok


async def main():
    print("Lanzando Chrome con nodriver (perfil propio)...")
    browser = await uc.start(headless=False, user_data_dir=PROFILE)
    print("Clearance inicial via home:", "OK" if await refrescar_clearance(browser) else "FALLO")

    pasadas = 0
    for p in range(1, HASTA + 1):
        # refresco preventivo antes de agotar el presupuesto de ~9 paginas
        if p > 1 and (p - 1) % CHUNK == 0:
            print("  ...refrescando clearance (home) antes de la pagina", p)
            await refrescar_clearance(browser)

        tab = await browser.get(url_pagina(p))
        ok, ch = await _contenido_ok(tab, ESPERA)
        if not ok:
            print("pagina {:>2}: {} -> refresco clearance y reintento".format(
                p, "challenge interactivo" if ch else "sin tarjetas"))
            await refrescar_clearance(browser)
            tab = await browser.get(url_pagina(p))
            ok, ch = await _contenido_ok(tab, ESPERA)

        if not ok:
            print("pagina {:>2}: BLOQUEADA aun tras refrescar el clearance.".format(p))
            print("\n>>> La idea de tandas NO alcanza: el muro persiste. Toca API.")
            break

        tarjetas = (await tab.get_content()).count('data-qa="posting PROPERTY"')
        print("pagina {:>2}: OK   ({} tarjetas)".format(p, tarjetas))
        pasadas += 1
        await asyncio.sleep(PAUSA)

    print("\n=== {} de {} paginas OK ===".format(pasadas, HASTA))
    if pasadas >= HASTA:
        print(">>> FUNCIONA: refrescando el clearance en tandas se cruza la pagina 10.")
        print(">>> Se puede construir el scraper completo con esta tecnica (gratis).")
    try:
        browser.stop()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    uc.loop().run_until_complete(main())

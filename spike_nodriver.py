# -*- coding: utf-8 -*-
"""SPIKE de diagnóstico: ¿nodriver pasa el managed challenge de Zonaprop donde
patchright loopea?

Baja las páginas 1..N de venta, de a una con pausas, y reporta hasta cuál pasa.
NO toca la base ni publica nada. Es una prueba puntual para decidir el motor.

Instalar y correr (una sola vez):
    venv\\Scripts\\python -m pip install nodriver
    venv\\Scripts\\python spike_nodriver.py

Abre una ventana de Chrome que se mueve sola. Si en algún momento aparece el
tilde "no soy un robot", resolvelo a mano UNA vez: el script espera hasta 90s
por página a que aparezcan las tarjetas.
"""
import asyncio
from pathlib import Path

import nodriver as uc
import parser as prs

BASE = "https://www.zonaprop.com.ar"
SLUG = "inmuebles-venta-cordoba-cb"
HASTA = 20                      # cuántas páginas seguidas intentar
PAUSA = 5                       # segundos entre páginas
ESPERA_POR_PAGINA = 90          # segundos máx. esperando tarjetas/challenge
PROFILE = str((Path(__file__).resolve().parent / "output" / "nodriver_profile"))


def url_pagina(p):
    if p <= 1:
        return "{}/{}.html".format(BASE, SLUG)
    return "{}/{}-pagina-{}.html".format(BASE, SLUG, p)


async def main():
    print("Lanzando Chrome con nodriver (ventana visible, perfil propio)...")
    browser = await uc.start(headless=False, user_data_dir=PROFILE)

    # calentamiento en la home (obtener clearance)
    tab = await browser.get(BASE)
    await asyncio.sleep(8)

    pasadas = 0
    for p in range(1, HASTA + 1):
        tab = await browser.get(url_pagina(p))
        cargo = False
        avisado = False
        vueltas = max(1, ESPERA_POR_PAGINA // 2)
        for _ in range(vueltas):
            await asyncio.sleep(2)
            try:
                html = await tab.get_content()
            except Exception:  # noqa: BLE001
                continue
            if not prs.es_pagina_bloqueo(html):
                tarjetas = html.count('data-qa="posting PROPERTY"')
                if tarjetas > 0:
                    print("pagina {:>2}: OK   ({} tarjetas)".format(p, tarjetas))
                    cargo = True
                    break
            elif not avisado:
                print("pagina {:>2}: challenge de Cloudflare... esperando "
                      "(resolve el tilde en la ventana si aparece)".format(p))
                avisado = True
        if not cargo:
            print("pagina {:>2}: BLOQUEADA (challenge no resuelto a tiempo)".format(p))
            print("\n>>> nodriver TAMPOCO pasa el muro. La ruta gratis esta agotada "
                  "para el snapshot completo: toca API.")
            break
        pasadas += 1
        await asyncio.sleep(PAUSA)

    print("\n=== Resultado: {} paginas seguidas sin bloqueo ===".format(pasadas))
    if pasadas >= HASTA:
        print(">>> nodriver CRUZO la pagina 10 y siguio. Vale la pena migrar el "
              "motor a nodriver.")
    try:
        browser.stop()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    uc.loop().run_until_complete(main())

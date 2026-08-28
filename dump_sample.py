# -*- coding: utf-8 -*-
"""Baja UNA pagina de listado y guarda el HTML crudo para inspeccionar la
estructura de las tarjetas (quien publica el aviso: inmobiliaria o particular).

Uso puntual, NO toca la base ni publica nada:

    venv\\Scripts\\python dump_sample.py

Deja el archivo en  output\\sample_listado.html
"""
import logging
import sys

import zonaprop as z


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = z.cargar_config()
    seg = cfg["segmentos"][0]  # inmuebles-venta-cordoba-cb
    url = z.url_pagina(cfg["base_url"], seg["slug"], 1)
    print("Bajando pagina de muestra:", url)
    cli = z.Cliente(cfg)
    try:
        html = cli.get(url)
    finally:
        cli.close()
    if not html:
        print("No se pudo bajar la pagina (revisa el navegador / challenge).")
        return 1
    dest = z.OUT / "sample_listado.html"
    dest.write_text(html, encoding="utf-8")
    print("Guardado: {}  ({:,} bytes)".format(dest, len(html)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

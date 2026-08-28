# -*- coding: utf-8 -*-
"""Generación de data.js y publicación atómica a la carpeta de red."""

import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger("zonaprop")


def generar_datajs(datos, destino):
    """Escribe data.js (window.ZONAPROP_DATA = {...}) de forma atómica."""
    destino = Path(destino)
    tmp = destino.with_suffix(".js.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.ZONAPROP_DATA = ")
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    tmp.replace(destino)
    log.info("data.js generado: %s (%.1f MB)", destino, destino.stat().st_size / 1e6)


def publicar_a_red(carpeta_local, carpeta_red, archivos):
    """Copia archivos a la carpeta de red con escritura atómica (tmp + rename).

    Los visores abiertos en otras máquinas nunca ven archivos a medio copiar.
    """
    red = Path(carpeta_red)
    try:
        red.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error("No se pudo acceder a la carpeta de red %s: %s", red, e)
        return False
    ok = True
    for nombre in archivos:
        origen = Path(carpeta_local) / nombre
        if not origen.exists():
            log.warning("No existe %s, se omite", origen)
            continue
        destino = red / nombre
        tmp = red / (nombre + ".tmp")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, tmp)
            tmp.replace(destino)
            log.info("Publicado en red: %s", destino)
        except OSError as e:
            log.error("Error copiando %s a la red: %s", nombre, e)
            ok = False
    return ok

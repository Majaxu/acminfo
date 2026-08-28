# -*- coding: utf-8 -*-
"""Servidor local del visor acminfo.

Sirve SOLO el visor (viewer.html) + data.js desde una carpeta limpia, para
verlo desde otra PC o el celular por la LAN o por Tailscale. NO expone la base
ni los logs. Refresca data.js cada pocos minutos a medida que el scraper lo
regenera. Sin dependencias: solo la stdlib de Python."""

import http.server
import os
import shutil
import socket
import socketserver
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"
WEB = OUT / "web_visor"          # carpeta servida (solo index.html + data.js)
PUERTO = int(os.environ.get("VISOR_PUERTO", "8899"))
REFRESCO_SEG = 300               # re-copia si viewer/data cambiaron


def sincronizar():
    WEB.mkdir(parents=True, exist_ok=True)
    for src, dst in [(OUT / "viewer.html", WEB / "index.html"),
                     (OUT / "data.js", WEB / "data.js")]:
        try:
            if src.exists() and (not dst.exists()
                                 or src.stat().st_mtime > dst.stat().st_mtime):
                shutil.copy2(src, dst)
        except Exception as e:
            print("[visor] no pude actualizar", dst.name, ":", e)


def refrescador():
    while True:
        time.sleep(REFRESCO_SEG)
        sincronizar()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def log_message(self, *a):
        pass


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def ip_lan():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    sincronizar()
    threading.Thread(target=refrescador, daemon=True).start()
    with Servidor(("0.0.0.0", PUERTO), Handler) as httpd:
        print("== Visor acminfo - sirviendo ==")
        print("   Esta PC:   http://localhost:%d/" % PUERTO)
        print("   En la LAN: http://%s:%d/" % (ip_lan(), PUERTO))
        print("   Tailscale: http://<IP-tailscale-de-esta-PC>:%d/" % PUERTO)
        print("   (solo el visor + data.js; la base NO se expone)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[visor] cortado a mano.")


if __name__ == "__main__":
    main()

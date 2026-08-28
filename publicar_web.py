# -*- coding: utf-8 -*-
"""Publica el visor CIFRADO en GitHub Pages (rama gh-pages), sin exponer la data.

- Cifra el JSON de output/data.js con la clave de web_config.json (AES-GCM).
- Genera index.html desde viewer.html cambiando SOLO el cargador por uno que
  pide la clave y descifra en el navegador (el resto del visor queda igual).
- Empuja index.html + data.enc a gh-pages con force-push (ghp-import), asi el
  repo no se infla con el historico del data.js de 27 MB.

Se corre solo despues de cada scrape (tarea ZonapropWeb) o a mano."""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import encriptar  # modulo local

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"
DATA_JS = OUT / "data.js"
VIEWER = BASE / "viewer.html"
WEB = OUT / "web_publish"
CFG = BASE / "web_config.json"
PLACEHOLDER = "PONE-ACA-UNA-CLAVE-LARGA"

LOADER_RE = re.compile(
    r'\(function \(\)\s*\{\s*var rutas = \["data\.js".*?siguiente\(\);\s*\}\)\(\);',
    re.S)

DECRYPT_LOADER = r'''(function () {
  function b64d(s){var b=atob(s),a=new Uint8Array(b.length);for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a;}
  function fallo(m){var s=document.getElementById("subtitle");if(s)s.textContent=m;}
  async function cargar(){
    var resp;
    try{ resp=await fetch("data.enc",{cache:"no-store"}); }
    catch(e){ fallo("No pude bajar los datos (data.enc)."); return; }
    if(!resp.ok){ fallo("No encontre data.enc en el sitio."); return; }
    var pack=await resp.json();
    for(var intento=0;intento<3;intento++){
      var clave=prompt(intento? "Clave incorrecta. Reintenta:" : "Clave del visor:");
      if(clave===null){ fallo("Necesitas la clave para ver los datos. Recarga para reintentar."); return; }
      try{
        var km=await crypto.subtle.importKey("raw",new TextEncoder().encode(clave),{name:"PBKDF2"},false,["deriveKey"]);
        var key=await crypto.subtle.deriveKey({name:"PBKDF2",salt:b64d(pack.salt),iterations:pack.iter||250000,hash:"SHA-256"},km,{name:"AES-GCM",length:256},false,["decrypt"]);
        var pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:b64d(pack.iv)},key,b64d(pack.ct));
        window.ZONAPROP_DATA=JSON.parse(new TextDecoder().decode(pt));
        arrancar(); return;
      }catch(e){}
    }
    fallo("Clave incorrecta. Recarga la pagina para reintentar.");
  }
  if(!window.crypto||!window.crypto.subtle){ fallo("Este navegador no soporta el descifrado (WebCrypto - abri el sitio por https)."); }
  else{ cargar(); }
})();'''


def cargar_cfg():
    if not CFG.exists():
        print("[web] falta web_config.json (copia web_config.example.json).")
        return None
    try:
        m = json.load(open(CFG, encoding="utf-8"))
    except Exception as e:
        print("[web] web_config.json ilegible:", e)
        return None
    clave = m.get("clave") or ""
    if not clave or clave == PLACEHOLDER:
        print("[web] pone una clave en web_config.json.")
        return None
    if len(clave) < 8:
        print("[web] la clave es muy corta (minimo 8, mejor 12+).")
        return None
    return m


def extraer_json(texto):
    a = texto.index("{")
    b = texto.rindex("}")
    return texto[a:b + 1]


def main():
    m = cargar_cfg()
    if not m:
        return 1
    if not DATA_JS.exists():
        print("[web] no existe output/data.js - corre el scraper/publish primero.")
        return 1
    if not VIEWER.exists():
        print("[web] no existe viewer.html.")
        return 1

    # 1) cifrar el payload
    payload = extraer_json(DATA_JS.read_text(encoding="utf-8"))
    json.loads(payload)  # validacion: debe ser JSON valido
    pack = encriptar.cifrar(payload, m["clave"])

    # 2) index.html con el cargador de descifrado
    html = VIEWER.read_text(encoding="utf-8")
    html, n = LOADER_RE.subn(DECRYPT_LOADER, html)
    if n != 1:
        print("[web] no ubique el cargador en viewer.html (encontre %d). Aborto." % n)
        return 2

    # 3) armar la carpeta del sitio (solo index.html + data.enc)
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "index.html").write_text(html, encoding="utf-8")
    (WEB / "data.enc").write_text(json.dumps(pack), encoding="utf-8")
    (WEB / ".nojekyll").write_text("", encoding="utf-8")
    print("[web] sitio armado | data.enc:", len(json.dumps(pack)), "bytes")

    # 4) push a gh-pages con force (sin historico) via ghp-import
    repo_dir = m.get("repo_dir") or str(BASE)
    rama = m.get("rama") or "gh-pages"
    msg = "publish " + datetime.now().strftime("%Y-%m-%d %H:%M")
    cmd = [sys.executable, "-m", "ghp_import", "-n", "-f", "-p",
           "-b", rama, "-m", msg, str(WEB)]
    print("[web] publicando a %s en %s ..." % (rama, repo_dir))
    r = subprocess.run(cmd, cwd=repo_dir)
    if r.returncode != 0:
        print("[web] ghp-import fallo (rc=%d). Revisa el remoto 'origin' y "
              "que el token de GitHub este guardado." % r.returncode)
        return r.returncode
    url = m.get("pages_url")
    print("[web] publicado OK." + (" -> " + url if url else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

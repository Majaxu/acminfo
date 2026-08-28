# acminfo - visor online cifrado (GitHub Pages)

El visor se publica en GitHub Pages con el data.js CIFRADO: entras a una URL,
te pide una clave y descifra EN TU NAVEGADOR. Para cualquiera sin la clave es un
blob ilegible. Esquema elegido: UN repo publico `acminfo` (codigo + sitio cifrado).

## Una sola vez

1) Instalar las librerias:
       venv\Scripts\pip install cryptography ghp-import

2) Elegir la clave del visor:
   - Copia `web_config.example.json` a `web_config.json`.
   - En "clave" pone una contrasena larga (12+ caracteres). Es la que vas a tipear
     en el visor para descifrar.
   - En "pages_url" pone https://TU-USUARIO.github.io/acminfo/ (solo informativo).
   - `web_config.json` esta en .gitignore: NO se sube.

3) Crear el repo PUBLICO y subir el codigo:
       cd C:\pythonapps\Scrapers\zonaprop
       git init
       git add .
       git status      (verifica que NO esten venv/ output/ email_config.json web_config.json)
       git commit -m "acminfo: scraper + vistas + parte + visor web"
       git branch -M main
   Con gh CLI:
       gh repo create acminfo --public --source . --remote origin --push
   Sin gh: crea en github.com un repo PUBLICO "acminfo" (vacio) y:
       git remote add origin https://github.com/TU-USUARIO/acminfo.git
       git push -u origin main

4) Publicar el visor por primera vez:
       venv\Scripts\python.exe publicar_web.py
   Cifra el data.js, arma el sitio y lo empuja a la rama gh-pages.

5) Activar Pages: GitHub -> repo acminfo -> Settings -> Pages ->
   Source: "Deploy from a branch" -> Branch: gh-pages / (root) -> Save.
   Espera ~1 minuto.

6) Entrar: https://TU-USUARIO.github.io/acminfo/ -> te pide la clave -> visor.
   Anda desde el celular, la casa, donde sea. Con la PC apagada tambien (es estatico).

7) Automatizar: doble clic en `install_task_web.bat`. Republica todos los dias
   09:15 (tras el scrape), asi el sitio se mantiene al dia solo.

## Token de GitHub (Personal Access Token)

GitHub ya no acepta contrasena para push por HTTPS. Si git te pide "password",
pega un token:
- github.com -> Settings -> Developer settings -> Personal access tokens ->
  Fine-grained tokens -> Generate.
- Acceso: solo el repo `acminfo`. Permiso: "Contents" = Read and write.
- Pegalo cuando git te pida la contrasena. Queda guardado en el Administrador de
  credenciales de Windows, y las corridas automaticas (ZonapropWeb) lo reusan.

## Notas

- La clave del visor vive solo en web_config.json (local) y en tu cabeza. Si la
  perdes, no hay data (esta cifrada). Anotala.
- El data.js pesa 27 MB; si no queres que el celular lo baje entero cada vez,
  despues armamos una version mas liviana para la web.
- Si te molesta que se vea la ruta de tu server interno (\\servernt...) en
  config.json, la sacamos antes de pushear. Avisame.

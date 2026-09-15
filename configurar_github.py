#!/usr/bin/env python3
"""Deja el panel funcionando en GitHub Actions + Pages. Se ejecuta una vez.

    python configurar_github.py

Hace, en orden:
  1. Sube el codigo (si hace falta, abre el navegador para autorizar GitHub).
  2. Te pide email y contrasena de LaLiga y comprueba que entran.
  3. Guarda los tres secretos cifrados en el repositorio.
  4. Activa GitHub Pages desde Actions.
  5. Lanza la primera actualizacion, espera a que acabe y te da la URL.

Tus contrasenas se teclean aqui, en tu terminal. No pasan por ningun chat ni
se escriben en disco: van cifradas directamente a GitHub.
"""
import base64
import getpass
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).parent
DUENIO, REPO = "Oscarhp19", "FantasyClaude"
API = f"https://api.github.com/repos/{DUENIO}/{REPO}"
WORKFLOW = "actualizar.yml"
URL_GUARDADA = AQUI / "data" / "panel_url.txt"


def paso(n, texto):
    print(f"\n[{n}/5] {texto}", flush=True)


def git(*args, entrada=None, interactivo=False):
    return subprocess.run(
        ["git", *args], cwd=AQUI, input=entrada, text=True,
        capture_output=not interactivo,
    )


def token_github():
    r = git("credential", "fill", entrada="protocol=https\nhost=github.com\n\n")
    datos = dict(l.split("=", 1) for l in (r.stdout or "").splitlines() if "=" in l)
    return datos.get("password")


def gh(metodo, ruta, token, cuerpo=None):
    req = urllib.request.Request(
        ruta if ruta.startswith("http") else API + ruta,
        method=metodo,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FantasyClaude-setup",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            crudo = r.read()
            return r.status, (json.loads(crudo) if crudo else {})
    except urllib.error.HTTPError as e:
        crudo = e.read()
        try:
            return e.code, json.loads(crudo)
        except ValueError:
            return e.code, {"message": crudo.decode("utf-8", "replace")[:300]}


def sube_codigo():
    paso(1, "Subiendo el codigo a GitHub")
    r = git("push", "-u", "origin", "main")
    if r.returncode == 0:
        print("   Subido.")
        return
    if "Authentication failed" not in (r.stderr or "") and "Invalid username" not in (r.stderr or ""):
        sys.exit(f"   El push fallo:\n{r.stderr}")
    # La credencial guardada esta caducada: la borramos para que GCM pida una nueva.
    print("   Tu credencial de GitHub ha caducado. Se abrira el navegador:")
    print("   inicia sesion y pulsa 'Authorize'. Luego vuelve aqui.")
    git("credential", "reject", entrada=f"protocol=https\nhost=github.com\nusername={DUENIO}\n\n")
    r = git("push", "-u", "origin", "main", interactivo=True)
    if r.returncode != 0:
        sys.exit("   No se pudo subir. Vuelve a lanzar el script cuando hayas autorizado GitHub.")
    print("   Subido.")


def credenciales_laliga():
    paso(2, "Credenciales de LaLiga Fantasy")
    sys.path.insert(0, str(AQUI))
    import laliga_auth

    for intento in range(3):
        email = input("   Email de LaLiga: ").strip()
        clave = getpass.getpass("   Contrasena (no se ve al teclear): ")
        try:
            # Se prueban antes de guardarlas: un secreto con una errata solo se
            # descubriria cuando el robot fallase en su siguiente pase.
            laliga_auth.login_password(email, clave)
            print("   Correctas.")
            return email, clave
        except urllib.error.HTTPError:
            quedan = 2 - intento
            print(f"   No entran.{' Prueba otra vez.' if quedan else ''}")
    sys.exit(
        "   Tres intentos fallidos. Si entras con Google/Apple/Facebook no tienes "
        "contrasena propia: creala desde la app de LaLiga y vuelve a lanzar esto."
    )


def guarda_secretos(token, email, clave):
    paso(3, "Guardando los secretos cifrados en el repositorio")
    from nacl import encoding, public

    codigo, clave_repo = gh("GET", "/actions/secrets/public-key", token)
    if codigo != 200:
        sys.exit(f"   No pude leer la clave publica del repo ({codigo}): {clave_repo.get('message')}")
    sello = public.SealedBox(public.PublicKey(clave_repo["key"].encode(), encoding.Base64Encoder()))

    # Si ya habia una ruta de otra ejecucion, se reutiliza: asi la URL no cambia.
    ruta = None
    if URL_GUARDADA.exists():
        for linea in URL_GUARDADA.read_text(encoding="utf-8").splitlines():
            if linea.startswith("RUTA_SECRETA="):
                ruta = linea.split("=", 1)[1].strip()
    ruta = ruta or secrets.token_hex(8)

    for nombre, valor in (("LALIGA_EMAIL", email), ("LALIGA_PASSWORD", clave), ("RUTA_SECRETA", ruta)):
        cifrado = base64.b64encode(sello.encrypt(valor.encode())).decode()
        codigo, resp = gh("PUT", f"/actions/secrets/{nombre}", token,
                          {"encrypted_value": cifrado, "key_id": clave_repo["key_id"]})
        if codigo not in (201, 204):
            sys.exit(f"   Fallo guardando {nombre} ({codigo}): {resp.get('message')}")
        print(f"   {nombre} guardado.")
    return ruta


def activa_pages(token):
    paso(4, "Activando GitHub Pages")
    codigo, resp = gh("POST", "/pages", token, {"build_type": "workflow"})
    if codigo in (409, 422):  # ya existia: la ponemos en modo Actions
        codigo, resp = gh("PUT", "/pages", token, {"build_type": "workflow"})
    if codigo not in (200, 201, 204):
        sys.exit(f"   No pude activar Pages ({codigo}): {resp.get('message')}")
    print("   Activado.")


def lanza_y_espera(token, ruta):
    paso(5, "Primera actualizacion (tarda un par de minutos)")
    antes = time.time()
    codigo, resp = gh("POST", f"/actions/workflows/{WORKFLOW}/dispatches", token, {"ref": "main"})
    if codigo != 204:
        sys.exit(f"   No pude lanzar el workflow ({codigo}): {resp.get('message')}")

    run = None
    for _ in range(90):  # hasta ~7,5 min
        time.sleep(5)
        _, datos = gh("GET", f"/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=1", token)
        runs = datos.get("workflow_runs") or []
        if not runs:
            continue
        run = runs[0]
        if run["status"] == "completed":
            break
        print(f"   {run['status']}...", flush=True)

    if not run or run["status"] != "completed":
        print(f"   Sigue en marcha. Miralo en https://github.com/{DUENIO}/{REPO}/actions")
    elif run["conclusion"] != "success":
        sys.exit(f"   Ha fallado. Detalle: {run['html_url']}")

    _, pages = gh("GET", "/pages", token)
    base = (pages.get("html_url") or f"https://{DUENIO.lower()}.github.io/{REPO}/").rstrip("/")
    url = f"{base}/{ruta}/"

    URL_GUARDADA.parent.mkdir(parents=True, exist_ok=True)
    URL_GUARDADA.write_text(f"URL={url}\nRUTA_SECRETA={ruta}\n", encoding="utf-8")
    print(f"\n   Listo. Tu panel:\n\n     {url}\n")
    print(f"   Guardada tambien en {URL_GUARDADA.relative_to(AQUI)} (no se sube al repo).")
    print("   La primera vez Pages puede tardar 1-2 minutos mas en responder.")


def main():
    try:
        import nacl  # noqa: F401
    except ImportError:
        sys.exit("Falta PyNaCl, que cifra los secretos:  python -m pip install --user pynacl")

    sube_codigo()
    token = token_github()
    if not token:
        sys.exit("No encuentro el token de GitHub tras el push. Vuelve a lanzar el script.")
    codigo, yo = gh("GET", "https://api.github.com/user", token)
    if codigo != 200:
        sys.exit(f"El token de GitHub no vale ({codigo}). Vuelve a lanzar el script.")
    print(f"   Conectado como {yo.get('login')}.")

    email, clave = credenciales_laliga()
    try:
        ruta = guarda_secretos(token, email, clave)
    finally:
        del clave
    activa_pages(token)
    lanza_y_espera(token, ruta)


if __name__ == "__main__":
    main()

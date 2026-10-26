#!/usr/bin/env python3
"""Login OAuth2 + PKCE contra el Azure AD B2C de LaLiga, y refresco de sesion.

Se usa el client_id de la app movil porque es el unico que acepta los logins
federados (Google, Apple, Facebook) ademas del de email y contrasena.

Hay dos formas de entrar, una sola vez:

1. Email y contrasena, sin navegador (la mas simple, y la que funciona cuando
   la pagina de login se queda muerta al pulsar el boton). Rellena por debajo
   el mismo formulario que esa pagina:

    python laliga_auth.py password

2. Navegador, necesaria si entras con Google, Apple o Facebook:

    python laliga_auth.py login      # imprime un enlace; lo abres y entras
    python laliga_auth.py codigo "authredirect://...?code=..."   # pegas la URL

A partir de ahi el token se refresca solo. `asegura` hace lo mismo sin preguntar
nada: reutiliza la sesion y solo usa LALIGA_EMAIL/LALIGA_PASSWORD si ya no vale. La contrasena, si usas la opcion 1,
viaja unicamente a login.laliga.es y no se guarda en ningun sitio.
"""
import base64
import hashlib
import http.cookiejar
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTHORIZE = "https://login.laliga.es/laligadspprob2c.onmicrosoft.com/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.laliga.es/laligadspprob2c.onmicrosoft.com/oauth2/v2.0/token"
POLICY = "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"
# La policy de "resource owner" (contrasena directa al endpoint de token) la
# retiro LaLiga el 15/10/2026: ahora da 404. Los tokens viejos la llevan anotada.
POLICY_RETIRADA = "B2C_1A_ResourceOwnerv2"
CLIENT_NATIVO = "af88bcff-1157-40a0-b579-030728aacf0b"
CLIENT_WEB = "6457fa17-1224-416a-b21a-ee6ce76e9bc0"
# El scope incluye el propio client_id: sin eso B2C devuelve un token con otra
# audiencia (o ninguno) y la API lo rechaza con 401.
SCOPE = f"openid {CLIENT_NATIVO} offline_access"
LOGIN_HOST = "https://login.laliga.es"
# La app movil registra este esquema. El navegador de escritorio no sabe abrirlo,
# pero deja la URL completa (con el code) en la barra de direcciones: con eso basta.
REDIRECT = "authredirect://com.lfp.laligafantasy"

DATA = Path(__file__).parent / "data"
TOKENS = DATA / "tokens.json"
PENDIENTE = DATA / "login_pendiente.json"
PENDIENTE_TTL = 900  # 15 min


def _escribe_privado(path: Path, obj):
    """Guarda JSON y restringe permisos: esto es media credencial o entera."""
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # en Windows el chmod es simbolico; el fichero ya esta en .gitignore


def _post_form(url, campos):
    datos = urllib.parse.urlencode(campos).encode()
    req = urllib.request.Request(
        url,
        data=datos,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def _normaliza(resp, client_id, policy=POLICY):
    ahora = int(time.time())
    return {
        "access_token": resp.get("access_token", ""),
        "refresh_token": resp.get("refresh_token", ""),
        "client_id": client_id,
        # B2C exige refrescar contra la MISMA policy que emitio el token
        "policy": policy,
        # 60 s de colchon para no usar un token que caduca a mitad de peticion
        "expira_en": ahora + int(resp.get("expires_in", 3600)) - 60,
        "obtenido": ahora,
    }


def _url_login():
    """URL de authorize con PKCE recien generado. Devuelve (url, verifier, state)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode()
    params = {
        "p": POLICY,
        "client_id": CLIENT_NATIVO,
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": state,  # B2C exige nonce y aqui no hay nada mejor a lo que atarlo
    }
    return AUTHORIZE + "?" + urllib.parse.urlencode(params), verifier, state


def inicia_login():
    url, verifier, state = _url_login()
    _escribe_privado(PENDIENTE, {"verifier": verifier, "state": state, "inicio": int(time.time())})
    return url


def extrae_codigo(texto):
    """Acepta la URL de redireccion completa o el codigo pelado."""
    texto = texto.strip().strip('"').strip("'")
    if "code=" in texto:
        # urlparse no entiende el esquema custom: partimos por la query a mano
        query = texto.split("?", 1)[1] if "?" in texto else texto
        query = query.split("#", 1)[0]
        valores = urllib.parse.parse_qs(query)
        if "error" in valores:
            raise SystemExit(
                f"LaLiga devolvio un error: {valores['error'][0]} "
                f"{valores.get('error_description', [''])[0]}"
            )
        if "code" in valores:
            return valores["code"][0]
    if texto and " " not in texto and "/" not in texto:
        return texto
    raise SystemExit("No encuentro ningun 'code=' en lo que has pegado.")


def canjea(codigo):
    if not PENDIENTE.exists():
        raise SystemExit("No hay login empezado. Ejecuta primero: python laliga_auth.py login")
    pend = json.loads(PENDIENTE.read_text(encoding="utf-8"))
    if time.time() - pend["inicio"] > PENDIENTE_TTL:
        PENDIENTE.unlink(missing_ok=True)
        raise SystemExit("El login empezado ha caducado (15 min). Pide otro enlace.")
    tokens = _canjea(codigo, pend["verifier"])
    PENDIENTE.unlink(missing_ok=True)  # el verifier ya esta gastado
    return tokens


def _canjea(codigo, verifier):
    resp = _post_form(
        f"{TOKEN_URL}?p={POLICY}",
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_NATIVO,
            "code": codigo,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
            "scope": SCOPE,
        },
    )
    tokens = _normaliza(resp, CLIENT_NATIVO)
    if not tokens["access_token"]:
        raise SystemExit(f"La respuesta no traia token: {resp}")
    _escribe_privado(TOKENS, tokens)
    return tokens


class CredencialesIncorrectas(Exception):
    pass


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # cada salto se mira a mano: el ultimo va a authredirect://


def login_password(email, password):
    """Email y contrasena sin navegador, haciendo lo mismo que la pagina de login.

    Desde que LaLiga retiro la policy de contrasena directa, la unica puerta es la
    pagina de B2C: se carga authorize, se envian las credenciales a SelfAsserted
    con el csrf y la transaccion que trae la pagina, y "confirmed" redirige a
    authredirect://...?code=, que se canjea con PKCE como el login de navegador.
    La contrasena viaja solo a login.laliga.es y no se guarda.
    """
    url, verifier, _ = _url_login()
    abridor = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _SinRedirecciones
    )
    cabeceras = {"User-Agent": "Mozilla/5.0", "Accept-Language": "es-ES,es;q=0.9"}

    def abre(destino, datos=None, extra=None):
        req = urllib.request.Request(destino, data=datos, headers={**cabeceras, **(extra or {})})
        try:
            with abridor.open(req, timeout=45) as r:
                return r.status, r.headers, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307):
                return e.code, e.headers, ""
            raise

    _, _, html = abre(url)
    m = re.search(r"var SETTINGS = (\{.*?\});", html, re.S)
    if not m:
        raise SystemExit("La pagina de login de LaLiga ha cambiado: no encuentro SETTINGS.")
    ajustes = json.loads(m.group(1))
    base = LOGIN_HOST + ajustes["hosts"]["tenant"]
    tx = {"tx": ajustes["transId"], "p": ajustes["hosts"]["policy"]}
    # Los nombres de campo salen de la pagina (hoy signInName y password_login).
    ids = re.findall(r'"ID": "([^"]+)"', html)
    campo_pass = next((i for i in ids if i.startswith("password")), "password")

    _, _, cuerpo = abre(
        f"{base}/SelfAsserted?{urllib.parse.urlencode(tx)}",
        urllib.parse.urlencode(
            {"request_type": "RESPONSE", "signInName": email, campo_pass: password}
        ).encode(),
        {
            "X-CSRF-TOKEN": ajustes["csrf"],
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        },
    )
    try:
        respuesta = json.loads(cuerpo)
    except ValueError:
        raise SystemExit(f"Respuesta inesperada del login: {cuerpo[:300]}")
    if str(respuesta.get("status")) != "200":
        # 90225: contrasena mal; 90053/90054: no existe o credencial invalida.
        if respuesta.get("errorCode") in ("AADB2C90225", "AADB2C90053", "AADB2C90054"):
            raise CredencialesIncorrectas(respuesta.get("errorCode"))
        raise SystemExit(f"El login de LaLiga ha respondido: {respuesta}")

    destino = f"{base}/api/{ajustes['api']}/confirmed?" + urllib.parse.urlencode(
        {"rememberMe": "false", "csrf_token": ajustes["csrf"], **tx}
    )
    for _ in range(6):
        codigo_http, cab, html = abre(destino)
        destino = urllib.parse.urljoin(destino, cab.get("Location") or "")
        if destino.startswith(REDIRECT):
            return _canjea(extrae_codigo(destino), verifier)
        if codigo_http not in (301, 302, 303, 307):
            # Otra pantalla intermedia (condiciones, verificacion...): no la sabemos pasar.
            pantalla = re.search(r'"api": "([^"]+)"', html)
            raise SystemExit(
                "El login de LaLiga pide un paso mas que no se puede hacer sin navegador "
                f"({pantalla.group(1) if pantalla else codigo_http}). "
                "Entra una vez en la app oficial y vuelve a probar."
            )
    raise SystemExit("El login de LaLiga redirige en bucle.")


def refresca(tokens):
    """El refresh token rota en cada uso: hay que guardar el nuevo si o si."""
    ultimo = None
    policy = tokens.get("policy", POLICY)
    if policy == POLICY_RETIRADA:
        policy = POLICY
    client_id = tokens.get("client_id") or CLIENT_NATIVO
    # Probamos primero la combinacion que emitio el token; el resto es red de seguridad.
    intentos = dict.fromkeys(
        [(policy, client_id), (POLICY, CLIENT_NATIVO), (POLICY, CLIENT_WEB)]
    )
    for pol, cid in intentos:
        try:
            resp = _post_form(
                f"{TOKEN_URL}?p={pol}",
                {
                    "grant_type": "refresh_token",
                    "client_id": cid,
                    "refresh_token": tokens["refresh_token"],
                    "scope": f"openid {cid} offline_access",
                },
            )
        except Exception as e:
            ultimo = f"{pol}/{cid}: {e}"
            continue
        nuevos = _normaliza(resp, cid, pol)
        if nuevos["access_token"]:
            if not nuevos["refresh_token"]:
                nuevos["refresh_token"] = tokens["refresh_token"]
            _escribe_privado(TOKENS, nuevos)
            return nuevos
    raise SystemExit(f"El refresh ha fallado ({ultimo}). Vuelve a iniciar sesion.")


def token_valido():
    """Devuelve un access_token utilizable, refrescando si hace falta."""
    if not TOKENS.exists():
        raise SystemExit("No has iniciado sesion. Ejecuta: python laliga_auth.py login")
    tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
    if time.time() >= tokens.get("expira_en", 0):
        if not tokens.get("refresh_token"):
            raise SystemExit("Sesion caducada y sin refresh token. Repite el login.")
        print("Token caducado: refrescando...", file=sys.stderr)
        tokens = refresca(tokens)
    return tokens["access_token"]


def main():
    # Sin esto, en el log de Actions los errores (stderr) salen antes que los
    # avisos (stdout) y el orden engana.
    sys.stdout.reconfigure(line_buffering=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "asegura":
        # Para el robot de GitHub: reutiliza la sesion guardada y solo mete la
        # contrasena si ya no vale. Un login con contrasena cada pocos minutos
        # desde un servidor es la senal mas clara de que no hay una persona.
        if TOKENS.exists():
            try:
                token_valido()
                print("Sesion reutilizada: sin iniciar sesion con contrasena.")
                return
            except SystemExit as e:
                print(f"La sesion guardada ya no vale ({e}). Se inicia sesion de nuevo.")
        else:
            print("No hay sesion guardada. Se inicia sesion con contrasena.")
        cmd = "password"
    if cmd == "password":
        import getpass

        # En CI no hay teclado: si vienen por entorno, se usan sin preguntar.
        email = os.environ.get("LALIGA_EMAIL", "").strip()
        clave = os.environ.get("LALIGA_PASSWORD", "")
        if email and clave:
            print(f"Usando credenciales del entorno para {email}")
        else:
            print("Login directo contra LaLiga (sin navegador).")
            print("La contrasena se envia solo a login.laliga.es y no se guarda en disco.\n")
            email = input("Email de tu cuenta LaLiga: ").strip()
            clave = getpass.getpass("Contrasena (no se ve al teclear): ")
        if not email or not clave:
            raise SystemExit(
                "Hacen falta email y contrasena (o las variables "
                "LALIGA_EMAIL y LALIGA_PASSWORD)."
            )
        try:
            t = login_password(email, clave)
        except CredencialesIncorrectas:
            raise SystemExit(
                "Email o contrasena incorrectos.\n"
                "Si entras a LaLiga con Google, Apple o Facebook no tienes contrasena "
                "propia: usa 'python laliga_auth.py login' o creala desde la app."
            )
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")
            raise SystemExit(f"HTTP {e.code} en el login de LaLiga: {detalle[:400]}")
        finally:
            del clave
        print(f"\nSesion guardada en {TOKENS}")
        print(f"Valida hasta {time.strftime('%H:%M:%S', time.localtime(t['expira_en']))}")
        print("A partir de ahora se refresca sola.")
    elif cmd == "login":
        url = inicia_login()
        print("\n1. Abre este enlace en tu navegador e inicia sesion:\n")
        print(url)
        print(
            "\n2. Al terminar, el navegador intentara abrir 'authredirect://...' y dara\n"
            "   un error. Es lo esperado: NO cierres la pestana.\n"
            "   Copia la URL COMPLETA de la barra de direcciones.\n"
            "\n3. Pegala aqui:\n"
            '   python laliga_auth.py codigo "authredirect://com.lfp.laligafantasy?code=..."\n'
        )
    elif cmd == "codigo":
        if len(sys.argv) < 3:
            raise SystemExit('Uso: python laliga_auth.py codigo "<url pegada>"')
        t = canjea(extrae_codigo(sys.argv[2]))
        print(f"Sesion guardada en {TOKENS}")
        print(f"Access token valido hasta {time.strftime('%H:%M:%S', time.localtime(t['expira_en']))}")
        print("A partir de ahora se refresca solo.")
    elif cmd == "estado":
        if not TOKENS.exists():
            print("Sin sesion.")
            return
        t = json.loads(TOKENS.read_text(encoding="utf-8"))
        queda = int(t.get("expira_en", 0) - time.time())
        print(f"Sesion activa. Access token: {'caducado' if queda < 0 else f'{queda // 60} min'}")
        print(f"Refresh token: {'si' if t.get('refresh_token') else 'NO'}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

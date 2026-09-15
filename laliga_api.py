#!/usr/bin/env python3
"""Cliente de la API oficial de LaLiga Fantasy.

Rutas verificadas contra el cliente de referencia PlatanosVerdes/laliga-fantasy.
Ojo: la API mezcla /league/ y /leagues/ segun el endpoint, no es un error de aqui.

    python laliga_api.py ligas        # tus ligas y su id (empieza por aqui)
    python laliga_api.py mercado LIGA_ID
    python laliga_api.py dinero EQUIPO_ID
    python laliga_api.py actividad LIGA_ID
"""
import gzip
import json
import sys
import urllib.error
import urllib.request

import laliga_auth

BASE = "https://fantasy-api.llt-services.com/api"
# Prefijo del que cuelga casi todo. La competicion 1 es LaLiga EA Sports.
COMP_RUTA = "/v1/competition/1"


# Cuantas llamadas hace este proceso: sirve para vigilar que no parezca un bot.
PETICIONES = 0


def pide(ruta, autenticado=True):
    global PETICIONES
    PETICIONES += 1
    url = ruta if ruta.startswith("http") else BASE + ruta
    cabeceras = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://fantasy.laliga.com/",
    }
    if autenticado:
        cabeceras["Authorization"] = "Bearer " + laliga_auth.token_valido()
    req = urllib.request.Request(url, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            crudo = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                crudo = gzip.decompress(crudo)
            return json.loads(crudo.decode("utf-8"))
    except urllib.error.HTTPError as e:
        cuerpo = e.read()[:300].decode("utf-8", "replace")
        if e.code == 401:
            raise SystemExit(
                "401: la sesion no vale. Prueba 'python laliga_auth.py estado' "
                "y si hace falta repite el login."
            )
        if e.code == 500:
            # La API contesta 500 (no 404) a rutas que existen a medias o que
            # piden otro prefijo. Si pasa, la ruta esta mal, no la sesion.
            raise SystemExit(
                f"500 en {url}\nLa sesion vale (un token malo daria 401): "
                f"lo que falla es la ruta.\n{cuerpo}"
            )
        raise SystemExit(f"HTTP {e.code} en {url}\n{cuerpo}")


# --- publico, sin token ---------------------------------------------------
def jugadores():
    """843 jugadores con valor oficial, puntos por jornada y estado fisico."""
    return pide(f"{COMP_RUTA}/players", autenticado=False)


def equipos():
    # No cuelga del prefijo de competicion, y tiene que ser "teams-master":
    # la ruta /teams contesta otra cosa distinta.
    return pide("/v3/teams-master", autenticado=False)


# --- requiere sesion ------------------------------------------------------
def ligas():
    # Cuelga del prefijo de competicion como casi todo. La ruta suelta
    # /v3/leagues existe pero responde 500: no es esta.
    return pide(f"{COMP_RUTA}/leagues")


def yo():
    return pide("/v4/user/me")


def mercado(liga_id):
    return pide(f"{COMP_RUTA}/league/{liga_id}/market")


def dinero(equipo_id):
    return pide(f"{COMP_RUTA}/teams/{equipo_id}/money")


def plantilla(liga_id, equipo_id):
    return pide(f"{COMP_RUTA}/leagues/{liga_id}/teams/{equipo_id}")


def clasificacion(liga_id):
    return pide(f"{COMP_RUTA}/leagues/{liga_id}/standing")


def actividad(liga_id, indice=0):
    """Feed de movimientos de la liga: fichajes, ventas y clausulas.

    Va paginado por indice; 0 es lo mas reciente.
    """
    return pide(f"{COMP_RUTA}/leagues/{liga_id}/activity/{indice}")


def valor_jugador(jugador_id):
    return pide(f"{COMP_RUTA}/player/{jugador_id}/market-value")


def ofertas(liga_id, player_team_id):
    """Ofertas recibidas por uno de tus jugadores.

    Va por playerTeamId (el hueco en tu plantilla), no por id de jugador:
    /market/{id}/offer solo acepta POST y contesta 405 a un GET.
    """
    return pide(f"{COMP_RUTA}/league/{liga_id}/playerTeam/{player_team_id}/offer")


def alineacion(equipo_id):
    """Once actual. formation.tacticalFormation es la forma, p.ej. [3,4,3]."""
    return pide(f"{COMP_RUTA}/teams/{equipo_id}/lineup")


def formaciones(premium=True):
    return pide("/v4/teams/lineup/formations?option=" + ("premium" if premium else "standard"))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    acciones = {
        "ligas": lambda: ligas(),
        "yo": lambda: yo(),
        "jugadores": lambda: jugadores()[:3],
        "equipos": lambda: equipos()[:5],
        "mercado": lambda: mercado(arg),
        "dinero": lambda: dinero(arg),
        "plantilla": lambda: plantilla(arg, sys.argv[3]),
        "clasificacion": lambda: clasificacion(arg),
        "actividad": lambda: actividad(arg),
    }
    if cmd not in acciones:
        print(__doc__)
        return
    if cmd in ("mercado", "dinero", "plantilla", "clasificacion", "actividad") and not arg:
        raise SystemExit(f"'{cmd}' necesita un id. Mira 'python laliga_api.py ligas'.")
    print(json.dumps(acciones[cmd](), ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()

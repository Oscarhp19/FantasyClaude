#!/usr/bin/env python3
"""Vuelca el estado completo de tu liga a data/liga.json.

    python sync.py                 # detecta tu liga sola
    python sync.py --liga 018411724
    python sync.py --resumen       # solo imprime, sin escribir

Calcula lo que la API no da hecho: saldo estimado de cada rival, quien tiene a
quien, cuanta prima se paga de verdad en la liga, y que jugadores tuyos tienen
la clausula al alcance de alguien.
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import laliga_api as api

DATA = Path(__file__).parent / "data"
SALIDA = DATA / "liga.json"

# Efecto en caja de cada tipo de evento, desde el punto de vista de user1.
# Sacado del log real de la liga; 10 aparece sin documentar y se deja pasar.
TIPOS = {
    1: ("traspaso", -1, +1),  # entre managers: user1 paga, user2 cobra
    6: ("recompensa", +1, 0),
    9: ("se une a la liga", 0, 0),
    31: ("compra", -1, 0),  # al mercado del juego
    33: ("venta", +1, 0),  # al mercado del juego
}
SALDO_INICIAL = 100_000_000.0

# El endpoint de plantilla trae positionId pero no el nombre de la posicion,
# al reves que el de mercado. Lo derivamos para que ambos hablen igual.
POSICIONES = {1: "Portero", 2: "Defensa", 3: "Centrocampista", 4: "Delantero", 5: "Entrenador"}


def num(x, defecto=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return defecto


CACHE = DATA / "cache_api.json"

# Cuanto aguanta cada respuesta antes de volver a pedirla. El mercado y la
# actividad se piden en cada pase porque son lo que cambia a cada rato; lo demas
# solo cuando caduca, o antes si la actividad dice que ha habido fichajes.
# Pedirlo todo cada vez eran ~33 llamadas por pase: el patron de un bot.
TTL = {
    "ligas": 24 * 3600,
    "formaciones": 24 * 3600,
    "clasificacion": 60 * 60,
    "plantilla": 60 * 60,
    "alineacion": 60 * 60,
    "ofertas": 30 * 60,
    "dinero": 20 * 60,
}


def pausa():
    """Espera irregular entre peticiones: un ritmo exacto delata a un script."""
    time.sleep(random.uniform(0.6, 1.8))


class Cache:
    def __init__(self, ignorar=False):
        self.d = {}
        if not ignorar:
            try:
                self.d = json.loads(CACHE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.d = {}
        self.ahora = time.time()
        self.de_red, self.de_cache = 0, 0

    def dame(self, clave, pedir, forzar=False):
        entrada = self.d.get(clave)
        if entrada and not forzar and self.ahora < entrada["caduca"]:
            self.de_cache += 1
            return entrada["v"]
        valor = pedir()
        tipo = clave.split(":")[0]
        # Caducidad con un +-25% al azar: si no, todo lo que se pidio junto
        # caduca junto y sale en rafaga siempre a la misma hora.
        self.d[clave] = {"v": valor, "caduca": self.ahora + TTL[tipo] * random.uniform(0.75, 1.25)}
        self.de_red += 1
        pausa()
        return valor

    def guarda(self):
        DATA.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")


def descarga_actividad(liga_id, cache, max_paginas=40):
    """Solo lo nuevo: el feed va de mas reciente a mas antiguo, asi que en cuanto
    una pagina trae un evento que ya teniamos, lo que sigue tambien lo es.

    Devuelve (todos los eventos, cuantos son nuevos respecto al pase anterior).
    """
    previos = cache.d.get("actividad", {}).get("v", [])
    conocidos = {e.get("id") for e in previos}
    nuevos = []
    for i in range(max_paginas):
        try:
            pagina = api.actividad(liga_id, i)
        except SystemExit as e:
            print(f"  aviso: actividad pagina {i} fallo ({e})", file=sys.stderr)
            break
        pausa()
        if not pagina:
            break
        frescos = [e for e in pagina if e.get("id") not in conocidos]
        conocidos.update(e.get("id") for e in frescos)
        nuevos.extend(frescos)
        if len(frescos) < len(pagina):
            break
    eventos = sorted(previos + nuevos, key=lambda e: e.get("createdAt") or "")
    cache.d["actividad"] = {"v": eventos, "caduca": 0}
    return eventos, (len(nuevos) if previos else 0)


def saldos_estimados(eventos, manager_ids):
    """Reconstruye la caja de cada manager desde el log.

    Es una estimacion: la API solo publica el dinero real del equipo propio.
    Si el log no llega al principio de temporada, el numero arrastra ese sesgo.
    """
    saldo = {str(m): SALDO_INICIAL for m in manager_ids}
    desconocidos = set()
    for ev in eventos:
        tipo = ev.get("activityTypeId")
        if tipo not in TIPOS:
            # Solo preocupa lo que mueve caja; los eventos informativos (importe 0)
            # no desvian nada y llenarian el aviso de ruido.
            if num(ev.get("amount")):
                desconocidos.add(tipo)
            continue
        _, signo1, signo2 = TIPOS[tipo]
        importe = num(ev.get("amount"))
        u1, u2 = str(ev.get("user1Id") or ""), str(ev.get("user2Id") or "")
        if u1 in saldo:
            saldo[u1] += signo1 * importe
        if u2 and u2 in saldo:
            saldo[u2] += signo2 * importe
    return saldo, sorted(x for x in desconocidos if x is not None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", help="id de liga (si no, la primera tuya)")
    ap.add_argument("--resumen", action="store_true", help="no escribir fichero")
    ap.add_argument("--completo", action="store_true",
                    help="ignora la cache y lo pide todo (lo usa el boton Actualizar)")
    args = ap.parse_args()
    cache = Cache(ignorar=args.completo)

    ligas = cache.dame("ligas", api.ligas)
    if not ligas:
        sys.exit("No apareces en ninguna liga.")
    liga = next((l for l in ligas if l["id"] == args.liga), ligas[0]) if args.liga else ligas[0]
    liga_id = liga["id"]
    mi_equipo = str(liga["team"]["id"])
    print(f"  {liga['name']} ({liga['managersNumber']} managers)", file=sys.stderr)

    # Siempre frescos: lo que cambia sin avisar.
    mercado = api.mercado(liga_id)
    pausa()
    eventos, nuevos = descarga_actividad(liga_id, cache)
    # Un fichaje, venta o clausulazo cambia plantillas, clasificacion y dinero.
    hay_fichajes = nuevos > 0
    print(f"  {len(mercado)} en mercado, {len(eventos)} movimientos ({nuevos} nuevos)", file=sys.stderr)

    clasif = cache.dame("clasificacion", lambda: api.clasificacion(liga_id), forzar=hay_fichajes)
    dinero = cache.dame("dinero", lambda: api.dinero(mi_equipo), forzar=hay_fichajes)

    equipos = {}
    for fila in clasif:
        t = fila["team"]
        equipos[str(t["managerId"])] = {
            "team_id": str(t["id"]),
            "manager": t.get("manager", {}).get("managerName", "?"),
            "posicion": fila.get("position"),
            "puntos": fila.get("points"),
            "valor_plantilla": t.get("teamValue"),
        }

    for mid, info in equipos.items():
        try:
            p = cache.dame(f"plantilla:{info['team_id']}",
                           lambda tid=info["team_id"]: api.plantilla(liga_id, tid), forzar=hay_fichajes)
        except SystemExit as e:
            print(f"  aviso: plantilla de {info['manager']} fallo ({e})", file=sys.stderr)
            info["jugadores"] = []
            continue
        info["jugadores"] = [
            {
                "id": str(j["playerMaster"]["id"]),
                # El id del hueco en plantilla, no del jugador: las ofertas van por aqui
                "player_team_id": str(j.get("playerTeamId") or ""),
                "nombre": j["playerMaster"].get("nickname"),
                "posicion": j["playerMaster"].get("position")
                or POSICIONES.get(j["playerMaster"].get("positionId")),
                "posicion_id": j["playerMaster"].get("positionId"),
                "valor": num(j["playerMaster"].get("marketValue")),
                "media_puntos": round(num(j["playerMaster"].get("averagePoints")), 2),
                "puntos": j["playerMaster"].get("points"),
                "estado": j["playerMaster"].get("playerStatus"),
                "clausula": num(j.get("buyoutClause")),
                "clausula_bloqueada_hasta": j.get("buyoutClauseLockedEndTime"),
                "escudo": bool(j.get("isShielded")),
            }
            for j in (p.get("players") or [])
        ]

    # --- ofertas recibidas y once actual: solo de tu equipo ---
    mi_manager_tmp = next((m for m, i in equipos.items() if i["team_id"] == mi_equipo), None)
    ofertas = {}
    for j in equipos.get(mi_manager_tmp, {}).get("jugadores", []):
        if not j["player_team_id"]:
            continue
        try:
            recibidas = cache.dame(f"ofertas:{j['player_team_id']}",
                                   lambda pt=j["player_team_id"]: api.ofertas(liga_id, pt))
        except SystemExit as e:
            print(f"  aviso: ofertas de {j['nombre']} fallaron ({e})", file=sys.stderr)
            continue
        pendientes = [o for o in recibidas if (o.get("status") or "") == "pending"]
        if pendientes:
            ofertas[j["id"]] = [
                {
                    "importe": num(o.get("money")),
                    "del_mercado": bool(o.get("isFromMarket")),
                    "caduca": o.get("expirationDate"),
                    "creada": o.get("createdAt"),
                }
                for o in pendientes
            ]
    print(f"  {sum(len(v) for v in ofertas.values())} ofertas pendientes", file=sys.stderr)

    try:
        once = cache.dame("alineacion", lambda: api.alineacion(mi_equipo))
    except SystemExit as e:
        print(f"  aviso: alineacion fallo ({e})", file=sys.stderr)
        once = {}
    try:
        formas = cache.dame("formaciones", lambda: api.formaciones(True) + api.formaciones(False))
    except SystemExit:
        formas = []

    cache.guarda()
    print(f"  {api.PETICIONES} peticiones a LaLiga en este pase "
          f"({cache.de_cache} respuestas reutilizadas de la cache)", file=sys.stderr)

    saldo, tipos_raros = saldos_estimados(eventos, equipos.keys())
    # El dinero real del equipo propio manda sobre la estimacion.
    mi_manager = next((m for m, i in equipos.items() if i["team_id"] == mi_equipo), None)
    real = num(dinero.get("teamMoney"))
    desvio = None
    if mi_manager:
        desvio = real - saldo.get(mi_manager, 0)
        saldo[mi_manager] = real
        # El log no registra las recompensas (bonus diario, premio de once ideal),
        # asi que todos los saldos salen cortos. Medimos cuanto con el equipo propio
        # y se lo sumamos a los rivales: para valorar quien puede pagarte una
        # clausula, quedarse corto es el error que duele.
        if desvio and desvio > 0:
            for m in saldo:
                if m != mi_manager:
                    saldo[m] += desvio

    # --- quien tiene a quien ---
    duenos = {}
    for mid, info in equipos.items():
        for j in info["jugadores"]:
            duenos[j["id"]] = info["manager"]

    # --- precios reales pagados: prima sobre el valor de mercado del momento ---
    valores = {str(p["playerMaster"]["id"]): num(p["playerMaster"].get("marketValue")) for p in mercado}
    compras = []
    for ev in eventos:
        if ev.get("activityTypeId") not in (1, 31):
            continue
        pid = str(ev.get("playerMasterId") or "")
        importe = num(ev.get("amount"))
        valor = valores.get(pid)
        compras.append(
            {
                "fecha": (ev.get("createdAt") or "")[:10],
                "jugador_id": pid,
                "comprador": equipos.get(str(ev.get("user1Id")), {}).get("manager", "?"),
                "pagado": importe,
                # Solo sale si el jugador esta hoy en el mercado; si no, no hay
                # con que comparar y se deja en None a proposito.
                "prima_pct": round((importe / valor - 1) * 100, 1) if valor else None,
            }
        )
    primas = [c["prima_pct"] for c in compras if c["prima_pct"] is not None]

    # --- alertas de clausula: quien puede pagarla hoy ---
    alertas = []
    mios = equipos.get(mi_manager, {}).get("jugadores", []) if mi_manager else []
    for j in mios:
        if j["escudo"] or not j["clausula"]:
            continue
        pueden = sorted(
            (i["manager"] for m, i in equipos.items() if m != mi_manager and saldo.get(m, 0) >= j["clausula"]),
        )
        if pueden:
            alertas.append(
                {
                    "jugador": j["nombre"],
                    "valor": j["valor"],
                    "clausula": j["clausula"],
                    "margen_pct": round((j["clausula"] / j["valor"] - 1) * 100, 1) if j["valor"] else None,
                    "pueden_pagarla": pueden,
                    "bloqueada_hasta": j["clausula_bloqueada_hasta"],
                }
            )
    alertas.sort(key=lambda a: a["margen_pct"] if a["margen_pct"] is not None else 9e9)

    salida = {
        "actualizado": datetime.now().isoformat(timespec="seconds"),
        "liga": {
            "id": liga_id,
            "nombre": liga["name"],
            "managers": liga["managersNumber"],
            "clausulas_activas": liga.get("config", {}).get("features", {}).get("buyoutClause"),
        },
        "yo": {
            "team_id": mi_equipo,
            "manager": equipos.get(mi_manager, {}).get("manager"),
            "dinero": real,
            "inversion": num(dinero.get("teamInvestment")),
            "valor_plantilla": equipos.get(mi_manager, {}).get("valor_plantilla"),
            "formacion_actual": (once.get("formation") or {}).get("tacticalFormation"),
            "capitan": (once.get("formation") or {}).get("captain"),
            "formaciones_permitidas": sorted(set(formas)),
        },
        "ofertas": ofertas,
        "equipos": [
            {**info, "manager_id": mid, "saldo_estimado": round(saldo.get(mid, 0))}
            for mid, info in sorted(equipos.items(), key=lambda kv: kv[1]["posicion"] or 99)
        ],
        "mercado": [
            {
                "id": str(e["playerMaster"]["id"]),
                "nombre": e["playerMaster"].get("nickname"),
                "posicion": e["playerMaster"].get("position"),
                "equipo_real": e["playerMaster"].get("teamId"),
                "valor": num(e["playerMaster"].get("marketValue")),
                "precio_venta": num(e.get("salePrice")),
                "media_puntos": e["playerMaster"].get("averagePoints"),
                "estado": e["playerMaster"].get("playerStatus"),
                "pujas": e.get("numberOfBids"),
                "caduca": e.get("expirationDate"),
                # marketPlayerTeam = lo vende un manager; marketPlayerLeague = libre
                "lo_vende": duenos.get(str(e["playerMaster"]["id"]))
                if e.get("discr") == "marketPlayerTeam"
                else None,
                "vendedor_tipo": "manager" if e.get("discr") == "marketPlayerTeam" else "liga",
                "vendedor": (duenos.get(str(e["playerMaster"]["id"])) or "Mánager")
                if e.get("discr") == "marketPlayerTeam"
                else "LaLiga",
            }
            for e in mercado
        ],
        "movimientos": [
            {
                "fecha": ev.get("createdAt"),
                "tipo": TIPOS.get(ev.get("activityTypeId"), ("desconocido", 0, 0))[0],
                "tipo_id": ev.get("activityTypeId"),
                "manager": equipos.get(str(ev.get("user1Id")), {}).get("manager", "?"),
                "jugador_id": str(ev.get("playerMasterId") or ""),
                "importe": num(ev.get("amount")),
            }
            for ev in reversed(eventos)
        ],
        "alertas_clausula": alertas,
        "prima_media_liga_pct": round(sum(primas) / len(primas), 1) if primas else None,
        "avisos": (
            [f"tipos de evento sin mapear: {tipos_raros}"] if tipos_raros else []
        )
        + (
            [f"el log no registra recompensas: faltaban {desvio:+,.0f} en tu caja y se "
             f"ha sumado esa misma cantidad a cada rival, asi que sus saldos son un minimo"]
            if desvio and desvio > 0
            else []
        ),
    }

    if not args.resumen:
        DATA.mkdir(parents=True, exist_ok=True)
        SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")

    eur = lambda x: f"{x:,.0f}".replace(",", ".")
    print(f"\n{salida['liga']['nombre']} — {salida['yo']['manager']}")
    print(f"Tu dinero: {eur(real)}   Plantilla: {eur(num(salida['yo']['valor_plantilla']))}\n")
    print(f"{'MANAGER':<20} {'POS':>3} {'PTS':>5} {'PLANTILLA':>13} {'SALDO EST.':>13}")
    for e in salida["equipos"]:
        marca = " <- tu" if e["team_id"] == mi_equipo else ""
        print(f"{e['manager'][:20]:<20} {e['posicion'] or '-':>3} {e['puntos'] or 0:>5} "
              f"{eur(num(e['valor_plantilla'])):>13} {eur(e['saldo_estimado']):>13}{marca}")

    if alertas:
        print(f"\nClausulas al alcance de alguien ({len(alertas)}):")
        for a in alertas[:8]:
            m = f"{a['margen_pct']:+.0f}%" if a["margen_pct"] is not None else "?"
            print(f"  {a['jugador'][:20]:<20} clausula {eur(a['clausula']):>13} ({m} s/valor) "
                  f"— pueden: {', '.join(a['pueden_pagarla'][:3])}")

    if salida["prima_media_liga_pct"] is not None:
        print(f"\nPrima media pagada en la liga: {salida['prima_media_liga_pct']:+.1f}% sobre valor")
    for a in salida["avisos"]:
        print(f"[!] {a}")
    if not args.resumen:
        print(f"\n-> {SALIDA}")


if __name__ == "__main__":
    main()

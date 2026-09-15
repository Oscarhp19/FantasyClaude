#!/usr/bin/env python3
"""Cruza tu liga real con los datos de tendencia y produce el informe de compra.

    python sync.py && python informe.py

Une dos fuentes que se complementan:
  - API oficial (data/liga.json): tu mercado, tu dinero, media de puntos, estado
  - FutbolFantasy (data/mercado.json): tendencia de precio y probabilidad de jugar

Escribe data/informe.json.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import laliga_api as api
import scrape

DATA = Path(__file__).parent / "data"
LIGA = DATA / "liga.json"
FF = DATA / "mercado.json"
SALIDA = DATA / "informe.json"

# Palabras que sobran al comparar nombres de equipo entre las dos fuentes
RUIDO_EQUIPO = {"cf", "ud", "rc", "real", "club", "de", "fc", "cd", "sd", "rcd"}


def mismo_equipo(a, b):
    a, b = scrape.slug(a or ""), scrape.slug(b or "")
    if not a or not b:
        return False
    ta = set(a.split()) - RUIDO_EQUIPO
    tb = set(b.split()) - RUIDO_EQUIPO
    return bool(ta & tb) or a[:5] == b[:5]


def empareja(nombre, equipo, ff):
    """La API oficial abrevia ('O. Sancet') y FutbolFantasy no ('oihan sancet').

    Por eso, si el nombre completo no casa, se cae al apellido filtrado por equipo.
    """
    q = scrape.slug(nombre or "")
    for cand in (
        [j for j in ff if j["slug"] == q],
        [j for j in ff if q in j["slug"].split()],
        [j for j in ff if q and q in j["slug"]],
    ):
        if len(cand) == 1:
            return cand[0]
        if len(cand) > 1:
            f = [c for c in cand if mismo_equipo(equipo, c["equipo"])]
            if len(f) == 1:
                return f[0]
    toks = [t for t in q.split() if len(t) > 2]
    if toks:
        cand = [j for j in ff if toks[-1] in j["slug"].split()]
        f = [c for c in cand if mismo_equipo(equipo, c["equipo"])]
        if len(f) == 1:
            return f[0]
        if len(cand) == 1:
            return cand[0]
    return None


def inflexion(var):
    """Compara la variacion de 7 dias con la de 14 para detectar el giro."""
    v7, v14 = var.get("7"), var.get("14")
    if v7 is None or v14 is None:
        return "sin datos", 0.0
    if v7 > 0 and v14 > 0:
        return "subida sostenida", 0.15
    if v7 > 0 >= v14:
        return "girando al alza", 0.10
    if v7 < (v14 - v7):
        return "caida acelerando", -0.10
    return "caida frenando", -0.05


ORDEN = {"COMPRAR": 0, "ESPERAR": 1, "ESPECULATIVO": 2, "LOTERIA": 3, "RELLENO": 4, "NO COMPRAR": 5}


def evalua(m, j, mi_dinero, mis_posiciones):
    prob = j["probabilidad"] if j else None
    tend, ajuste = inflexion(j["var"]) if j else ("sin datos", 0.0)
    media = m.get("media_puntos")
    media = float(media) if media not in (None, "") else None
    valor = m["valor"]
    precio = m["precio_venta"] or valor
    estado = (m.get("estado") or "").lower()

    esperados = round(media * prob / 100, 1) if (media is not None and prob is not None) else None

    # Los entrenadores puntuan pero no salen en ninguna alineacion probable:
    # exigirles probabilidad los mandaria siempre al cajon de los dudosos.
    es_entrenador = (m.get("posicion") or "").lower().startswith("entrenador")
    titular = prob is None or prob >= 65

    if estado and estado != "ok":
        veredicto, razon, tope = "NO COMPRAR", f"estado oficial: {estado}", 0.0
    elif prob == 0:
        veredicto, razon, tope = "NO COMPRAR", "probabilidad 0%: no esta disponible", 0.0
    elif media is None:
        veredicto, razon, tope = "ESPECULATIVO", "sin historial de puntos", 1.00
    elif media < 2.5:
        veredicto, razon, tope = "NO COMPRAR", f"no puntua (media {media})", 0.0
    elif titular and media >= 5 and ajuste > 0:
        veredicto, razon, tope = "COMPRAR", "puntua y el valor sube", 1.0 + ajuste
    elif titular and media >= 5:
        veredicto, razon, tope = "ESPERAR", "bueno pero el valor cae: no pagues prima", 1.0
    else:
        veredicto, razon, tope = "RELLENO", "rotacion o puntuacion discreta", 1.0 + min(ajuste, 0)

    # Sin probabilidad el veredicto se sostiene solo en la media, que no ve
    # lesiones ni perdidas de titularidad recientes. Se avisa, no se degrada.
    incierto = prob is None and not es_entrenador

    tope_eur = round(valor * tope) if tope else 0
    # El vendedor fija un minimo: por debajo del precio de venta no hay puja posible.
    puja = max(tope_eur, 0)
    return {
        "id": m["id"],
        "nombre": m["nombre"],
        "posicion": m["posicion"],
        "equipo": j["equipo"] if j else None,
        "valor": valor,
        "precio_venta": precio,
        "media_puntos": media,
        "estado": m.get("estado"),
        "pujas": m.get("pujas"),
        "caduca": m.get("caduca"),
        "lo_vende": m.get("lo_vende"),
        # Los liga.json anteriores no traen vendedor_tipo: se deduce de lo_vende.
        "vendedor_tipo": m.get("vendedor_tipo") or ("manager" if m.get("lo_vende") else "liga"),
        "vendedor": m.get("vendedor") or m.get("lo_vende") or "LaLiga",
        "probabilidad": prob,
        "var_1d": j["var"].get("1") if j else None,
        "dif_1d": (j.get("dif") or {}).get("1") if j else None,
        "var_7d": j["var"].get("7") if j else None,
        "var_30d": j["var"].get("30") if j else None,
        "tendencia": tend,
        "jornada": j["jornada"] if j else None,
        "rival": j["rival"] if j else None,
        "puntos_esperados": esperados,
        "veredicto": veredicto,
        "razon": razon,
        "precio_max": puja,
        # Avisos que cambian la decision aunque el jugador sea bueno
        "te_cabe": puja <= mi_dinero if puja else True,
        "caro_de_salida": bool(puja and precio > puja),
        "posicion_cubierta": mis_posiciones.get(m["posicion"], 0) >= 2,
        "emparejado": bool(j),
        "sin_probabilidad": incierto,
        "es_entrenador": es_entrenador,
    }


# Cuando FutbolFantasy no publica probabilidad asumimos 70%, el mismo umbral que
# usamos para considerar titular a alguien. Queda anotado en cada fila afectada.
PROB_POR_DEFECTO = 70
LINEAS = {1: "portero", 2: "defensa", 3: "centrocampista", 4: "delantero", 5: "entrenador"}


def esperados(media, prob):
    if media is None:
        return None
    return round(media * (prob if prob is not None else PROB_POR_DEFECTO) / 100, 2)


def analiza_plantilla(mios, ff, equipos_reales, ofertas, prima_liga):
    """Enriquece tu plantilla y decide a quien conviene vender."""
    filas = []
    for p in mios:
        j = empareja(p["nombre"], equipos_reales.get(str(p.get("equipo_real", "")), ""), ff)
        if not j:  # la plantilla no trae el equipo real, asi que probamos sin filtro
            j = empareja(p["nombre"], "", ff)
        prob = j["probabilidad"] if j else None
        tend, ajuste = inflexion(j["var"]) if j else ("sin datos", 0.0)
        media = float(p["media_puntos"]) if p.get("media_puntos") not in (None, "") else None
        valor = p["valor"]
        estado = (p.get("estado") or "").lower()
        ofs = ofertas.get(p["id"], [])
        mejor = max((o["importe"] for o in ofs), default=None)
        prima_oferta = round((mejor / valor - 1) * 100, 1) if (mejor and valor) else None

        if estado and estado != "ok":
            accion, razon = "VENDER", f"estado oficial: {estado}"
        elif prob == 0:
            accion, razon = "VENDER", "no cuenta para su entrenador (0%)"
        elif media is not None and media < 2.5 and ajuste < 0:
            accion, razon = "VENDER", f"no puntua (media {media}) y el valor cae"
        elif ajuste <= -0.10 and (media is None or media < 5):
            accion, razon = "VENDER", "valor en caida acelerada sin rendimiento que lo sostenga"
        elif media is not None and media >= 5 and ajuste > 0:
            accion, razon = "MANTENER", "puntua y revaloriza"
        elif ajuste > 0:
            accion, razon = "MANTENER", "el valor sube: vender ahora es regalar la subida"
        else:
            accion, razon = "REVISAR", "ni claramente bueno ni claramente malo"

        # Una oferta por encima de la prima habitual de la liga es dinero gratis
        # aunque el jugador no sea un descarte.
        oferta_buena = bool(
            prima_oferta is not None and prima_liga is not None and prima_oferta > prima_liga + 5
        )
        if oferta_buena and accion != "MANTENER":
            accion, razon = "ACEPTAR OFERTA", f"te ofrecen un {prima_oferta:+.1f}% sobre su valor"

        filas.append({
            **p,
            "equipo": j["equipo"] if j else None,
            "probabilidad": prob,
            "var_7d": j["var"].get("7") if j else None,
            "var_30d": j["var"].get("30") if j else None,
            "tendencia": tend,
            "jornada": j["jornada"] if j else None,
            "rival": j["rival"] if j else None,
            "esperados": esperados(media, prob),
            "sin_probabilidad": prob is None and p.get("posicion_id") != 5,
            "ofertas": ofs,
            "mejor_oferta": mejor,
            "prima_oferta_pct": prima_oferta,
            "oferta_por_encima_del_mercado": oferta_buena,
            # Vender a un descarte esta bien, pero no a cualquier precio: si la
            # oferta no llega al valor, conviene listarlo y buscar puja.
            "oferta_baja": bool(prima_oferta is not None and prima_oferta < -2),
            "accion": accion,
            "razon_venta": razon,
        })
    orden = {"ACEPTAR OFERTA": 0, "VENDER": 1, "REVISAR": 2, "MANTENER": 3}
    filas.sort(key=lambda r: (orden.get(r["accion"], 9), -(r["mejor_oferta"] or 0)))
    return filas


def mejor_once(plantilla, formaciones):
    """Prueba cada formacion permitida y se queda con la de mas puntos esperados."""
    disponibles = [
        p for p in plantilla
        if (p.get("estado") or "ok").lower() == "ok" and p["probabilidad"] != 0
        and p["esperados"] is not None
    ]
    por_linea = {}
    for p in disponibles:
        por_linea.setdefault(p.get("posicion_id"), []).append(p)
    for v in por_linea.values():
        v.sort(key=lambda p: -p["esperados"])

    porteros, entrenadores = por_linea.get(1, []), por_linea.get(5, [])
    if not porteros:
        return None

    mejor = None
    for forma in formaciones:
        try:
            d, m, f = (int(x) for x in forma.split(","))
        except ValueError:
            continue
        lineas = {2: d, 3: m, 4: f}
        if any(len(por_linea.get(pid, [])) < n for pid, n in lineas.items()):
            continue  # no tienes jugadores para cubrirla
        once = [porteros[0]] + [p for pid, n in lineas.items() for p in por_linea[pid][:n]]
        total = sum(p["esperados"] for p in once)
        if entrenadores:
            once.append(entrenadores[0])
            total += entrenadores[0]["esperados"]
        if mejor is None or total > mejor["total"]:
            capitan = max(once, key=lambda p: p["esperados"])
            mejor = {
                "formacion": forma,
                "total": round(total, 1),
                "capitan": capitan["nombre"],
                "once": [
                    {k: p[k] for k in ("id", "nombre", "posicion", "posicion_id", "equipo",
                                       "media_puntos", "probabilidad", "esperados",
                                       "sin_probabilidad", "rival", "jornada")}
                    for p in once
                ],
            }
    if mejor:
        dentro = {p["id"] for p in mejor["once"]}
        mejor["banquillo"] = [
            {k: p[k] for k in ("id", "nombre", "posicion", "esperados", "probabilidad", "estado")}
            for p in plantilla if p["id"] not in dentro
        ]
    return mejor


def clausulazos(equipos, mi_team_id, mi_dinero, ff, ahora=None):
    """Jugadores de rivales cuya clausula te cabe en la caja.

    Los bloqueados NO se descartan: se marcan con la fecha en que se abren, que
    es justo lo que hace falta para preparar el golpe. Se ordenan los
    disponibles primero y, dentro de cada grupo, por puntos esperados.
    """
    ahora = ahora or datetime.now().astimezone()
    fuera = []
    for e in equipos:
        if e["team_id"] == mi_team_id:
            continue
        for p in e.get("jugadores", []):
            clausula = p.get("clausula") or 0
            if not clausula or p.get("escudo") or clausula > mi_dinero:
                continue
            bloqueo = p.get("clausula_bloqueada_hasta")
            bloqueada = False
            if bloqueo:
                try:
                    bloqueada = datetime.fromisoformat(bloqueo) > ahora
                except ValueError:
                    bloqueada = False
            j = empareja(p["nombre"], "", ff)
            prob = j["probabilidad"] if j else None
            if prob == 0 or (p.get("estado") or "ok").lower() != "ok":
                continue
            media = float(p["media_puntos"]) if p.get("media_puntos") not in (None, "") else None
            esp = esperados(media, prob)
            if esp is None or esp < 3:
                continue  # por debajo de 3 esperados no compensa vaciar la caja
            tend, _ = inflexion(j["var"]) if j else ("sin datos", 0.0)
            valor = p.get("valor") or 0
            fuera.append({
                "nombre": p["nombre"],
                "posicion": p.get("posicion"),
                "duenio": e["manager"],
                "equipo": j["equipo"] if j else None,
                "valor": valor,
                "clausula": clausula,
                "sobreprecio_pct": round((clausula / valor - 1) * 100, 1) if valor else None,
                "te_queda": round(mi_dinero - clausula),
                "media_puntos": media,
                "probabilidad": prob,
                "esperados": esp,
                "var_7d": j["var"].get("7") if j else None,
                "tendencia": tend,
                "jornada": j["jornada"] if j else None,
                "rival": j["rival"] if j else None,
                "sin_probabilidad": prob is None,
                "bloqueada": bloqueada,
                "disponible_desde": bloqueo if bloqueada else None,
            })
    # Disponibles primero; dentro de cada grupo, lo que mas puntos te da.
    fuera.sort(key=lambda r: (r["bloqueada"], -r["esperados"],
                              r["sobreprecio_pct"] if r["sobreprecio_pct"] is not None else 999))
    return fuera


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(SALIDA))
    args = ap.parse_args()

    if not LIGA.exists():
        sys.exit("Falta data/liga.json. Ejecuta antes: python sync.py")
    liga = json.loads(LIGA.read_text(encoding="utf-8"))

    refrescar = True
    if FF.exists():
        ff_doc = json.loads(FF.read_text(encoding="utf-8"))
        edad = datetime.now() - datetime.fromisoformat(ff_doc["actualizado"])
        # Con 12 h la "subida de hoy" podia ser la de ayer. Es una sola peticion por hora.
        refrescar = edad > timedelta(hours=1)
    if refrescar:
        print("Refrescando FutbolFantasy...", file=sys.stderr)
        jug = scrape.parse_mercado(scrape.get(scrape.MERCADO))
        ff_doc = {"actualizado": datetime.now().isoformat(timespec="seconds"), "jugadores": jug}
        FF.write_text(json.dumps(ff_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    ff = ff_doc["jugadores"]

    # Los equipos de LaLiga no cambian en toda la temporada: pedirlos en cada pase
    # era una llamada tirada. Se guardan un dia.
    cache_eq = DATA / "equipos.json"
    try:
        guardado = json.loads(cache_eq.read_text(encoding="utf-8"))
        if datetime.now() - datetime.fromisoformat(guardado["actualizado"]) > timedelta(days=1):
            raise ValueError("caducado")
        lista_equipos = guardado["equipos"]
    except (OSError, ValueError, KeyError):
        lista_equipos = api.equipos()
        cache_eq.write_text(json.dumps({"actualizado": datetime.now().isoformat(timespec="seconds"),
                                        "equipos": lista_equipos}, ensure_ascii=False), encoding="utf-8")
    equipos_reales = {str(t["id"]): t["name"] for t in lista_equipos}
    mi_dinero = liga["yo"]["dinero"]
    mios = next((e for e in liga["equipos"] if e["team_id"] == liga["yo"]["team_id"]), {})
    mis_posiciones = {}
    for p in mios.get("jugadores", []):
        mis_posiciones[p["posicion"]] = mis_posiciones.get(p["posicion"], 0) + 1

    plantilla = analiza_plantilla(
        mios.get("jugadores", []), ff, equipos_reales,
        liga.get("ofertas", {}), liga.get("prima_media_liga_pct"),
    )
    once = mejor_once(plantilla, liga["yo"].get("formaciones_permitidas") or [])
    golpes = clausulazos(liga["equipos"], liga["yo"]["team_id"], mi_dinero, ff)

    filas = []
    for m in liga["mercado"]:
        j = empareja(m["nombre"], equipos_reales.get(str(m["equipo_real"]), ""), ff)
        filas.append(evalua(m, j, mi_dinero, mis_posiciones))
    # Sin probabilidad no hay puntos esperados; se ordena por media para que un
    # buen jugador sin dato no caiga al fondo de su propio cajon.
    filas.sort(key=lambda r: (ORDEN.get(r["veredicto"], 9),
                              -(r["puntos_esperados"] if r["puntos_esperados"] is not None
                                else (r["media_puntos"] or 0))))

    doc = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "liga": liga["liga"],
        "yo": liga["yo"],
        "equipos": liga["equipos"],
        "alertas_clausula": liga["alertas_clausula"],
        "prima_media_liga_pct": liga.get("prima_media_liga_pct"),
        "mi_plantilla": plantilla,
        "once_optimo": once,
        "clausulazos": golpes,
        "mercado": filas,
        "sin_emparejar": [r["nombre"] for r in filas if not r["emparejado"]],
    }
    Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    eur = lambda x: f"{x:,.0f}".replace(",", ".") if x else "-"
    print(f"\n{liga['liga']['nombre']} — {liga['yo']['manager']}   Dinero: {eur(mi_dinero)}\n")
    cab = f"{'JUGADOR':<20} {'POS':<11} {'VALOR':>12} {'PIDEN':>12} {'7d':>7} {'PRB':>4} {'MED':>5} {'ESP':>5}  {'VEREDICTO':<12} {'MAXIMO':>12}"
    print(cab)
    print("-" * len(cab))
    for r in filas[:18]:
        v7 = f"{r['var_7d']:+.1f}%" if r["var_7d"] is not None else "   n/a"
        pr = f"{r['probabilidad']}%" if r["probabilidad"] is not None else " s/d"
        me = f"{r['media_puntos']:.1f}" if r["media_puntos"] is not None else "  -"
        es = f"{r['puntos_esperados']:.1f}" if r["puntos_esperados"] is not None else "  -"
        flag = "" if r["te_cabe"] else "  (no te cabe)"
        print(f"{(r['nombre'] or '?')[:20]:<20} {(r['posicion'] or '')[:11]:<11} {eur(r['valor']):>12} "
              f"{eur(r['precio_venta']):>12} {v7:>7} {pr:>4} {me:>5} {es:>5}  {r['veredicto']:<12} "
              f"{eur(r['precio_max']):>12}{flag}")
    if doc["sin_emparejar"]:
        print(f"\n[!] sin datos de tendencia: {', '.join(doc['sin_emparejar'])}")
    print(f"\n-> {args.json}")


if __name__ == "__main__":
    main()

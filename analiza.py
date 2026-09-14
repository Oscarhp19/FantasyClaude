#!/usr/bin/env python3
"""Analiza los jugadores de tu mercado diario y recomienda precio maximo de puja.

Uso:
    python analiza.py Dmitrovic "Marcos Alonso" Yeremay Pedrosa
    python analiza.py -f mercado_hoy.txt
    python analiza.py -f mercado_hoy.txt --saldo 12000000 --json informe.json

Si data/mercado.json tiene mas de 12 horas, lo refresca solo.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from difflib import get_close_matches
from pathlib import Path

import scrape  # reutiliza get(), slug(), parse_puntos(), parse_noticias()

DATA = Path(__file__).parent / "data"
MERCADO_JSON = DATA / "mercado.json"
DETALLE = f"{scrape.BASE}/analytics/laliga-fantasy/mercado/detalle/{{}}"
FICHA = f"{scrape.BASE}/jugadores/{{}}"
CADUCIDAD_H = 12
PAUSA = 1.5  # segundos entre peticiones: FutbolFantasy corta con 429 si vas rapido

# Palabras que, en un titular reciente, avisan de problema fisico o disciplinario
ALERTAS = re.compile(
    r"lesi[oó]n|lesionad|baja|al margen|duda|sancion|expulsad|roja|molestias|"
    r"enfermer|operad|recupera|no viaja|no convocad",
    re.I,
)


def carga_mercado(force=False):
    if MERCADO_JSON.exists() and not force:
        d = json.loads(MERCADO_JSON.read_text(encoding="utf-8"))
        edad = datetime.now() - datetime.fromisoformat(d["actualizado"])
        if edad < timedelta(hours=CADUCIDAD_H):
            return d, edad
    print("Mercado caducado o ausente: refrescando...", file=sys.stderr)
    jug = scrape.parse_mercado(scrape.get(scrape.MERCADO))
    if not jug:
        sys.exit("ERROR: no se pudo leer el mercado de FutbolFantasy.")
    d = {"actualizado": datetime.now().isoformat(timespec="seconds"), "jugadores": jug}
    DATA.mkdir(parents=True, exist_ok=True)
    MERCADO_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d, timedelta(0)


def busca(nombre, jugadores):
    """Devuelve (match, ambiguos). Prioriza igualdad exacta, luego 'empieza por',
    luego subcadena, y como ultimo recurso similitud difusa."""
    q = scrape.slug(nombre)
    exactos = [j for j in jugadores if j["slug"] == q]
    if len(exactos) == 1:
        return exactos[0], []

    # por apellido/token: "dmitrovic" -> "marko dmitrovic"
    tokens = [j for j in jugadores if q in j["slug"].split()]
    if len(tokens) == 1:
        return tokens[0], []
    if len(tokens) > 1:
        return None, tokens

    subs = [j for j in jugadores if q in j["slug"]]
    if len(subs) == 1:
        return subs[0], []
    if len(subs) > 1:
        return None, subs

    cerca = get_close_matches(q, [j["slug"] for j in jugadores], n=4, cutoff=0.75)
    cands = [j for j in jugadores if j["slug"] in cerca]
    if len(cands) == 1:
        return cands[0], []
    return None, cands


def detalle_jugador(pid):
    """Puntos + noticias fechadas. Dos peticiones por jugador.

    Ninguna de las dos es critica: si FutbolFantasy falla seguimos con lo que
    haya, porque el veredicto ya se sostiene con los datos del mercado.
    """
    puntos, noticias = None, []
    try:
        puntos = scrape.parse_puntos(scrape.get(scrape.PUNTOS.format(pid)))
    except Exception as e:
        print(f"    aviso: sin puntuacion para id {pid} ({e})", file=sys.stderr)
    time.sleep(PAUSA)
    try:
        det = scrape.get(DETALLE.format(pid))
        m = re.search(r"/jugadores/([a-z0-9-]+)", det)
        if m:
            time.sleep(PAUSA)
            noticias = scrape.parse_noticias(scrape.get(FICHA.format(m.group(1))))
    except Exception as e:
        print(f"    aviso: sin noticias para id {pid} ({e})", file=sys.stderr)
    return puntos, noticias


def inflexion(var):
    """Compara la caida/subida de 7d con la de 14d para detectar el giro.
    Devuelve texto corto y un ajuste sobre el precio recomendado."""
    v7, v14 = var.get("7"), var.get("14")
    if v7 is None or v14 is None:
        return "sin datos", 0.0
    if v7 > 0 and v14 > 0:
        return "subida sostenida", 0.15
    if v7 > 0 >= v14:
        return "girando al alza", 0.10
    # la primera mitad de la quincena fue v14 - v7
    previa = v14 - v7
    if v7 < previa:
        return "caida acelerando", -0.10
    return "caida frenando", -0.05


def evalua(j, puntos, noticias):
    prob = j["probabilidad"]
    media = puntos["media_jugados"] if puntos and puntos.get("jugados") else None
    jugados = puntos["jugados"] if puntos else 0
    tend, ajuste = inflexion(j["var"])

    # puntos esperados = media cuando juega x probabilidad de jugar
    esperados = None
    if media is not None and prob is not None:
        esperados = round(media * prob / 100, 1)

    alertas = [n for n in noticias[:4] if ALERTAS.search(n["titulo"])]

    # --- veredicto ---
    if prob == 0:
        veredicto, razon, tope = "NO COMPRAR", "probabilidad 0%: no esta disponible", 0.0
    elif prob is None:
        veredicto, razon, tope = (
            "ESPECULATIVO",
            "sin probabilidad publicada: no esta en el once proyectado",
            1.00,
        )
    elif jugados <= 1:
        veredicto, razon, tope = (
            "LOTERIA",
            f"solo {jugados} partido(s) jugado(s): muestra insuficiente",
            1.00 + max(ajuste, 0),
        )
    elif media is not None and media < 2.5:
        veredicto, razon, tope = (
            "NO COMPRAR",
            f"juega pero no puntua (media {media})",
            0.0,
        )
    elif prob >= 65 and media is not None and media >= 5 and ajuste > 0:
        veredicto, razon, tope = "COMPRAR", "titular, puntua y el valor sube", 1.0 + ajuste
    elif prob >= 65 and media is not None and media >= 5:
        veredicto, razon, tope = (
            "ESPERAR",
            "buen jugador pero el valor cae: no pagues prima",
            1.0,
        )
    else:
        veredicto, razon, tope = "RELLENO", "rotacion o puntuacion discreta", 1.0 + min(ajuste, 0)

    precio = round(j["valor"] * tope) if j["valor"] and tope else 0
    return {
        "nombre": j["nombre"],
        "equipo": j["equipo"],
        "posicion": j["posicion"],
        "valor": j["valor"],
        "var_7d": j["var"].get("7"),
        "var_30d": j["var"].get("30"),
        "tendencia": tend,
        "probabilidad": prob,
        "jornada": j["jornada"],
        "rival": j["rival"],
        "partidos_jugados": jugados,
        "media_puntos": media,
        "puntos_esperados": esperados,
        "veredicto": veredicto,
        "razon": razon,
        "precio_max": precio,
        "alertas": [f"{n['fecha']} {n['titulo']}" for n in alertas],
    }


def eur(x):
    return f"{x:,.0f}".replace(",", ".") if x else "-"


ORDEN = {"COMPRAR": 0, "ESPERAR": 1, "ESPECULATIVO": 2, "LOTERIA": 3, "RELLENO": 4, "NO COMPRAR": 5}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nombres", nargs="*", help="jugadores del mercado de hoy")
    ap.add_argument("-f", "--fichero", help="fichero con un nombre por linea")
    ap.add_argument("--saldo", type=int, help="tu presupuesto, para avisar si te pasas")
    ap.add_argument("--json", help="volcar el informe a este fichero")
    ap.add_argument("--refresh", action="store_true", help="forzar descarga del mercado")
    args = ap.parse_args()

    nombres = list(args.nombres)
    if args.fichero:
        for linea in Path(args.fichero).read_text(encoding="utf-8").splitlines():
            linea = linea.split("#")[0].strip()
            if linea:
                nombres.append(linea)
    if not nombres:
        sys.exit("Dame nombres: python analiza.py Dmitrovic Yeremay   (o -f mercado_hoy.txt)")

    d, edad = carga_mercado(args.refresh)
    jugadores = d["jugadores"]
    print(f"Mercado de FutbolFantasy actualizado hace {int(edad.total_seconds() // 60)} min "
          f"({len(jugadores)} jugadores)\n", file=sys.stderr)

    informes, problemas = [], []
    for n in nombres:
        j, cands = busca(n, jugadores)
        if not j:
            if cands:
                opciones = ", ".join(f"{c['nombre']} ({c['equipo']})" for c in cands)
                problemas.append(f'"{n}" es ambiguo -> {opciones}')
            else:
                problemas.append(f'"{n}" no aparece en LaLiga')
            continue
        print(f"  consultando {j['nombre']}...", file=sys.stderr)
        try:
            puntos, noticias = detalle_jugador(j["id"])
        except Exception as e:
            problemas.append(f'"{n}" ({j["nombre"]}): fallo al consultar ficha -> {e}')
            continue
        informes.append(evalua(j, puntos, noticias))
        time.sleep(PAUSA)

    informes.sort(key=lambda r: (ORDEN.get(r["veredicto"], 9), -(r["puntos_esperados"] or 0)))

    print()
    cab = f"{'JUGADOR':<22} {'EQUIPO':<11} {'VALOR':>12} {'7d':>7} {'PROB':>5} {'MED':>5} {'ESP':>5}  {'VEREDICTO':<12} {'PUJA MAX':>12}"
    print(cab)
    print("-" * len(cab))
    for r in informes:
        v7 = f"{r['var_7d']:+.1f}%" if r["var_7d"] is not None else "   n/a"
        pr = f"{r['probabilidad']}%" if r["probabilidad"] is not None else "s/d"
        me = f"{r['media_puntos']:.1f}" if r["media_puntos"] is not None else "  -"
        es = f"{r['puntos_esperados']:.1f}" if r["puntos_esperados"] is not None else "  -"
        print(f"{r['nombre'][:22]:<22} {r['equipo'][:11]:<11} {eur(r['valor']):>12} {v7:>7} "
              f"{pr:>5} {me:>5} {es:>5}  {r['veredicto']:<12} {eur(r['precio_max']):>12}")

    print("\nDetalle:")
    for r in informes:
        print(f"\n  {r['nombre']} ({r['equipo']}, {r['posicion']})")
        print(f"    {r['veredicto']}: {r['razon']}")
        print(f"    Valor {eur(r['valor'])} | 7d {r['var_7d']:+.1f}% | 30d {r['var_30d']:+.1f}% | {r['tendencia']}")
        if r["jornada"]:
            print(f"    J{r['jornada']} vs {r['rival']}")
        for a in r["alertas"]:
            print(f"    [!] {a}")

    if args.saldo:
        compras = [r for r in informes if r["veredicto"] == "COMPRAR"]
        total = sum(r["precio_max"] for r in compras)
        print(f"\nSaldo {eur(args.saldo)} | pujas COMPRAR suman {eur(total)}", end="")
        print("  -> NO TE LLEGA, prioriza" if total > args.saldo else "  -> cabe")

    for p in problemas:
        print(f"\n[!] {p}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"generado": datetime.now().isoformat(timespec="seconds"),
                        "jugadores": informes, "problemas": problemas},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nInforme -> {args.json}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Descarga el dataset publico de FutbolFantasy y lo cachea en data/.

Uso:
    python scrape.py              # mercado + fichas de los jugadores que toquen
    python scrape.py --full       # ademas, ficha de puntuacion de TODOS (lento)

Genera:
    data/mercado.json   valor, variaciones, tendencia, probabilidad, rival
    data/puntos.json    historial de puntos por jornada (solo con --full o --ids)

Las noticias y los puntos del dia a dia los pide analiza.py bajo demanda,
solo para los jugadores de tu mercado.
"""
import argparse
import gzip
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

BASE = "https://www.futbolfantasy.com"
MERCADO = f"{BASE}/analytics/laliga-fantasy/mercado"
PUNTOS = f"{BASE}/analytics/laliga-fantasy/puntuacion/detalle/{{}}"
DATA = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


def get(url, retries=4):
    """GET con reintentos, backoff exponencial y descompresion gzip.

    FutbolFantasy responde 429 si le aprietas: en ese caso respetamos
    Retry-After si viene, y si no esperamos bastante mas que en un error normal.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "text/html,*/*"}
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""  # ficha inexistente: no es un fallo que reintentar
            if attempt == retries - 1:
                raise
            if e.code == 429:
                espera = int(e.headers.get("Retry-After") or 0) or 10 * (attempt + 1) ** 2
                print(f"    429: esperando {espera}s...", file=sys.stderr, flush=True)
                time.sleep(espera)
            else:
                time.sleep(3 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    return ""


def slug(s):
    """Normaliza un nombre para comparar: sin acentos, minusculas, sin puntuacion."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_mercado(html):
    """Extrae una fila por jugador con valores, variaciones y probabilidad."""
    out = []
    for row in re.findall(r'<tr class="elemento_jugador.*?</tr>', html, re.S):
        d = dict(re.findall(r'data-([a-z0-9-]+)="([^"]*)"', row))
        if "nombre" not in d or "id" not in d:
            continue
        eq = re.search(r"<span>([^<]+)</span>\s*</div>", row)
        rival = re.search(r'title="Jornada (\d+) &middot; Próximo rival: ([^"]+)"', row) or re.search(
            r'title="Jornada (\d+) · Próximo rival: ([^"]+)"', row
        )
        prob = re.search(r'class="prob-\d+"[^>]*>(\d+)%', row)
        out.append(
            {
                "id": d["id"],
                "nombre": d["nombre"],
                "slug": slug(d["nombre"]),
                "posicion": d.get("posicion", ""),
                "equipo": eq.group(1).strip() if eq else "",
                "valor": num(d.get("valor")),
                "var": {k: num(d.get(f"diferencia-pct{k}")) for k in ("1", "3", "7", "14", "30")},
                # Lo mismo en euros: es la cifra que FutbolFantasy destaca como "subida hoy".
                "dif": {k: num(d.get(f"diferencia{k}")) for k in ("1", "3", "7", "14", "30")},
                "tendencia": num(d.get("tendencia")),
                "aceleracion": num(d.get("aceleracion")),
                "jornada": int(rival.group(1)) if rival else None,
                "rival": rival.group(2) if rival else None,
                # None = sin dato publicado (no es lo mismo que 0%)
                "probabilidad": int(prob.group(1)) if prob else None,
            }
        )
    return out


def parse_puntos(html):
    """Historial de puntos por jornada desde la ficha de puntuacion."""
    if not html.strip():
        return None
    pares = re.findall(r'puntos\.push\(\{jornada: "J(\d+)", value: "(-?\d+)" \}\)', html)
    if not pares:
        return None
    # ordenamos por jornada: el HTML las trae desordenadas si hubo aplazamientos
    pts = sorted(((int(j), int(v)) for j, v in pares), key=lambda x: x[0])
    jugados = len(re.findall(r"partidos_jugados\+=1", html))
    convocados = len(re.findall(r"partidos_convocado\+=1", html))
    total = sum(v for _, v in pts)
    return {
        "por_jornada": [{"jornada": j, "puntos": v} for j, v in pts],
        "jugados": jugados,
        "convocados": convocados,
        "total": total,
        "media_jugados": round(total / jugados, 2) if jugados else None,
    }


def parse_noticias(html, limit=8):
    """Titulares con fecha dd/mm. Infiere el anho: si el dd/mm aun no ha
    ocurrido este anho, la noticia es del anho pasado."""
    pat = re.compile(
        r'<div class="date mr-1"[^>]*>(\d\d)/(\d\d)</div>.*?'
        r'href="[^"]*?/noticias/\d+-[a-z0-9-]+">([^<]{8,160})',
        re.S,
    )
    hoy = date.today()
    vistos, out = set(), []
    for dd, mm, titulo in pat.findall(html):
        titulo = re.sub(r"\s+", " ", titulo).strip()
        if titulo in vistos:
            continue
        vistos.add(titulo)
        try:
            d = date(hoy.year, int(mm), int(dd))
        except ValueError:
            continue
        if d > hoy:
            d = d.replace(year=hoy.year - 1)
        out.append({"fecha": d.isoformat(), "titulo": titulo})
        if len(out) >= limit:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="fichas de todos los jugadores")
    ap.add_argument("--ids", nargs="*", help="solo estos ids de jugador")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)

    print("Descargando mercado...", flush=True)
    jugadores = parse_mercado(get(MERCADO))
    if not jugadores:
        sys.exit("ERROR: 0 jugadores. La web habra cambiado de formato; revisa parse_mercado().")
    payload = {"actualizado": datetime.now().isoformat(timespec="seconds"), "jugadores": jugadores}
    (DATA / "mercado.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  {len(jugadores)} jugadores -> data/mercado.json")

    if args.ids:
        objetivo = [j for j in jugadores if j["id"] in set(args.ids)]
    elif args.full:
        objetivo = jugadores
    else:
        print("  (sin --full ni --ids: no descargo fichas de puntuacion)")
        return

    print(f"Descargando {len(objetivo)} fichas de puntuacion...", flush=True)
    puntos = {}
    for i, j in enumerate(objetivo, 1):
        try:
            puntos[j["id"]] = parse_puntos(get(PUNTOS.format(j["id"])))
        except Exception as e:
            print(f"  aviso: {j['nombre']} fallo ({e})")
            puntos[j["id"]] = None
        if i % 25 == 0:
            print(f"  {i}/{len(objetivo)}", flush=True)
        time.sleep(0.25)  # cortesia con el servidor

    (DATA / "puntos.json").write_text(
        json.dumps(puntos, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  -> data/puntos.json ({sum(1 for v in puntos.values() if v)} con datos)")


if __name__ == "__main__":
    main()

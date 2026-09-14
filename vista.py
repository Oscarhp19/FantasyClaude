#!/usr/bin/env python3
"""Genera la vista HTML del informe, con los datos incrustados.

    python sync.py && python informe.py && python vista.py

La pagina es autonoma: no pide nada al servidor, asi que se puede abrir en
local o publicar tal cual.
"""
import json
import sys
from pathlib import Path

AQUI = Path(__file__).parent
PLANTILLA = AQUI / "vista_plantilla.html"
INFORME = AQUI / "data" / "informe.json"
SALIDA = AQUI / "vista.html"          # para publicar como artifact (sin <head>)
SALIDA_LOCAL = AQUI / "vista_local.html"  # para servidor.py (documento completo)

# Al publicar como artifact, claude.ai envuelve el fichero en su propio
# <head> con charset y viewport. Servido en local no hay nadie que lo haga, y
# sin viewport iOS renderiza a 980 px de ancho y el diseno movil no se activa.
ENVOLTORIO = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<!-- Lleva tu plantilla y tu dinero: que no acabe en un buscador. -->
<meta name="robots" content="noindex, nofollow">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Bernuy">
<style>html{-webkit-text-size-adjust:100%}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head>
<body>
{contenido}
</body>
</html>
"""


def main():
    if not INFORME.exists():
        sys.exit("Falta data/informe.json. Ejecuta antes: python sync.py && python informe.py")
    datos = json.loads(INFORME.read_text(encoding="utf-8"))
    html = PLANTILLA.read_text(encoding="utf-8")

    # El JSON va dentro de un <script type="application/json">, asi que lo unico
    # que puede romperlo es un "</script>" literal dentro de un dato.
    blob = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    if "__DATOS__" not in html:
        sys.exit("La plantilla ha perdido el marcador __DATOS__.")
    pagina = html.replace("__DATOS__", blob)
    SALIDA.write_text(pagina, encoding="utf-8")
    SALIDA_LOCAL.write_text(ENVOLTORIO.replace("{contenido}", pagina), encoding="utf-8")

    print(f"{len(datos.get('mercado', []))} jugadores, "
          f"{len(datos.get('alertas_clausula', []))} alertas de clausula, "
          f"{len(datos.get('clausulazos', []))} clausulazos")
    print(f"-> {SALIDA.name} (artifact) y {SALIDA_LOCAL.name} (servidor)")


if __name__ == "__main__":
    main()

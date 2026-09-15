#!/usr/bin/env python3
"""Guarda y recupera, cifrado, el estado que el robot necesita entre ejecuciones.

    python estado_ci.py cierra   # data/ -> estado.bin (al final del workflow)
    python estado_ci.py abre     # estado.bin -> data/ (al principio)

Sin esto cada ejecucion empieza de cero: inicia sesion con contrasena y lo pide
todo a la API. Con esto reutiliza la sesion y solo pide lo que ha cambiado.

Por que cifrado: el repositorio es publico, y la cache de Actions la puede leer
un workflow lanzado desde un pull request de un fork. Esos workflows no reciben
los secretos, asi que sin LALIGA_PASSWORD y RUTA_SECRETA no hay forma de abrirlo.
"""
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).parent
DATA = AQUI / "data"
PAQUETE = AQUI / "estado.bin"
# tokens: la sesion. cache_api: lo que no hace falta volver a pedir.
# mercado y equipos: las caches de FutbolFantasy y de la lista de equipos.
FICHEROS = ["tokens.json", "cache_api.json", "mercado.json", "equipos.json"]


def clave():
    pw = os.environ.get("LALIGA_PASSWORD", "")
    ruta = os.environ.get("RUTA_SECRETA", "")
    if not pw or not ruta:
        sys.exit("Faltan LALIGA_PASSWORD o RUTA_SECRETA en el entorno.")
    # scrypt y no un hash suelto: la contrasena puede ser corta.
    return hashlib.scrypt(f"{pw}|{ruta}".encode(), salt=b"fantasy-estado-v1",
                          n=2 ** 14, r=8, p=1, dklen=32)


def cierra():
    from nacl.secret import SecretBox

    contenido = {}
    for nombre in FICHEROS:
        f = DATA / nombre
        if f.exists():
            contenido[nombre] = base64.b64encode(f.read_bytes()).decode()
    if "tokens.json" not in contenido:
        print("Sin sesion que guardar: no se crea paquete.")
        return
    cifrado = SecretBox(clave()).encrypt(json.dumps(contenido).encode())
    PAQUETE.write_bytes(bytes(cifrado))
    print(f"Estado guardado ({', '.join(contenido)}; {len(cifrado) // 1024} KB cifrados).")


def abre():
    from nacl.exceptions import CryptoError
    from nacl.secret import SecretBox

    if not PAQUETE.exists():
        print("No hay estado anterior: se empieza de cero.")
        return
    try:
        contenido = json.loads(SecretBox(clave()).decrypt(PAQUETE.read_bytes()))
    except (CryptoError, ValueError):
        # Pasa si has cambiado la contrasena o la ruta: no es un error, se
        # inicia sesion de nuevo y el siguiente paquete ya usa la clave nueva.
        print("El estado guardado no se puede abrir con los secretos actuales: se empieza de cero.")
        return
    DATA.mkdir(parents=True, exist_ok=True)
    for nombre, b64 in contenido.items():
        if nombre in FICHEROS:  # nunca escribir fuera de la lista
            (DATA / nombre).write_bytes(base64.b64decode(b64))
    print(f"Estado recuperado: {', '.join(contenido)}.")


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    if accion == "cierra":
        cierra()
    elif accion == "abre":
        abre()
    else:
        print(__doc__)

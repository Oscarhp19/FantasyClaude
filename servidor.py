#!/usr/bin/env python3
"""Sirve el panel en tu red local y lo mantiene al dia.

    python servidor.py                # puerto 8000, refresco cada 2 min
    python servidor.py --puerto 8080 --cada 30

Da lo que una pagina publicada no puede dar: un boton que rehace los datos de
verdad, y un refresco automatico. Al arrancar imprime la direccion que tienes
que abrir en el movil, que debe estar en la misma red que este ordenador.
"""
import argparse
import json
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Sin esto Windows retiene la salida en el buffer y arrancas sin ver la URL.
sys.stdout.reconfigure(line_buffering=True)

AQUI = Path(__file__).parent
# El documento completo, con viewport: el otro es el fragmento del artifact.
VISTA = AQUI / "vista_local.html"
PASOS = ["sync.py", "informe.py", "vista.py"]

estado = {
    "actualizando": False,
    "ultimo_ok": None,
    "ultimo_error": None,
    "duracion_s": None,
}
cerrojo = threading.Lock()


def ip_local():
    """La IP de este equipo en la red local. El socket no llega a enviar nada."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def actualiza():
    """Ejecuta el pipeline. Un solo pase a la vez."""
    with cerrojo:
        if estado["actualizando"]:
            return False
        estado["actualizando"] = True
    inicio = time.time()
    try:
        for paso in PASOS:
            r = subprocess.run(
                [sys.executable, str(AQUI / paso)],
                capture_output=True, text=True, cwd=str(AQUI), timeout=900,
            )
            if r.returncode != 0:
                cola = (r.stderr or r.stdout or "").strip().splitlines()
                estado["ultimo_error"] = f"{paso}: {cola[-1] if cola else 'fallo sin mensaje'}"
                print(f"[{datetime.now():%H:%M:%S}] ERROR en {paso}: {estado['ultimo_error']}")
                return False
        estado["ultimo_ok"] = datetime.now().isoformat(timespec="seconds")
        estado["ultimo_error"] = None
        estado["duracion_s"] = round(time.time() - inicio)
        print(f"[{datetime.now():%H:%M:%S}] actualizado en {estado['duracion_s']}s")
        return True
    except subprocess.TimeoutExpired:
        estado["ultimo_error"] = "el pipeline ha tardado demasiado"
        return False
    except Exception as e:  # noqa: BLE001 - el servidor no debe caerse por esto
        estado["ultimo_error"] = str(e)
        return False
    finally:
        estado["actualizando"] = False


def bucle(minutos):
    while True:
        time.sleep(minutos * 60)
        print(f"[{datetime.now():%H:%M:%S}] refresco automatico...")
        actualiza()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # sin ruido de peticiones

    def _envia(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos = cuerpo if isinstance(cuerpo, bytes) else cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        # La pagina se regenera entera: que el movil no sirva una copia vieja.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta in ("/", "/index.html"):
            if not VISTA.exists():
                return self._envia(503, "<h1>Aun no hay datos</h1>"
                                        "<p>Ejecuta: python sync.py && python informe.py "
                                        "&& python vista.py</p>", "text/html; charset=utf-8")
            return self._envia(200, VISTA.read_bytes(), "text/html; charset=utf-8")
        if ruta == "/estado":
            return self._envia(200, json.dumps(estado))
        self._envia(404, json.dumps({"error": "no existe"}))

    def do_POST(self):
        if self.path.split("?")[0] != "/actualizar":
            return self._envia(404, json.dumps({"error": "no existe"}))
        if estado["actualizando"]:
            return self._envia(409, json.dumps({"error": "ya se esta actualizando", **estado}))
        threading.Thread(target=actualiza, daemon=True).start()
        self._envia(202, json.dumps({"lanzado": True}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--cada", type=int, default=2, help="minutos entre refrescos")
    ap.add_argument("--sin-refresco", action="store_true")
    args = ap.parse_args()

    if not VISTA.exists():
        print("No hay vista.html todavia: genero los datos antes de arrancar...")
        actualiza()

    if not args.sin_refresco:
        threading.Thread(target=bucle, args=(args.cada,), daemon=True).start()

    # Enlazamos ANTES de anunciar nada: si el puerto esta pillado por otra copia
    # del servidor, lo normal seria imprimir la direccion y morir despues, y te
    # quedarias mirando datos viejos servidos por el proceso anterior.
    try:
        servidor = ThreadingHTTPServer(("0.0.0.0", args.puerto), Handler)
    except OSError as e:
        sys.exit(
            f"No se pudo abrir el puerto {args.puerto}: {e}\n"
            f"Casi seguro que ya tienes otro servidor.py corriendo. Cierralo, o usa "
            f"--puerto con otro numero."
        )

    ip = ip_local()
    print(f"\n  Panel servido en:")
    print(f"    este equipo   http://localhost:{args.puerto}")
    print(f"    iPhone / iPad http://{ip}:{args.puerto}   (misma red)")
    if not args.sin_refresco:
        print(f"\n  Refresco automatico cada {args.cada} min. Ctrl+C para parar.")
    if estado["ultimo_ok"]:
        print(f"  Ultimos datos: {estado['ultimo_ok']}")
    print()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")


if __name__ == "__main__":
    main()

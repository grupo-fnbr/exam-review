"""Arranque: python -m corrector  (abre el navegador en http://127.0.0.1:5050)."""

import argparse
import threading
import webbrowser

from .web import crear_app


def main():
    parser = argparse.ArgumentParser(description="Corrector de actividades de evaluación continua")
    parser.add_argument("--puerto", type=int, default=5050)
    parser.add_argument("--datos", help="Ruta del fichero cifrado (por defecto ~/.corrector-aec/datos.enc)")
    parser.add_argument("--sin-navegador", action="store_true")
    args = parser.parse_args()
    app = crear_app(args.datos)
    url = f"http://127.0.0.1:{args.puerto}/"
    if not args.sin_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Corrector AEC en {url}  (Ctrl+C para cerrar)")
    # Solo escucha en este ordenador; un único hilo porque los datos viven en memoria.
    app.run(host="127.0.0.1", port=args.puerto, debug=False, threaded=False, use_reloader=False)


if __name__ == "__main__":
    main()

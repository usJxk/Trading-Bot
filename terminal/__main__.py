import argparse
import os

from waitress import create_server

from .web import create_app


def main():
    parser = argparse.ArgumentParser(description="Abre la interfaz local de Trading-Bot.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Usa un puerto entre 1024 y 65535.")
    if os.name == "posix":
        os.umask(0o077)
    app = create_app()
    server = create_server(app, host="127.0.0.1", port=args.port, threads=4,
                           max_request_body_size=12 * 1024, expose_tracebacks=False)
    print(f"Trading-Bot está disponible en http://127.0.0.1:{args.port}", flush=True)
    server.run()


if __name__ == "__main__":
    main()

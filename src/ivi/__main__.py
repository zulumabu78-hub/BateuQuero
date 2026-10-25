"""Start the local app without an external account or an AI download."""

from __future__ import annotations

import argparse
import uvicorn

from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="I.V.I. — assistente pessoal local")
    parser.add_argument("--port", type=int, help="Porta local (padrão: 8765).")
    args = parser.parse_args()
    settings = Settings.from_env()
    port = args.port if args.port is not None else settings.port
    if not 1024 <= port <= 65535:
        parser.error("A porta deve estar entre 1024 e 65535.")
    from .app import create_app

    print(f"I.V.I. iniciando em http://127.0.0.1:{port} — pressione Ctrl+C para sair.")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, ws_max_size=2_000_000)


if __name__ == "__main__":
    main()

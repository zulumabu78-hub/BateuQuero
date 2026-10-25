"""Open the local Windows assistant as a fullscreen application window."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import webbrowser

from . import __version__
from .config import Settings


def _local_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("A janela da I.V.I. só pode abrir seu servidor HTTP local.")
    if parsed.port is not None and not 1024 <= parsed.port <= 65535:
        raise ValueError("Porta local inválida.")
    return url.rstrip("/")


def find_browser() -> Path | None:
    """Find only standard Edge/Chrome installations, with no shell search."""
    bases = [
        Path(value)
        for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")
        if (value := os.environ.get(key))
    ]
    for vendor in (Path("Microsoft/Edge/Application/msedge.exe"), Path("Google/Chrome/Application/chrome.exe")):
        for base in bases:
            candidate = base / vendor
            if candidate.is_file():
                return candidate
    return None


def build_browser_command(executable: Path, url: str, profile: Path) -> list[str]:
    return [
        str(executable),
        f"--app={_local_url(url)}",
        "--start-fullscreen",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
    ]


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def read_server_status(url: str) -> dict | None:
    url = _local_url(url)
    # This client is strictly loopback-only; a corporate HTTP proxy must not
    # receive the local assistant's status requests.
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirects())
        with opener.open(url + "/api/status", timeout=0.8) as response:
            if response.status != 200:
                return None
            payload = response.read(65537)
            if len(payload) > 65536:
                return None
            status = json.loads(payload)
            return status if isinstance(status, dict) else None
    except (URLError, OSError, ValueError):
        return None


def server_ready(url: str) -> bool:
    status = read_server_status(url)
    return bool(status and status.get("name") == "I.V.I." and status.get("version") == __version__)


def _port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _stop_owned_server(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def launch(settings: Settings) -> int:
    if sys.platform != "win32":
        raise RuntimeError("O atalho de aplicativo é para Windows. Neste sistema, inicie com python -m ivi e use o botão Tela cheia.")
    url = f"http://127.0.0.1:{settings.port}"
    existing = read_server_status(url)
    if existing and (existing.get("name") != "I.V.I." or existing.get("version") != __version__):
        raise RuntimeError("Há outra versão ou serviço aberto nessa porta. Feche a I.V.I. anterior no PowerShell com Ctrl+C e abra INICIAR-IVI.cmd novamente.")
    if not existing and not _port_available(settings.port):
        raise RuntimeError(f"A porta {settings.port} já está ocupada. Feche o servidor anterior antes de abrir esta versão.")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    profile = settings.data_dir / "browser"
    owned = None
    try:
        if not existing:
            log_path = settings.data_dir / "desktop-server.log"
            with log_path.open("ab") as log:
                owned = subprocess.Popen(
                    [sys.executable, "-m", "ivi", "--port", str(settings.port)],
                    cwd=str(Path.cwd()),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            deadline = time.monotonic() + 20
            while not server_ready(url):
                if owned.poll() is not None:
                    raise RuntimeError(f"O servidor não iniciou. Confira {log_path}.")
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"O servidor demorou para iniciar. Confira {log_path}.")
                time.sleep(0.2)
        browser = find_browser()
        opened = False
        if browser:
            try:
                subprocess.Popen(build_browser_command(browser, url, profile), shell=False, close_fds=True)
                opened = True
            except OSError:
                print("Não consegui abrir a janela do aplicativo; tentando o navegador padrão.")
        if not opened:
            if not webbrowser.open(url, new=1):
                raise RuntimeError(f"Não consegui abrir o navegador. Abra {url} manualmente.")
            print("Use o botão Tela cheia da I.V.I. ou pressione F11.")
        print("I.V.I. aberta neste computador. F11 alterna a tela cheia do navegador.")
        if owned:
            print("Mantenha esta janela aberta. Para encerrar o servidor, pressione Ctrl+C.")
            returncode = owned.wait()
            return 0 if returncode in {0, None} else 1
        print("O servidor que já estava aberto foi reutilizado.")
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if owned:
            _stop_owned_server(owned)


def main() -> int:
    try:
        return launch(Settings.from_env())
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"I.V.I.: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

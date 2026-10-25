"""Small allowlist of desktop actions; parsing never performs an action."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from urllib.parse import quote, urlsplit
import webbrowser


@dataclass(frozen=True)
class ToolRequest:
    name: str
    title: str
    description: str
    arguments: dict[str, str]


APP_NAMES = {
    "calculator": "Calculadora",
    "notepad": "Bloco de Notas",
    "spotify": "Spotify",
    "browser": "navegador",
}
APP_ALIASES = {
    "calculadora": "calculator",
    "calc": "calculator",
    "bloco de notas": "notepad",
    "notepad": "notepad",
    "spotify": "spotify",
    "navegador": "browser",
    "browser": "browser",
}
URL_HOSTS = frozenset({
    "google.com", "www.google.com", "open.spotify.com", "youtube.com",
    "www.youtube.com", "pt.wikipedia.org", "en.wikipedia.org", "github.com",
    "www.github.com",
})


def _normalize(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn").lower()


def validate_url(url: str) -> str:
    """Validate the exact host allowlist and HTTP(S), refusing local/file URLs."""
    if not isinstance(url, str) or len(url) > 2048 or any(ord(char) <= 32 for char in url):
        raise ValueError("Endereço inválido.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Endereço inválido.") from error
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in URL_HOSTS
            or parsed.username is not None or parsed.password is not None
            or port not in {None, 80, 443}):
        raise ValueError("Este endereço não está na lista de sites permitidos.")
    return url


def _spotify_request(query: str) -> ToolRequest | None:
    query = re.sub(r"^(?:uma?\s+)?m[uú]sicas?\s+(?:da|do|de)\s+", "", query.strip(), flags=re.IGNORECASE)
    if not query or len(query) > 300 or any(ord(char) < 32 for char in query):
        return None
    return ToolRequest(
        "spotify_search", f"Pesquisar {query} no Spotify",
        f"Abrir a busca por “{query}” no Spotify. A reprodução será escolhida por você.",
        {"query": query},
    )


def parse_tool_request(text: str) -> ToolRequest | None:
    """Recognize explicit Portuguese requests, not arbitrary executable commands."""
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        return None
    text = re.sub(r"^(?:i\.?\s*v\.?\s*i\.?)[,:\s]+", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"[, ]+por favor[.!?]*$", "", text, flags=re.IGNORECASE).rstrip(".!? ")
    spotify = re.fullmatch(
        r"(?:abre|abra|abrir)\s+(?:o\s+)?spotify\s+e\s+"
        r"(?:coloca|coloque|toca|toque|reproduza?|busca|busque|procura|procure)\s+(.+)",
        text, flags=re.IGNORECASE,
    )
    if not spotify:
        spotify = re.fullmatch(
            r"(?:pesquisa|pesquise|busca|busque|procura|procure|coloca|coloque|toca|toque)\s+(.+?)\s+no\s+spotify",
            text, flags=re.IGNORECASE,
        )
    if spotify:
        return _spotify_request(spotify.group(1))

    opening = re.fullmatch(r"(?:abre|abra|abrir)\s+(?:(?:o|a|um|uma)\s+)?(.+)", text, flags=re.IGNORECASE)
    if not opening:
        return None
    target = opening.group(1).strip()
    app = APP_ALIASES.get(_normalize(target))
    if app:
        title = f"Abrir {APP_NAMES[app]}"
        return ToolRequest("open_app", title, f"{title} neste computador Windows.", {"app": app})
    try:
        url = validate_url(target)
    except ValueError:
        return None
    return ToolRequest("open_url", f"Abrir {urlsplit(url).hostname}", f"Abrir {url} no navegador padrão.", {"url": url})


class ToolRegistry:
    """Execute only after the caller receives explicit user confirmation.

    This intentionally cannot control a Windows desktop from a remote Linux
    cloud machine. It acts on the machine where the Python server is running.
    """

    def __init__(self, platform: str | None = None):
        self.platform = sys.platform if platform is None else platform

    def execute(self, request: ToolRequest) -> str:
        if not isinstance(request, ToolRequest):
            raise ValueError("Solicitação de ferramenta inválida.")
        if self.platform != "win32":
            raise RuntimeError("O controle de aplicativos só funciona quando a I.V.I. está rodando no seu Windows; esta instância não controla o seu PC.")

        if request.name == "open_app" and set(request.arguments) == {"app"}:
            app = request.arguments["app"]
            if app not in APP_NAMES:
                raise ValueError("Aplicativo não permitido.")
            if app in {"calculator", "notepad"}:
                executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / {"calculator": "calc.exe", "notepad": "notepad.exe"}[app]
                subprocess.Popen([str(executable)], shell=False, close_fds=True)
            elif app == "spotify":
                try:
                    os.startfile("spotify:")  # type: ignore[attr-defined]
                except (OSError, AttributeError) as error:
                    raise RuntimeError("Não foi possível abrir o Spotify. Confira se o aplicativo está instalado no Windows.") from error
            else:
                self._open_url("https://www.google.com/")
            return f"Solicitei a abertura de {APP_NAMES[app]}."

        if request.name == "spotify_search" and set(request.arguments) == {"query"}:
            parsed = _spotify_request(request.arguments["query"])
            if parsed is None:
                raise ValueError("Busca do Spotify inválida.")
            query = parsed.arguments["query"]
            self._open_url(f"https://open.spotify.com/search/{quote(query, safe='')}")
            return f"Abri a busca por “{query}” no Spotify. Escolha a faixa para reproduzir."

        if request.name == "open_url" and set(request.arguments) == {"url"}:
            self._open_url(request.arguments["url"])
            return "Solicitei a abertura do endereço no navegador."
        raise ValueError("Ferramenta ou argumentos não permitidos.")

    @staticmethod
    def _open_url(url: str) -> None:
        url = validate_url(url)
        if not webbrowser.open(url, new=2):
            raise RuntimeError("O navegador não confirmou a abertura do endereço.")

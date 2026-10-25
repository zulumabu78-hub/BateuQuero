"""Instalacao explicita de conversa local; sem compilador ou APIs de inferencia."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
import zipfile

from .download_models import SPECS


ENGINE_TAG = "b11869"
ENGINE_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11869/llama-b11869-bin-win-cpu-x64.zip"
# GitHub release-asset digest, independently matched to the official ZIP.
ENGINE_SHA256 = "68bbb8f833d6b623386d50f958af8cf5d9f4b39897ba8ab79b9b294093304891"
ENGINE_SOURCE = "https://github.com/ggml-org/llama.cpp/releases/expanded_assets/b11869"
VC_RUNTIME_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
MAX_DOWNLOAD_BYTES = 700 * 1024 * 1024
Progress = Callable[[dict], None]


class BootstrapError(RuntimeError):
    pass


class BootstrapCancelled(BootstrapError):
    pass


class HTTPSOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.lower() != "https":
            raise BootstrapError("O provedor tentou redirecionar para uma conexao sem HTTPS; nenhuma requisicao foi enviada ao destino inseguro.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def conversation_setup_capability() -> dict:
    supported = sys.platform == "win32" and struct.calcsize("P") == 8 and platform.machine().lower() in {"amd64", "x86_64"}
    return {"can_install": supported, "reason": "" if supported else "A instalacao guiada esta disponivel somente para Windows x64. Nenhum download foi iniciado."}


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise BootstrapCancelled("Instalacao cancelada. Downloads parciais de modelos nao foram ativados.")


def _progress(callback: Progress, phase: str, message: str, value: float | None = None, **extra) -> None:
    callback({"phase": phase, "message": message, "progress": value, **extra})


def _inside(root: Path, relative: str | Path) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise BootstrapError("Caminho de instalacao fora da pasta de dados.")
    current = path
    while current != root:
        if current.is_symlink():
            raise BootstrapError("A instalacao nao substitui caminhos com links simbolicos.")
        current = current.parent
    return path


def _open(url: str):
    if urlsplit(url).scheme.lower() != "https":
        raise BootstrapError("Downloads exigem HTTPS com verificacao de certificado.")
    # urllib keeps the inherited proxy and system/SSL_CERT_FILE trust configuration.
    opener = build_opener(HTTPSOnlyRedirect())
    response = opener.open(Request(url, headers={"User-Agent": "IVI-Local-Setup/0.3", "Accept": "application/json, */*"}), timeout=30)
    if urlsplit(response.geturl()).scheme.lower() != "https":
        response.close()
        raise BootstrapError("O provedor redirecionou o download para uma conexao sem HTTPS.")
    return response


def _json(url: str) -> dict:
    with _open(url) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise BootstrapError("Os metadados do provedor excedem o limite permitido.")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise BootstrapError("O provedor retornou metadados invalidos.")
    return value


def _sha256(path: Path, cancel: threading.Event) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            _check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest()


def download_verified(url: str, destination: Path, expected_sha256: str, cancel: threading.Event, callback: Progress, *, phase: str, start: float = 0, end: float = 90, expected_size: int | None = None) -> Path:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise BootstrapError("O provedor nao informou um SHA256 verificavel; download recusado.")
    if expected_size is not None and not 0 < expected_size <= MAX_DOWNLOAD_BYTES:
        raise BootstrapError("O arquivo informado pelo provedor excede o limite de 700 MiB.")
    _check_cancel(cancel)
    if destination.is_symlink():
        raise BootstrapError("O arquivo de destino e um link simbolico.")
    if destination.is_file() and destination.stat().st_size <= MAX_DOWNLOAD_BYTES and _sha256(destination, cancel) == expected_sha256.lower():
        _progress(callback, phase, "Arquivo existente conferido por SHA256.", end)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part-" + uuid4().hex)
    try:
        with _open(url) as response, partial.open("xb") as output:
            raw_length = response.headers.get("Content-Length")
            declared = int(raw_length) if raw_length else None
            if declared is not None and not 0 <= declared <= MAX_DOWNLOAD_BYTES:
                raise BootstrapError("O download excede o limite de 700 MiB.")
            total = expected_size or declared
            digest, received, last_report = hashlib.sha256(), 0, 0.0
            while True:
                _check_cancel(cancel)
                block = response.read(1024 * 1024)
                if not block:
                    break
                received += len(block)
                if received > MAX_DOWNLOAD_BYTES:
                    raise BootstrapError("O download excede o limite de 700 MiB.")
                output.write(block)
                digest.update(block)
                if time.monotonic() - last_report >= 0.2:
                    value = start + (end - start) * min(received / total, 1) if total else None
                    _progress(callback, phase, "Baixando arquivo verificado...", value, downloaded_bytes=received, total_bytes=total)
                    last_report = time.monotonic()
            output.flush()
            os.fsync(output.fileno())
        _check_cancel(cancel)
        if (expected_size is not None and received != expected_size) or (declared is not None and received != declared):
            raise BootstrapError("Download incompleto; nenhum arquivo anterior foi substituido.")
        if digest.hexdigest() != expected_sha256.lower():
            raise BootstrapError("A verificacao SHA256 falhou; o arquivo baixado nao sera usado.")
        os.replace(partial, destination)
        _progress(callback, phase, "Download concluido e SHA256 confirmado.", end)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def _extract_engine(archive_path: Path, directory: Path, cancel: threading.Event) -> Path:
    directory.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 256 or sum(item.file_size for item in entries) > 256 * 1024 * 1024:
            raise BootstrapError("Arquivo do motor com tamanho ou quantidade de entradas inesperados.")
        seen, names = set(), []
        for item in entries:
            name = item.filename
            parts = name.rstrip("/").split("/")
            if "\\" in name or any(part in {"", ".", ".."} or ":" in part or part.endswith((".", " ")) for part in parts):
                raise BootstrapError("O ZIP do motor contem um caminho inseguro.")
            reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
            if any(any(ord(character) < 32 or character in '<>:"|?*' for character in part) or part.split(".", 1)[0].upper() in reserved for part in parts):
                raise BootstrapError("O ZIP do motor contem um nome invalido para Windows.")
            kind = stat.S_IFMT(item.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or name.casefold() in seen:
                raise BootstrapError("O ZIP do motor contem links ou entradas duplicadas.")
            seen.add(name.casefold())
            names.append((item, Path(*PurePosixPath(name).parts)))
        if not any(path == Path("llama-server.exe") for item, path in names if not item.is_dir()):
            raise BootstrapError("O ZIP oficial nao contem llama-server.exe na raiz.")
        if directory.exists():
            for item, relative in names:
                _check_cancel(cancel)
                existing = _inside(directory, relative)
                if not item.is_dir() and (not existing.is_file() or hashlib.sha256(archive.read(item)).hexdigest() != _sha256(existing, cancel)):
                    raise BootstrapError("O motor existente foi alterado; ele foi preservado. Escolha outra pasta de dados para reinstalar.")
            return directory / "llama-server.exe"
        with tempfile.TemporaryDirectory(prefix=".ivi-engine-", dir=directory.parent) as temporary:
            staging = Path(temporary) / "files"
            staging.mkdir()
            for item, relative in names:
                _check_cancel(cancel)
                output = _inside(staging, relative)
                if item.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with output.open("xb") as handle:
                        handle.write(archive.read(item))
            _check_cancel(cancel)
            os.rename(staging, directory)
    return directory / "llama-server.exe"


def _probe_engine(engine: Path) -> None:
    try:
        result = subprocess.run([str(engine), "--version"], cwd=engine.parent, shell=False, capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as error:
        raise BootstrapError(f"O motor nao iniciou no Windows. Verifique o Microsoft Visual C++ x64 Redistributable: {VC_RUNTIME_URL} . Nao e necessario instalar um compilador.") from error
    except subprocess.TimeoutExpired as error:
        raise BootstrapError("O teste do motor demorou mais de 15 segundos. Nenhum modelo foi executado.") from error
    code = result.returncode & 0xFFFFFFFF
    if code == 0xC000001D:
        raise BootstrapError("O motor encontrou uma instrucao nao suportada pela CPU. Nenhum modelo foi executado.")
    if code != 0:
        raise BootstrapError(f"O teste do motor falhou (codigo {code:#x}). Se faltarem DLLs, instale o Microsoft Visual C++ x64 Redistributable: {VC_RUNTIME_URL} . Nenhum modelo foi executado.")


def _valid_file(value) -> Path | None:
    if isinstance(value, (str, Path)) and str(value).strip():
        path = Path(value).expanduser().resolve()
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _runtime(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise BootstrapError("runtime.json existente tem formato invalido e nao sera sobrescrito.")
    return value


def _save_runtime(path: Path, engine: Path, model: Path, cancel: threading.Event) -> dict:
    return _save_paths(path, {"llm_engine": engine, "llm_model": model}, cancel)


def _valid_setting(name: str, value) -> Path | None:
    if name == "stt_model" and isinstance(value, (str, Path)) and str(value).strip():
        path = Path(value).expanduser().resolve()
        if path.is_dir() and all((path / item).is_file() for item in SPECS["stt"]["required"]):
            return path
        return None
    return _valid_file(value)


def _chosen_path(settings, data: Path, runtime: dict, name: str, *explicit_names: str) -> Path | None:
    for attribute in explicit_names or (name,):
        explicit = _valid_setting(name, getattr(settings, attribute, None))
        if explicit is not None:
            return explicit
    stored = _valid_setting(name, runtime.get(name))
    if stored is not None and not stored.is_relative_to(data):
        raise BootstrapError(f"O caminho {name} de runtime.json esta fora da pasta de dados. Use uma configuracao explicita para caminhos personalizados; nenhum componente foi ativado.")
    return stored


def _save_paths(path: Path, paths: dict[str, Path], cancel: threading.Event) -> dict:
    value = _runtime(path)
    for name, local_path in paths.items():
        chosen = _valid_setting(name, local_path)
        if chosen is None:
            raise BootstrapError(f"O caminho escolhido para {name} deixou de ser valido; a configuracao anterior foi preservada.")
        value[name] = str(chosen)
    temporary = path.with_name(".runtime-" + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        _check_cancel(cancel)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return value


def install_conversation(settings, progress_callback: Progress, cancel_event: threading.Event) -> dict:
    capability = conversation_setup_capability()
    if not capability["can_install"]:
        raise BootstrapError(capability["reason"])
    _check_cancel(cancel_event)
    data = Path(settings.data_dir).expanduser().resolve()
    runtime_path = _inside(data, "runtime.json")
    runtime = _runtime(runtime_path)
    engine = _chosen_path(settings, data, runtime, "llm_engine", "llm_server", "llm_engine")
    model = _chosen_path(settings, data, runtime, "llm_model")
    engine_preexisting = engine is not None
    if engine is None:
        _progress(progress_callback, "motor", "Preparando motor local para Windows x64...", 0)
        archive = download_verified(ENGINE_URL, _inside(data, f"engines/downloads/llama-{ENGINE_TAG}-{ENGINE_SHA256[:12]}.zip"), ENGINE_SHA256, cancel_event, progress_callback, phase="motor", start=0, end=15)
        engine = _extract_engine(archive, _inside(data, f"engines/llama-{ENGINE_TAG}-{ENGINE_SHA256[:12]}"), cancel_event)
    _check_cancel(cancel_event)
    _progress(progress_callback, "verificacao", "Testando o motor local, sem carregar modelo...", 17)
    _probe_engine(engine)
    model_manifest = {"source": "existing", "path": str(model)} if model else {}
    if model is None:
        _progress(progress_callback, "modelo", "Consultando a origem e o SHA256 do modelo pequeno...", 20)
        spec = SPECS["llm"]
        info = _json(f"https://huggingface.co/api/models/{spec['repo']}/revision/main?blobs=true")
        revision = str(info.get("sha", ""))
        if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
            raise BootstrapError("O Hugging Face nao informou um commit verificavel para o modelo.")
        filename = spec["required"][0]
        item = next((item for item in info.get("siblings", []) if item.get("rfilename") == filename), {})
        metadata = item.get("lfs") or {}
        checksum = str(metadata.get("sha256", ""))
        size = metadata.get("size")
        if not isinstance(size, int):
            raise BootstrapError("O Hugging Face nao informou o tamanho verificavel do modelo.")
        url = f"https://huggingface.co/{spec['repo']}/resolve/{revision}/{quote(filename)}?download=true"
        model = download_verified(url, _inside(data, "models/llm/" + filename), checksum, cancel_event, progress_callback, phase="modelo", start=20, end=95, expected_size=size)
        with model.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                raise BootstrapError("O arquivo verificado nao tem formato GGUF; ele nao foi ativado.")
        model_manifest = {"repo": spec["repo"], "revision": revision, "source": url, "path": str(model), "lfs_sha256": checksum}
    _check_cancel(cancel_event)
    _progress(progress_callback, "configuracao", "Salvando os caminhos locais, preservando seu .env...", 98)
    data.mkdir(parents=True, exist_ok=True)
    saved = _save_runtime(runtime_path, engine, model, cancel_event)
    _progress(progress_callback, "concluido", "Conversa local preparada. O modelo sera carregado na primeira mensagem.", 100)
    manifest = {"components": {"llm": model_manifest}, "engine": {"source": "existing" if engine_preexisting else ENGINE_URL, "path": str(engine)}}
    if not engine_preexisting:
        manifest["engine"].update(release=ENGINE_TAG, archive_sha256=ENGINE_SHA256, digest_source=ENGINE_SOURCE)
    return {"installed": True, "components": ["llm"], "prepared_components": 1, "engine_path": saved["llm_engine"], "model_path": saved["llm_model"], "runtime_config": str(runtime_path), "manifest": manifest}


def voice_setup_capability() -> dict:
    result = conversation_setup_capability()
    if result["can_install"] and importlib.util.find_spec("pip") is None:
        return {"can_install": False, "reason": "O Python deste ambiente nao possui pip para instalar os mecanismos de voz."}
    return result


def _sanitized_output(output: bytes) -> str:
    text = output[-8000:].decode("utf-8", errors="replace")

    def clean_url(match):
        try:
            value = urlsplit(match.group(0))
            return f"{value.scheme}://{value.hostname or '[host]'}/[caminho-omitido]"
        except ValueError:
            return "[URL omitida]"

    text = re.sub(r"https?://[^\s<>\"']+", clean_url, text)
    text = re.sub(r"(?im)(authorization\s*[:=])[^\r\n]*", r"\1[oculto]", text)
    text = re.sub(r"(?i)(password|token)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|\S+)", r"\1=[oculto]", text)
    return text[-4000:]


def _run_python(arguments: list[str], cancel: threading.Event, *, timeout: float = 600) -> None:
    _check_cancel(cancel)
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([sys.executable, *arguments], shell=False, stdout=output, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started = time.monotonic()
        try:
            while process.poll() is None:
                _check_cancel(cancel)
                if time.monotonic() - started > timeout:
                    raise BootstrapError("A preparacao dos mecanismos de voz excedeu o tempo permitido.")
                cancel.wait(0.2)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise
        if process.returncode:
            output.seek(0, os.SEEK_END)
            size = output.tell()
            output.seek(max(0, size - 8000))
            detail = _sanitized_output(output.read())
            code = process.returncode & 0xFFFFFFFF
            if code == 0xC000001D:
                raise BootstrapError("Um mecanismo de voz usa instrucoes nao suportadas pela CPU. Nenhum modelo foi executado.")
            raise BootstrapError("Nao foi possivel preparar a voz com pacotes binarios compativeis. Nenhuma compilacao foi iniciada. Verifique a versao do Python, o acesso ao PyPI e o Microsoft Visual C++ x64 Redistributable. " + detail)


def _download_git_blob(url: str, destination: Path, expected_blob: str, cancel: threading.Event, callback: Progress, *, phase: str, start: float, end: float, expected_size: int | None = None) -> Path:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_blob):
        raise BootstrapError("O provedor nao informou o hash Git do arquivo de configuracao.")
    limit = 16 * 1024 * 1024
    if expected_size is not None and not 0 <= expected_size <= limit:
        raise BootstrapError("Arquivo de configuracao maior que o limite permitido.")

    def matches(data: bytes) -> bool:
        return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest() == expected_blob.lower()

    _check_cancel(cancel)
    if destination.is_symlink():
        raise BootstrapError("O arquivo de configuracao de destino e um link simbolico.")
    if destination.is_file() and destination.stat().st_size <= limit and matches(destination.read_bytes()):
        _progress(callback, phase, "Configuracao existente conferida pelo hash Git.", end)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part-" + uuid4().hex)
    try:
        chunks, received = [], 0
        with _open(url) as response:
            while True:
                _check_cancel(cancel)
                block = response.read(1024 * 1024)
                if not block:
                    break
                received += len(block)
                if received > limit:
                    raise BootstrapError("Arquivo de configuracao maior que o limite permitido.")
                chunks.append(block)
        data = b"".join(chunks)
        _check_cancel(cancel)
        if (expected_size is not None and len(data) != expected_size) or not matches(data):
            raise BootstrapError("A verificacao do hash Git da configuracao falhou.")
        with partial.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        _check_cancel(cancel)
        os.replace(partial, destination)
        _progress(callback, phase, "Configuracao conferida pelo hash Git do commit fixado.", end)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def _prepare_hf_component(component: str, data: Path, callback: Progress, cancel: threading.Event, start: float, end: float) -> dict:
    spec = SPECS[component]
    info = _json(f"https://huggingface.co/api/models/{spec['repo']}/revision/main?blobs=true")
    revision = str(info.get("sha", ""))
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise BootstrapError("O Hugging Face nao informou o commit verificavel dos arquivos de voz.")
    siblings = {item.get("rfilename"): item for item in info.get("siblings", []) if isinstance(item, dict)}
    if any(name not in siblings for name in spec["required"]):
        raise BootstrapError(f"O repositorio {spec['repo']} nao contem todos os arquivos necessarios.")
    names = spec["required"] + [name for name in spec["optional"] if name in siblings]
    records = []
    for index, name in enumerate(names):
        _check_cancel(cancel)
        destination = _inside(data, Path("models") / component / name)
        item = siblings[name]
        metadata = item.get("lfs") or {}
        begin = start + (end - start) * index / len(names)
        finish = start + (end - start) * (index + 1) / len(names)
        url = f"https://huggingface.co/{spec['repo']}/resolve/{revision}/{quote(name, safe='/')}?download=true"
        if metadata:
            checksum = str(metadata.get("sha256", ""))
            size = metadata.get("size")
            if not isinstance(size, int):
                raise BootstrapError("O provedor nao informou o tamanho verificavel de um modelo de voz.")
            path = download_verified(url, destination, checksum, cancel, callback, phase=component, start=begin, end=finish, expected_size=size)
            expected = {"lfs_sha256": checksum}
        else:
            blob = str(item.get("blobId", ""))
            path = _download_git_blob(url, destination, blob, cancel, callback, phase=component, start=begin, end=finish, expected_size=item.get("size"))
            expected = {"git_blob_sha1": blob}
        records.append({"path": str(path), "sha256": _sha256(path, cancel), **expected})
    return {"repo": spec["repo"], "revision": revision, "source": f"https://huggingface.co/{spec['repo']}/tree/{revision}", "files": records}


def install_voice(settings, progress_callback: Progress, cancel_event: threading.Event) -> dict:
    capability = voice_setup_capability()
    if not capability["can_install"]:
        raise BootstrapError(capability["reason"])
    _check_cancel(cancel_event)
    data = Path(settings.data_dir).expanduser().resolve()
    runtime_path = _inside(data, "runtime.json")
    runtime = _runtime(runtime_path)
    paths = {name: _chosen_path(settings, data, runtime, name) for name in ("stt_model", "tts_model", "tts_config")}
    default_tts = _inside(data, Path("models/tts") / SPECS["tts"]["required"][0])
    default_config = _inside(data, Path("models/tts") / SPECS["tts"]["required"][1])
    if paths["tts_model"] is not None and paths["tts_config"] is None and paths["tts_model"] != default_tts:
        paths["tts_config"] = _valid_file(Path(str(paths["tts_model"]) + ".json"))
        if paths["tts_config"] is None:
            raise BootstrapError("Sua voz personalizada foi preservada. Informe o JSON correspondente em IVI_TTS_CONFIG antes de preparar a voz.")
    if paths["tts_config"] is not None and paths["tts_model"] is None and paths["tts_config"] != default_config:
        paths["tts_model"] = _valid_file(Path(str(paths["tts_config"]).removesuffix(".json")))
        if paths["tts_model"] is None:
            raise BootstrapError("Sua configuracao de voz personalizada foi preservada. Informe o ONNX correspondente em IVI_TTS_MODEL.")
    _progress(progress_callback, "pacotes", "Instalando mecanismos de voz binarios, sem compilacao...", 0)
    _run_python(["-m", "pip", "install", "--only-binary=:all:", "--quiet", "--disable-pip-version-check", "faster-whisper==1.2.1", "piper-tts==1.8.0"], cancel_event)
    _progress(progress_callback, "verificacao", "Conferindo a compatibilidade dos mecanismos de voz...", 15)
    _run_python(["-c", "import faster_whisper; from piper import PiperVoice"], cancel_event, timeout=30)
    manifest = {"components": {"stt": {"source": "existing", "path": str(paths["stt_model"])}, "tts": {"source": "existing", "model_path": str(paths["tts_model"]), "config_path": str(paths["tts_config"])}}}
    if paths["stt_model"] is None:
        manifest["components"]["stt"] = _prepare_hf_component("stt", data, progress_callback, cancel_event, 20, 55)
        paths["stt_model"] = _inside(data, "models/stt")
    if paths["tts_model"] is None or paths["tts_config"] is None:
        manifest["components"]["tts"] = _prepare_hf_component("tts", data, progress_callback, cancel_event, 60, 95)
        paths["tts_model"] = paths["tts_model"] or default_tts
        paths["tts_config"] = paths["tts_config"] or default_config
    for key, value in paths.items():
        if _valid_setting(key, value) is None:
            raise BootstrapError("Os arquivos de voz nao ficaram completos; a configuracao anterior foi preservada.")
    _check_cancel(cancel_event)
    _progress(progress_callback, "configuracao", "Salvando os caminhos de escuta e fala sem alterar seu .env...", 98)
    data.mkdir(parents=True, exist_ok=True)
    saved = _save_paths(runtime_path, paths, cancel_event)
    _progress(progress_callback, "concluido", "Arquivos de voz preparados. O microfone permanece desligado ate voce ativa-lo.", 100)
    return {"installed": True, "components": ["stt", "tts"], "prepared_components": 2, "runtime_config": str(runtime_path), "stt_model": saved["stt_model"], "tts_model": saved["tts_model"], "tts_config": saved["tts_config"], "manifest": manifest}

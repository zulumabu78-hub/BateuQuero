"""A CPU-only llama-server owned by this local app; no cloud inference calls."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any, AsyncIterator
from uuid import uuid4


MAX_JSON_BYTES = 2_000_000
MAX_SSE_LINE = 65_536


class _Cancelled(Exception):
    pass


class NativeEngine:
    """Lazy, loopback-only llama.cpp process with cooperative stream cancellation.

    The installer supplies a verified executable and all its CPU backend DLLs.
    This module does not download, install, compile, or contact an AI service.
    """

    def __init__(self, settings: Any, executable: Path, model: Path, *, startup_timeout: float = 120):
        self.settings = settings
        self.executable = Path(executable).resolve()
        self.model = Path(model).resolve()
        self.context_size = max(512, min(8192, int(getattr(settings, "context_tokens", 1024))))
        # Leave a CPU core available to the interface on a two-core A4.
        available = os.cpu_count() or 2
        self.threads = max(1, min(2, int(getattr(settings, "cpu_threads", 2)), max(1, available - 1)))
        self.alias = "ivi-" + uuid4().hex
        self._api_key = uuid4().hex + uuid4().hex
        self.port: int | None = None
        self.startup_timeout = startup_timeout
        self._process: subprocess.Popen | None = None
        self._ready = False
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._transport_lock = threading.Lock()
        self._active_transport: tuple[object, socket.socket] | None = None

    @property
    def loaded(self) -> bool:
        return bool(self._ready and self._process and self._process.poll() is None)

    def command(self, port: int) -> list[str]:
        return [
            str(self.executable), "--model", str(self.model),
            "--ctx-size", str(self.context_size), "--threads", str(self.threads),
            "--n-gpu-layers", "0", "--parallel", "1", "--batch-size", "64",
            "--host", "127.0.0.1", "--port", str(port), "--alias", self.alias,
            "--api-key", self._api_key,
        ]

    def _connection(self, timeout: float = 120) -> http.client.HTTPConnection:
        if self.port is None or not 1 <= self.port <= 65535:
            raise RuntimeError("O mecanismo local ainda não escolheu uma porta válida.")
        # A literal loopback IP and fixed internal paths prevent remote hosts,
        # proxy credentials, or HTTP redirects entering the inference route.
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)

    def _json(self, method: str, path: str, data: Any = None, *, timeout: float = 20) -> Any:
        if path not in {"/health", "/v1/models", "/tokenize"}:
            raise ValueError("Endpoint local inválido.")
        connection = self._connection(timeout)
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        try:
            connection.request(method, path, body=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._api_key})
            response = connection.getresponse()
            payload = response.read(MAX_JSON_BYTES + 1)
            if response.status != 200:
                raise RuntimeError(f"O mecanismo local respondeu HTTP {response.status}.")
            if len(payload) > MAX_JSON_BYTES:
                raise RuntimeError("A resposta de controle do mecanismo local ultrapassou o limite.")
            return json.loads(payload)
        finally:
            connection.close()

    def _healthy(self) -> bool:
        if not self._process or self._process.poll() is not None:
            return False
        try:
            health = self._json("GET", "/health", timeout=0.7)
            models = self._json("GET", "/v1/models", timeout=0.7)
            matches = any(item.get("id") == self.alias for item in models.get("data", []) if isinstance(item, dict))
            return bool(health.get("status") == "ok" and matches and self._process.poll() is None)
        except (OSError, ValueError, RuntimeError, http.client.HTTPException, AttributeError):
            return False

    @staticmethod
    def _startup_error(returncode: int | None) -> RuntimeError:
        code = returncode & 0xFFFFFFFF if isinstance(returncode, int) else None
        if code == 0xC0000135:
            return RuntimeError(
                "Falta o Microsoft Visual C++ Redistributable x64 no Windows. "
                "Instale o runtime oficial em https://aka.ms/vs/17/release/vc_redist.x64.exe "
                "e reinicie a I.V.I.; não é necessário instalar compiladores."
            )
        if code == 0xC000001D:
            return RuntimeError(
                "O mecanismo encontrou uma instrução de CPU incompatível. "
                "Mantenha todas as DLLs da instalação oficial, inclusive os backends x64/SSE42/Piledriver, e reinstale a conversa local."
            )
        return RuntimeError(
            "O mecanismo de conversa não conseguiu iniciar. Confira native-engine.log na pasta de dados. "
            "Se o Windows avisar sobre VCRUNTIME ou MSVCP, instale o Microsoft Visual C++ Redistributable x64 oficial."
        )

    def _start_process(self) -> None:
        with self._process_lock:
            if self._closed.is_set():
                raise _Cancelled
            if self._process and self._process.poll() is None:
                return
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                self.port = listener.getsockname()[1]
            data_dir = Path(getattr(self.settings, "data_dir", self.executable.parent))
            data_dir.mkdir(parents=True, exist_ok=True)
            try:
                with (data_dir / "native-engine.log").open("ab") as log:
                    self._process = subprocess.Popen(
                        self.command(self.port), cwd=str(self.executable.parent),
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
                    )
            except OSError as error:
                if getattr(error, "winerror", None) in {126, 127}:
                    raise self._startup_error(0xC0000135) from error
                raise RuntimeError(f"Não consegui abrir o mecanismo local: {error}") from error

    def _ensure_started(self, stop: threading.Event, cancelled: threading.Event) -> None:
        if self._closed.is_set():
            raise RuntimeError("O mecanismo local foi encerrado.")
        if self.loaded:
            return
        if stop.is_set() or cancelled.is_set():
            raise _Cancelled
        if not self.executable.is_file() or not self.model.is_file():
            raise RuntimeError("O mecanismo ou o modelo local não foi encontrado. Abra Configurar I.V.I. para concluir a instalação.")
        self._start_process()
        deadline = time.monotonic() + self.startup_timeout
        while True:
            if stop.is_set() or cancelled.is_set() or self._closed.is_set():
                raise _Cancelled
            if self._process.poll() is not None:
                raise self._startup_error(self._process.returncode)
            if self._healthy():
                self._ready = True
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("O modelo demorou para carregar neste computador. Confira native-engine.log; reduza o contexto ou feche outros aplicativos antes de tentar novamente.")
            cancelled.wait(0.15)

    def n_ctx(self) -> int:
        return self.context_size

    def tokenize(self, data: bytes, *, add_bos: bool, special: bool) -> list[int]:
        result = self._json("POST", "/tokenize", {"content": data.decode("utf-8"), "add_special": add_bos})
        tokens = result.get("tokens") if isinstance(result, dict) else None
        if not isinstance(tokens, list) or any(not isinstance(token, int) for token in tokens):
            raise RuntimeError("O tokenizador local retornou um formato inválido.")
        return tokens

    def _interrupt_transport(self, request_id: object | None = None) -> None:
        with self._transport_lock:
            transport = self._active_transport
            active = transport[1] if transport and (request_id is None or transport[0] is request_id) else None
        if active:
            with suppress(OSError):
                active.shutdown(socket.SHUT_RDWR)

    def _stream_sync(self, messages: list[dict[str, str]], stop: threading.Event, cancelled: threading.Event, request_id: object, emit) -> None:
        # Imported at request time to avoid a providers/native_llm import cycle.
        from .providers import MAX_COMPLETION_TOKENS, budget_chat_messages

        try:
            with self._lock:
                connection = response = None
                try:
                    self._ensure_started(stop, cancelled)
                    if stop.is_set() or cancelled.is_set() or self._closed.is_set():
                        return
                    prepared = budget_chat_messages(self, messages)
                    payload = json.dumps({
                        "model": self.alias, "messages": prepared, "stream": True,
                        "max_tokens": MAX_COMPLETION_TOKENS, "temperature": 0.65,
                        "top_p": 0.9, "repeat_penalty": 1.1,
                    }, ensure_ascii=False).encode("utf-8")
                    connection = self._connection()
                    connection.request("POST", "/v1/chat/completions", body=payload, headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": "Bearer " + self._api_key})
                    with self._transport_lock:
                        if connection.sock is not None:
                            self._active_transport = (request_id, connection.sock)
                    if stop.is_set() or cancelled.is_set():
                        self._interrupt_transport(request_id)
                        return
                    response = connection.getresponse()
                    if response.status != 200:
                        error_body = response.read(8192).decode("utf-8", errors="replace")
                        if response.status == 400:
                            raise ValueError("O pedido excedeu um limite do modelo local. Reduza a mensagem ou o contexto da conversa.")
                        raise RuntimeError(f"A conversa local respondeu HTTP {response.status}: {error_body[:300]}")
                    completed = False
                    while not stop.is_set() and not cancelled.is_set() and not self._closed.is_set():
                        line = response.readline(MAX_SSE_LINE + 1)
                        if not line:
                            if not completed:
                                raise RuntimeError("A conexão com o modelo local terminou antes de concluir a resposta.")
                            break
                        if len(line) > MAX_SSE_LINE:
                            raise RuntimeError("Um trecho do mecanismo local ultrapassou o limite de transporte.")
                        if not line.startswith(b"data:"):
                            continue
                        value = line[5:].strip()
                        if value == b"[DONE]":
                            break
                        event = json.loads(value)
                        choices = event.get("choices", [])
                        if choices and choices[0].get("finish_reason") is not None:
                            completed = True
                        token = choices[0].get("delta", {}).get("content") if choices else None
                        if isinstance(token, str) and token and not stop.is_set() and not cancelled.is_set():
                            emit("token", token)
                finally:
                    with self._transport_lock:
                        if self._active_transport and self._active_transport[0] is request_id:
                            self._active_transport = None
                    if response:
                        response.close()
                    if connection:
                        connection.close()
        except _Cancelled:
            pass
        except Exception as error:
            if not stop.is_set() and not cancelled.is_set() and not self._closed.is_set():
                emit("error", error)
        finally:
            emit("done", None)

    async def stream_chat(self, messages: list[dict[str, str]], stop: threading.Event) -> AsyncIterator[str]:
        if stop.is_set():
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        cancelled = threading.Event()
        request_id = object()

        def emit(kind, value):
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, (kind, value))

        future = loop.run_in_executor(None, self._stream_sync, messages, stop, cancelled, request_id, emit)
        try:
            while not stop.is_set():
                try:
                    kind, value = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
                if kind == "done" or stop.is_set():
                    break
                if kind == "error":
                    raise value
                yield value
        finally:
            cancelled.set()
            self._interrupt_transport(request_id)
            future.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    def _close(self) -> None:
        self._closed.set()
        self._interrupt_transport()
        with self._process_lock:
            process = self._process
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self._ready = False

    async def aclose(self) -> None:
        await asyncio.to_thread(self._close)

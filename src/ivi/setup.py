"""Explicit, cancellable preparation jobs for the local neural components."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import math
import re
import threading
from typing import Any, Callable

from .config import Settings


class SetupConflict(RuntimeError):
    pass


class SetupUnavailable(RuntimeError):
    pass


class SetupManager:
    def __init__(
        self,
        settings: Settings,
        *,
        workers: dict[str, Callable] | None = None,
        capabilities: dict[str, dict[str, Any]] | None = None,
        on_complete: Callable[[], None] | None = None,
    ):
        if workers is None:
            from . import bootstrap

            workers = {"conversation": bootstrap.install_conversation}
            capabilities = {"conversation": bootstrap.conversation_setup_capability()}
            if hasattr(bootstrap, "install_voice"):
                workers["voice"] = bootstrap.install_voice
                capabilities["voice"] = bootstrap.voice_setup_capability()
        self.settings = settings
        self.workers = workers
        self.capabilities = capabilities or {name: {"can_install": True, "reason": ""} for name in workers}
        self.on_complete = on_complete
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._task: asyncio.Task | None = None
        self._closed = False
        self._state: dict[str, Any] = {
            "state": "idle", "phase": "idle", "component": None,
            "message": "Escolha o que deseja preparar neste computador.",
            "progress": None, "log": [], "result": None,
        }

    @staticmethod
    def _text(value: Any) -> str:
        text = str(value)[:2000]
        return re.sub(r"(https?://)[^/@\s]+@", r"\1[credencial omitida]@", text)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = deepcopy(self._state)
        state["components"] = deepcopy(self.capabilities)
        state["can_install"] = bool(self.capabilities.get("conversation", {}).get("can_install"))
        state["can_install_voice"] = bool(self.capabilities.get("voice", {}).get("can_install"))
        if state["state"] == "idle" and not state["can_install"] and not state["can_install_voice"]:
            state["message"] = self.capabilities.get("conversation", {}).get("reason") or "A preparação automática não está disponível neste sistema."
        return state

    def _progress(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        with self._lock:
            if self._state["state"] != "running":
                return
            if self._cancel.is_set():
                return
            phase = event.get("phase")
            if phase:
                self._state["phase"] = self._text(phase)[:80]
            if event.get("message"):
                message = self._text(event["message"])
                self._state["message"] = message
                if not self._state["log"] or self._state["log"][-1] != message:
                    self._state["log"] = (self._state["log"] + [message])[-40:]
            value = event.get("progress")
            self._state["progress"] = (
                max(0, min(100, float(value)))
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                else None
            )

    async def start(self, component: str) -> dict[str, Any]:
        if self._closed:
            raise SetupUnavailable("O servidor está encerrando. Abra a I.V.I. novamente.")
        if self._task and not self._task.done():
            raise SetupConflict("Já existe uma preparação em andamento. Aguarde ou cancele antes de iniciar outra.")
        capability = self.capabilities.get(component, {})
        if component not in self.workers or not capability.get("can_install"):
            raise SetupUnavailable(capability.get("reason") or "Esta preparação ainda não está disponível neste sistema.")
        self._cancel = threading.Event()
        with self._lock:
            self._state = {
                "state": "running", "phase": "starting", "component": component,
                "message": "Preparando o download solicitado…", "progress": None,
                "log": ["Preparando o download solicitado…"], "result": None,
            }
        self._task = asyncio.create_task(self._run(component))
        return self.snapshot()

    async def _run(self, component: str) -> None:
        try:
            result = await asyncio.to_thread(self.workers[component], self.settings, self._progress, self._cancel)
            if self._cancel.is_set() and not (isinstance(result, dict) and result.get("installed")):
                with self._lock:
                    self._state.update(state="cancelled", phase="cancelled", message="Preparação cancelada. Arquivos de cache já verificados podem ser reutilizados.", progress=None)
                return
            if not isinstance(result, dict) or result.get("installed") is not True:
                raise RuntimeError("A preparação não confirmou a instalação dos arquivos. Nenhum componente foi marcado como pronto.")
            if self.on_complete:
                self.on_complete()
            with self._lock:
                message = "Arquivos preparados. A primeira utilização carrega os modelos locais."
                self._state.update(state="completed", phase="completed", message=message, progress=100, result=result)
                self._state["log"] = (self._state["log"] + [message])[-40:]
        except Exception as error:
            cancelled = self._cancel.is_set()
            message = "Preparação cancelada. Arquivos de cache já verificados podem ser reutilizados." if cancelled else self._text(error)
            with self._lock:
                self._state.update(state="cancelled" if cancelled else "failed", phase="cancelled" if cancelled else "failed", message=message, progress=None)
                self._state["log"] = (self._state["log"] + [message])[-40:]

    async def cancel(self) -> dict[str, Any]:
        if self._task and not self._task.done():
            self._cancel.set()
            with self._lock:
                self._state.update(phase="cancelling", message="Cancelando com segurança…")
        return self.snapshot()

    async def aclose(self) -> None:
        self._closed = True
        await self.cancel()
        if self._task:
            await self._task

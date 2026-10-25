"""Asynchronous turns, local speech, and explicit desktop action consent."""

from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import suppress
import re
import threading
import time
from typing import Any, Awaitable, Callable
from uuid import uuid4

from .memory import MemoryStore
from .providers import LocalProviders, ProviderUnavailable
from .tools import ToolRegistry, parse_tool_request


HELP = (
    "Sou a I.V.I. Você pode me pedir para abrir Spotify, Arquivos, Navegador ou Calculadora. "
    "Eu peço sua confirmação antes de abrir um aplicativo. "
    "Para guardar algo, escreva /lembrar seguido da informação; /memorias mostra suas anotações. "
    "O botão Ativar conversa local prepara o modelo para conversar livremente. "
    "A escuta e a voz podem ser preparadas na mesma janela."
)
SYSTEM_PROMPT = (
    "Você é I.V.I., uma assistente pessoal local. Converse em português brasileiro de forma "
    "natural, clara e acolhedora. Preserve o contexto, admita incertezas e não invente fatos. "
    "Prefira respostas breves, exceto quando pedirem detalhes. Não afirme ter executado ações "
    "ou consultado a internet: ferramentas só executam após confirmação na interface."
)


class ConversationSession:
    def __init__(
        self,
        store: MemoryStore,
        providers: LocalProviders,
        tools: ToolRegistry,
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ):
        self.store, self.providers, self.tools, self.send = store, providers, tools, send
        self.task: asyncio.Task | None = None
        self.stop = threading.Event()
        self.pending: dict[str, tuple[Any, float]] = {}
        self.activated_until = 0.0

    async def interrupt(self, *, notify: bool = True) -> None:
        self.stop.set()
        if self.task and not self.task.done():
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if notify:
            await self.send({"type": "status", "state": "interrupted"})

    async def close(self) -> None:
        self.pending.clear()
        await self.interrupt(notify=False)

    async def receive(self, data: dict[str, Any]) -> None:
        kind = data.get("type")
        if kind == "interrupt":
            await self.interrupt()
            return
        if kind == "confirm_tool":
            if not isinstance(data.get("id"), str) or not isinstance(data.get("approved"), bool):
                raise ValueError("Confirmação inválida.")
            pending = self.pending.pop(data["id"], None)
            if not pending or pending[1] < time.monotonic():
                raise ValueError("Esta confirmação expirou. Peça a ação novamente.")
            if not data["approved"]:
                await self.send({"type": "tool_result", "text": "Ação cancelada por você."})
                return
            await self.interrupt(notify=False)
            self.stop = threading.Event()
            self.task = asyncio.create_task(self._execute_tool(pending[0]))
            return
        if kind not in {"text", "audio"}:
            raise ValueError("Tipo de mensagem desconhecido.")
        if kind == "text":
            value = data.get("text")
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise ValueError("A mensagem deve ter entre 1 e 4000 caracteres.")
            value = value.strip()
        else:
            value = data.get("audio")
            if not isinstance(value, str) or not value or len(value) > 1_400_000:
                raise ValueError("Áudio inválido ou longo demais. Use trechos de até 30 segundos.")
        await self.interrupt(notify=False)
        self.pending.clear()
        self.stop = threading.Event()
        self.task = asyncio.create_task(self._run(value, audio=kind == "audio"))

    async def _run(self, value: str, *, audio: bool) -> None:
        try:
            if audio:
                await self.send({"type": "status", "state": "transcribing"})
                try:
                    wav = base64.b64decode(value, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("O áudio recebido não está em base64 válido.") from exc
                value = (await self.providers.transcribe(wav)).strip()
                if not value:
                    return
                enabled = self.store.get_settings()["require_wake_word"]
                wake = re.search(r"\b(?:i[.\s]*v[.\s]*i|ivy|ívi)\b[.,:!?\s]*", value, re.I)
                activated = not enabled or bool(wake) or time.monotonic() < self.activated_until
                await self.send({"type": "transcript", "text": value, "activated": activated})
                if not activated:
                    return
                if enabled:
                    self.activated_until = time.monotonic() + 60
                    if wake:
                        value = (value[:wake.start()] + value[wake.end():]).strip()
                if not value:
                    await self._respond("Estou ouvindo. O que vamos fazer?")
                    return
            await self._text(value)
        except asyncio.CancelledError:
            self.stop.set()
            raise
        except (ProviderUnavailable, ValueError, RuntimeError) as exc:
            await self.send({"type": "error", "message": str(exc)})
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Falha ao processar uma conversa local")
            await self.send({"type": "error", "message": "Não consegui concluir esta resposta. Confira o terminal da I.V.I. para o diagnóstico."})
        finally:
            if not self.stop.is_set():
                await self.send({"type": "status", "state": "idle"})

    async def _text(self, text: str) -> None:
        await asyncio.to_thread(self.store.add_message, "user", text)
        await self.send({"type": "user", "text": text})
        await self.send({"type": "status", "state": "thinking"})
        if text.lower().strip() in {"/ajuda", "ajuda"}:
            await self._respond(HELP)
            return
        remember = re.match(r"^(?:/lembrar\s+|lembre\s+que\s+|lembra\s+que\s+)(.+)$", text, re.I | re.S)
        if remember:
            await asyncio.to_thread(self.store.add_memory, remember.group(1))
            await self._respond("Anotei essa informação na sua memória local. Você pode consultá-la ou removê-la no painel Memória.")
            await self.send({"type": "memory_updated"})
            return
        if text.lower().strip() in {"/memorias", "/memórias"}:
            memories = await asyncio.to_thread(self.store.list_memories)
            response = "\n".join(f"• {item['content']}" for item in memories[:20]) or "Você ainda não salvou memórias. Use /lembrar seguido do que quer guardar."
            await self._respond(response)
            return
        tool = parse_tool_request(text)
        if tool:
            identifier = uuid4().hex
            self.pending[identifier] = (tool, time.monotonic() + 120)
            await self.send({"type": "tool_confirmation", "id": identifier, "title": tool.title, "description": tool.description})
            return
        if not self.providers.status()["llm"]["ready"]:
            raise ProviderUnavailable("A conversa local ainda precisa ser preparada. Clique em Ativar conversa local para baixar o modelo. Enquanto isso, posso abrir aplicativos e guardar suas anotações.")
        history = await asyncio.to_thread(self.store.recent_messages, 8)
        facts = await asyncio.to_thread(self.store.list_memories)
        context = SYSTEM_PROMPT
        if facts:
            context += "\nAnotações fornecidas pelo usuário, para contexto: " + "; ".join(item["content"][:160] for item in facts[:5])
        messages = [{"role": "system", "content": context}] + [{"role": item["role"], "content": item["content"]} for item in history]
        spoken = asyncio.Queue(maxsize=8)
        voice = self.store.get_settings()["voice_enabled"] and self.providers.status()["tts"]["ready"]
        worker = asyncio.create_task(self._speech_worker(spoken)) if voice else None
        answer, phrase = "", ""
        try:
            async for token in self.providers.stream_chat(messages, self.stop):
                if self.stop.is_set():
                    return
                answer += token
                phrase += token
                await self.send({"type": "token", "text": token})
                if worker and (re.search(r"[.!?…]\s$", phrase) or len(phrase) >= 240):
                    await spoken.put(phrase)
                    phrase = ""
                if len(answer) > 12000:
                    self.stop.set()
                    break
            if not answer.strip():
                raise RuntimeError("O modelo local não gerou texto. Verifique a compatibilidade do GGUF e o contexto configurado.")
            await asyncio.to_thread(self.store.add_message, "assistant", answer.strip())
            await self.send({"type": "assistant", "text": answer.strip()})
            if worker:
                if phrase.strip():
                    await spoken.put(phrase)
                await spoken.put(None)
                await worker
        finally:
            if worker and not worker.done():
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    async def _speech_worker(self, queue: asyncio.Queue) -> None:
        failed = False
        while (text := await queue.get()) is not None:
            if self.stop.is_set():
                return
            if failed:
                continue
            try:
                audio = await self.providers.synthesize(text, self.store.get_settings()["speech_rate"])
                if not self.stop.is_set():
                    await self.send({"type": "status", "state": "speaking"})
                    await self.send({"type": "audio", "audio": base64.b64encode(audio).decode("ascii"), "mime": "audio/wav", "text": text})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failed = True
                await self.send({"type": "error", "component": "tts", "message": f"A resposta em texto foi mantida, mas a voz local falhou: {exc}"})

    async def _respond(self, text: str) -> None:
        await asyncio.to_thread(self.store.add_message, "assistant", text)
        await self.send({"type": "assistant", "text": text})
        if self.store.get_settings()["voice_enabled"] and self.providers.status()["tts"]["ready"]:
            queue = asyncio.Queue()
            await queue.put(text)
            await queue.put(None)
            await self._speech_worker(queue)

    async def _execute_tool(self, request: Any) -> None:
        try:
            result = await asyncio.to_thread(self.tools.execute, request)
            await asyncio.to_thread(self.store.add_message, "assistant", result)
            await self.send({"type": "tool_result", "text": result})
        except (RuntimeError, ValueError, OSError) as exc:
            await self.send({"type": "error", "component": "tools", "message": str(exc)})
        finally:
            await self.send({"type": "status", "state": "idle"})

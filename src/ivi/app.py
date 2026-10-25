"""Loopback web interface for the local assistant; no cloud AI service."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from pathlib import Path
import platform
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import psutil
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .config import Settings
from .dialogue import ConversationSession
from .memory import MemoryStore
from .providers import LocalProviders
from .tools import ToolRegistry


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=2000)


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    require_wake_word: bool | None = None
    voice_enabled: bool | None = None
    speech_rate: float | None = Field(default=None, ge=0.7, le=1.5)


def system_snapshot() -> dict[str, float]:
    memory = psutil.virtual_memory()
    return {"cpu_percent": psutil.cpu_percent(), "ram_percent": memory.percent, "ram_total_gb": round(memory.total / 1024**3, 1)}


def _same_origin(origin: str | None, host: str) -> bool:
    return origin is None or origin in {f"http://{host}", f"https://{host}"}


def create_app(settings: Settings | None = None, *, providers: Any = None, tools: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(settings.data_dir / "ivi.sqlite3")
    engine = providers if providers is not None else LocalProviders(settings)
    registry = tools if tools is not None else ToolRegistry()
    app = FastAPI(title="I.V.I.", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.providers = store, engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    static = Path(__file__).parent / "static"

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        if request.url.path.startswith("/api/") and (
            not _same_origin(request.headers.get("origin"), request.headers.get("host", ""))
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "A interface local não aceita esta origem."}, status_code=403)
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Content-Length inválido."}, status_code=400)
        if length < 0 or length > 2_000_000:
            return JSONResponse({"detail": "Requisição muito grande."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; "
            "worker-src 'self' blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    def status() -> dict[str, Any]:
        return {"name": "I.V.I.", "version": __version__, "platform": platform.system(), "models": engine.status(), "settings": store.get_settings(), "system": system_snapshot()}

    @app.get("/api/status")
    def get_status():
        return status()

    @app.get("/api/history")
    def history():
        return {"messages": store.recent_messages(40)}

    @app.delete("/api/history")
    def clear_history():
        store.clear_history()
        return {"ok": True}

    @app.get("/api/memory")
    def list_memory():
        return {"items": store.list_memories()}

    @app.post("/api/memory", status_code=201)
    def add_memory(body: MemoryInput):
        try:
            return store.add_memory(body.content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/memory/{identifier}")
    def remove_memory(identifier: int):
        try:
            if not store.delete_memory(identifier):
                raise HTTPException(404, "Memória não encontrada.")
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.patch("/api/settings")
    def save_settings(body: Preferences):
        return store.update_settings(body.model_dump(exclude_none=True))

    @app.websocket("/ws")
    async def conversation(websocket: WebSocket):
        if not _same_origin(websocket.headers.get("origin"), websocket.headers.get("host", "")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        lock = asyncio.Lock()
        closed = False

        async def send(data):
            if closed:
                return
            async with lock:
                if not closed:
                    await websocket.send_json(data)

        session = ConversationSession(store, engine, registry, send)

        async def telemetry():
            while True:
                await asyncio.sleep(2)
                await send({"type": "telemetry", "system": system_snapshot()})

        monitor = asyncio.create_task(telemetry())
        try:
            await send({"type": "ready", "status": status()})
            while True:
                raw = await websocket.receive_text()
                if len(raw) > 1_500_000:
                    await send({"type": "error", "message": "Mensagem muito grande."})
                    continue
                try:
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("A mensagem deve ser um objeto JSON.")
                    await session.receive(data)
                except (ValueError, TypeError) as exc:
                    await send({"type": "error", "message": str(exc)})
        except WebSocketDisconnect:
            pass
        finally:
            closed = True
            monitor.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await monitor
            await session.close()

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static, check_dir=False), name="static")
    return app

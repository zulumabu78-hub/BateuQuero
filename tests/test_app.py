"""Backend contract tests with explicit fake models, never inference claims."""

from __future__ import annotations

import asyncio
import base64
from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave

import anyio
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ivi.app import create_app
from ivi.config import Settings
from ivi.providers import validate_microphone_wav
from ivi.tools import ToolRegistry


def fixture_wav() -> bytes:
    """A short silent PCM fixture validates transport, not speech quality."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 800)
    return buffer.getvalue()


class FakeProviders:
    def __init__(self, *, llm=True, tts=False, transcript="/ajuda", slow=False):
        self.llm, self.tts, self.transcript, self.slow = llm, tts, transcript, slow
        self.contexts = []
        self.synthesis = []
        self.cancelled = threading.Event()
        self.stop_events = []

    def status(self):
        return {
            name: {"ready": ready, "detail": "Test fake; no neural inference"}
            for name, ready in {"llm": self.llm, "stt": True, "tts": self.tts}.items()
        }

    async def stream_chat(self, messages, stop):
        self.contexts.append([dict(message) for message in messages])
        self.stop_events.append(stop)
        try:
            yield "Olá"
            if self.slow:
                await asyncio.sleep(60)
                yield " obsoleto"
            else:
                await asyncio.sleep(0)
                if not stop.is_set():
                    yield ", mundo."
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def transcribe(self, wav):
        validate_microphone_wav(wav)
        return self.transcript

    async def synthesize(self, text, speech_rate):
        self.synthesis.append((text, speech_rate))
        return fixture_wav()


class FakeTools:
    def __init__(self):
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return "Ação de teste confirmada; nenhum aplicativo real foi iniciado."


class AppTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.settings = Settings(data_dir=Path(self.directory))
        self.providers = FakeProviders()
        self.tools = FakeTools()
        self.client = self.make_client(self.providers, self.tools)

    def tearDown(self):
        self.stack.close()

    def make_client(self, providers=None, tools=None):
        app = create_app(
            self.settings,
            providers=self.providers if providers is None else providers,
            tools=self.tools if tools is None else tools,
        )
        return self.stack.enter_context(TestClient(app, base_url="http://127.0.0.1"))

    def event(self, websocket, timeout=4):
        # TestClient's synchronous receive has no timeout. Bound the underlying
        # ASGI memory-channel receive inside its own AnyIO portal instead.
        async def receive():
            with anyio.fail_after(timeout):
                return await websocket._send_rx.receive()

        message = websocket.portal.call(receive)
        self.assertEqual(message["type"], "websocket.send", message)
        return json.loads(message["text"])

    def until(self, websocket, kind, predicate=None, timeout=5):
        deadline = time.monotonic() + timeout
        events = []
        while time.monotonic() < deadline:
            event = self.event(websocket, max(0.05, deadline - time.monotonic()))
            events.append(event)
            if event.get("type") == kind and (predicate is None or predicate(event)):
                return event, events
        self.fail(f"Missing {kind}; observed {events}")

    def ready(self, websocket):
        event, _ = self.until(websocket, "ready")
        self.assertEqual(event["status"]["name"], "I.V.I.")

    def idle(self, websocket):
        return self.until(websocket, "status", lambda event: event.get("state") == "idle")

    def test_http_memory_crud_persists_and_history_clear_preserves_facts(self):
        created = self.client.post("/api/memory", json={"content": "Gosto de jazz"})
        self.assertEqual(created.status_code, 201)
        identifier = created.json()["id"]
        self.assertEqual(self.client.get("/api/memory").json()["items"][0]["content"], "Gosto de jazz")
        self.client.app.state.store.add_message("user", "Uma conversa")
        self.assertEqual(self.client.get("/api/history").json()["messages"][0]["content"], "Uma conversa")
        self.assertEqual(self.client.delete("/api/history").status_code, 200)
        self.assertEqual(self.client.get("/api/history").json(), {"messages": []})
        restored = self.make_client()
        self.assertEqual(restored.get("/api/memory").json()["items"][0]["id"], identifier)
        self.assertEqual(restored.delete(f"/api/memory/{identifier}").status_code, 200)
        self.assertEqual(self.client.get("/api/memory").json()["items"], [])
        self.assertEqual(self.client.delete(f"/api/memory/{identifier}").status_code, 404)
        self.assertEqual(self.client.delete("/api/memory/0").status_code, 422)
        for body in [{"content": " "}, {"content": "x" * 2001}, {"content": "ok", "extra": True}]:
            self.assertEqual(self.client.post("/api/memory", json=body).status_code, 422)

    def test_http_settings_are_strict_persisted_and_report_real_system_fields(self):
        changed = self.client.patch("/api/settings", json={"require_wake_word": True, "voice_enabled": False, "speech_rate": 0.8})
        self.assertEqual(changed.status_code, 200)
        restored = self.make_client().get("/api/status").json()
        self.assertEqual(restored["settings"]["speech_rate"], 0.8)
        self.assertTrue(restored["settings"]["require_wake_word"])
        self.assertFalse(restored["settings"]["voice_enabled"])
        self.assertEqual(set(restored["models"]), {"llm", "stt", "tts"})
        self.assertGreater(restored["system"]["ram_total_gb"], 0)
        self.assertGreaterEqual(restored["system"]["cpu_percent"], 0)
        for body in [{"speech_rate": 10}, {"voice_enabled": "false"}, {"not_a_setting": True}]:
            self.assertEqual(self.client.patch("/api/settings", json=body).status_code, 422)

    def test_host_origin_and_cross_site_guards(self):
        self.assertEqual(self.client.get("/api/status", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(self.client.get("/api/status", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/memory", json={"content": "blocked"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        allowed = self.client.get("/api/status", headers={"Origin": "http://127.0.0.1"})
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("frame-ancestors 'none'", allowed.headers["Content-Security-Policy"])
        with self.assertRaises(WebSocketDisconnect) as denied:
            with self.client.websocket_connect("ws://127.0.0.1/ws", headers={"Origin": "https://evil.example"}):
                self.fail("A cross-origin WebSocket was accepted")
        self.assertEqual(denied.exception.code, 1008)

    def test_help_and_explicit_remember_work_without_a_language_model(self):
        providers = FakeProviders(llm=False)
        client = self.make_client(providers)
        with client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "text", "text": "/ajuda"})
            reply, events = self.until(websocket, "assistant")
            self.assertIn("Ativar conversa local", reply["text"])
            self.assertTrue(any(event["type"] == "user" for event in events))
            self.idle(websocket)
            websocket.send_json({"type": "text", "text": "/lembrar Meu projeto é a I.V.I."})
            self.until(websocket, "memory_updated")
            self.idle(websocket)
            self.assertEqual(client.get("/api/memory").json()["items"][0]["content"], "Meu projeto é a I.V.I.")
            websocket.send_json({"type": "text", "text": "/memorias"})
            memories, _ = self.until(websocket, "assistant")
            self.assertIn("Meu projeto é a I.V.I.", memories["text"])
        self.assertEqual(providers.contexts, [])

    def test_missing_language_model_is_an_error_not_a_fabricated_answer(self):
        client = self.make_client(FakeProviders(llm=False))
        with client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "text", "text": "Vamos conversar sobre ciência?"})
            error, events = self.until(websocket, "error")
            self.assertIn("Ativar conversa local", error["message"])
            self.assertFalse(any(event["type"] in {"token", "assistant"} for event in events))
            self.idle(websocket)
        self.assertEqual([message["role"] for message in client.get("/api/history").json()["messages"]], ["user"])

    def test_streaming_tokens_precede_final_and_context_contains_explicit_memories(self):
        self.client.post("/api/memory", json={"content": "Meu instrumento é o piano"})
        self.client.app.state.store.add_message("user", "Qual é meu instrumento?")
        self.client.app.state.store.add_message("assistant", "É o piano.")
        with self.client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "text", "text": "E o que posso estudar?"})
            reply, events = self.until(websocket, "assistant")
            self.assertEqual(reply["text"], "Olá, mundo.")
            self.assertEqual("".join(event["text"] for event in events if event["type"] == "token"), reply["text"])
            self.assertEqual(events[-1]["type"], "assistant")
            self.idle(websocket)
        context = self.providers.contexts[-1]
        self.assertEqual(context[0]["role"], "system")
        self.assertIn("Meu instrumento é o piano", context[0]["content"])
        self.assertIn({"role": "assistant", "content": "É o piano."}, context)
        self.assertEqual(context[-1], {"role": "user", "content": "E o que posso estudar?"})
        self.assertEqual(self.client.get("/api/history").json()["messages"][-1]["content"], "Olá, mundo.")

    def test_tools_never_execute_before_confirmation_denial_and_replay_are_inert(self):
        with self.client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "text", "text": "abre calculadora"})
            confirmation, _ = self.until(websocket, "tool_confirmation")
            self.idle(websocket)
            self.assertEqual(self.tools.calls, [])
            websocket.send_json({"type": "confirm_tool", "id": confirmation["id"], "approved": False})
            denied, _ = self.until(websocket, "tool_result")
            self.assertIn("cancelada", denied["text"])
            self.assertEqual(self.tools.calls, [])
            websocket.send_json({"type": "confirm_tool", "id": confirmation["id"], "approved": True})
            self.until(websocket, "error")
            self.assertEqual(self.tools.calls, [])
            websocket.send_json({"type": "text", "text": "abre calculadora"})
            approved, _ = self.until(websocket, "tool_confirmation")
            self.idle(websocket)
            websocket.send_json({"type": "confirm_tool", "id": approved["id"], "approved": True})
            self.until(websocket, "tool_result")
            self.idle(websocket)
            self.assertEqual(len(self.tools.calls), 1)
            self.assertEqual(self.tools.calls[0].arguments, {"app": "calculator"})
            websocket.send_json({"type": "confirm_tool", "id": approved["id"], "approved": True})
            self.until(websocket, "error")
            self.assertEqual(len(self.tools.calls), 1)

    def test_linux_tool_guard_survives_confirmation_without_starting_apps(self):
        client = self.make_client(tools=ToolRegistry(platform="linux"))
        with client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "text", "text": "abre Spotify"})
            confirmation, _ = self.until(websocket, "tool_confirmation")
            self.idle(websocket)
            websocket.send_json({"type": "confirm_tool", "id": confirmation["id"], "approved": True})
            error, _ = self.until(websocket, "error")
            self.assertEqual(error["component"], "tools")
            self.assertIn("Windows", error["message"])
            self.idle(websocket)

    def test_malformed_json_and_audio_are_errors_and_connection_recovers(self):
        with self.client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            for raw in ["{broken", "[]", '{"type":"unknown"}', '{"type":"text","text":42}']:
                websocket.send_text(raw)
                self.until(websocket, "error")
            websocket.send_json({"type": "audio", "audio": "!!!not-base64!!!"})
            invalid_base64, _ = self.until(websocket, "error")
            self.assertIn("base64", invalid_base64["message"])
            self.idle(websocket)
            websocket.send_json({"type": "audio", "audio": base64.b64encode(b"not a wav").decode("ascii")})
            malformed, _ = self.until(websocket, "error")
            self.assertIn("WAV", malformed["message"])
            self.idle(websocket)
            websocket.send_json({"type": "text", "text": "/ajuda"})
            self.until(websocket, "assistant")

    def test_interrupt_cancels_the_model_and_no_stale_token_reaches_next_turn(self):
        providers = FakeProviders(slow=True)
        client = self.make_client(providers)
        with client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "text", "text": "Uma resposta longa"})
            first, _ = self.until(websocket, "token")
            self.assertEqual(first["text"], "Olá")
            websocket.send_json({"type": "interrupt"})
            self.until(websocket, "status", lambda event: event.get("state") == "interrupted")
            self.assertTrue(providers.cancelled.is_set())
            self.assertTrue(providers.stop_events[0].is_set())
            websocket.send_json({"type": "text", "text": "/ajuda"})
            _, later = self.until(websocket, "assistant")
            self.assertFalse(any(event["type"] == "token" for event in later))
            self.idle(websocket)
        history = client.get("/api/history").json()["messages"]
        self.assertFalse(any(message["role"] == "assistant" and "obsoleto" in message["content"] for message in history))
        self.assertFalse(any(message["role"] == "assistant" and message["content"] == "Olá" for message in history))

    def test_audio_wake_word_gate_ignores_unactivated_speech_then_accepts_name(self):
        providers = FakeProviders(llm=False, transcript="Bom dia")
        client = self.make_client(providers)
        client.patch("/api/settings", json={"require_wake_word": True})
        audio = base64.b64encode(fixture_wav()).decode("ascii")
        with client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "audio", "audio": audio})
            ignored, _ = self.until(websocket, "transcript")
            self.assertFalse(ignored["activated"])
            self.idle(websocket)
            self.assertEqual(client.get("/api/history").json()["messages"], [])
            providers.transcript = "I.V.I., /ajuda"
            websocket.send_json({"type": "audio", "audio": audio})
            activated, _ = self.until(websocket, "transcript")
            self.assertTrue(activated["activated"])
            self.until(websocket, "assistant")
            self.idle(websocket)
            self.assertEqual(client.get("/api/history").json()["messages"][0]["content"], "/ajuda")

    def test_speech_transport_uses_wav_and_persisted_speed_after_text_answer(self):
        providers = FakeProviders(tts=True)
        client = self.make_client(providers)
        client.patch("/api/settings", json={"speech_rate": 1.2})
        with client.websocket_connect("ws://127.0.0.1/ws") as websocket:
            self.ready(websocket)
            websocket.send_json({"type": "text", "text": "/ajuda"})
            answer, _ = self.until(websocket, "assistant")
            speech, _ = self.until(websocket, "audio")
            self.assertEqual(speech["mime"], "audio/wav")
            self.assertEqual(speech["text"], answer["text"])
            validate_microphone_wav(base64.b64decode(speech["audio"]))
            self.idle(websocket)
        self.assertEqual(providers.synthesis, [(answer["text"], 1.2)])


if __name__ == "__main__":
    unittest.main()

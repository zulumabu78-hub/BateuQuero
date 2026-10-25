"""Local HTTP/process fixtures; these never claim real neural inference."""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ivi.native_llm import NativeEngine
from ivi.providers import ContextWindowExceeded, LocalProviders


class OwnedProcess:
    returncode = None

    def __init__(self):
        self.terminated = self.killed = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = 0

    def kill(self):
        self.killed += 1
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, payload, code=200, headers=None):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + self.server.api_key:
            self.reply({}, 401)
            return
        if self.path == "/health":
            if self.server.redirect:
                self.reply({}, 302, {"Location": "/must-not-follow"})
            else:
                self.reply({"status": "ok"})
        elif self.path == "/v1/models":
            self.reply({"data": [{"id": self.server.alias}]})
        else:
            self.server.unexpected += 1
            self.reply({}, 404)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer " + self.server.api_key:
            self.reply({}, 401)
            return
        if self.path == "/tokenize":
            self.server.tokenizations.append(payload)
            self.reply({"tokens": list(range(len(payload["content"])))})
            return
        if self.path != "/v1/chat/completions":
            self.reply({}, 404)
            return
        self.server.requests.append(payload)
        first = 'data: {"choices":[{"delta":{"content":"Olá"}}]}\n\n'.encode()
        final = 'data: {"choices":[{"delta":{"content":", coração"}}]}\n\n'.encode()
        final += b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        if self.server.mode == "oversized":
            first, final = b"data: " + b"x" * 70000 + b"\n", b""
        elif self.server.mode == "abrupt":
            final = b""
        pause = self.server.mode == "pause-once"
        if pause:
            self.server.mode = "normal"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(first) + len(final)))
        self.end_headers()
        try:
            self.wfile.write(first)
            self.wfile.flush()
            if pause:
                self.server.release.wait(3)
            self.wfile.write(final)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class NativeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = self.root / "models/model.gguf"
        self.model.parent.mkdir()
        self.model.write_bytes(b"protocol fixture, not a neural model")
        self.executable = self.root / "engine/llama-server.exe"
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"never executed")
        self.settings = SimpleNamespace(data_dir=self.root, context_tokens=1024, cpu_threads=2)
        self.engine = NativeEngine(self.settings, self.executable, self.model)
        self.process = OwnedProcess()
        self.engine._process = self.process
        self.engine._ready = True
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.alias = self.engine.alias
        self.server.api_key = self.engine._api_key
        self.server.requests = []
        self.server.tokenizations = []
        self.server.mode = "normal"
        self.server.redirect = False
        self.server.unexpected = 0
        self.server.release = threading.Event()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.engine.port = self.server.server_port

    async def asyncTearDown(self):
        self.server.release.set()
        await self.engine.aclose()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    async def test_actual_loopback_sse_preserves_utf8_and_uses_native_token_budget(self):
        messages = [{"role": "system", "content": "Português"}, {"role": "user", "content": "Oi"}]
        result = [part async for part in self.engine.stream_chat(messages, threading.Event())]
        self.assertEqual(result, ["Olá", ", coração"])
        self.assertEqual(self.server.requests[0]["messages"], messages)
        self.assertEqual(self.server.requests[0]["model"], self.engine.alias)
        self.assertEqual(self.server.requests[0]["max_tokens"], 192)
        self.assertEqual(len(self.server.tokenizations), 2)
        self.assertTrue(all(item["add_special"] is False for item in self.server.tokenizations))

    async def test_cancel_closes_transport_and_next_turn_has_no_stale_token(self):
        self.server.mode = "pause-once"
        first = self.engine.stream_chat([{"role": "user", "content": "First"}], threading.Event())
        self.assertEqual(await anext(first), "Olá")
        await asyncio.wait_for(first.aclose(), timeout=.5)
        second = self.engine.stream_chat([{"role": "user", "content": "Second"}], threading.Event())
        result = await asyncio.wait_for(self.collect(second), timeout=1)
        self.assertEqual(result, ["Olá", ", coração"])
        self.assertEqual([request["messages"][-1]["content"] for request in self.server.requests], ["First", "Second"])

    async def test_stop_event_interrupts_a_stream_waiting_for_its_next_token(self):
        self.server.mode = "pause-once"
        stop = threading.Event()
        stream = self.engine.stream_chat([{"role": "user", "content": "Oi"}], stop)
        self.assertEqual(await anext(stream), "Olá")
        pending = asyncio.create_task(self.collect(stream))
        await asyncio.sleep(.01)
        stop.set()
        self.assertEqual(await asyncio.wait_for(pending, timeout=.5), [])

    @staticmethod
    async def collect(stream):
        return [part async for part in stream]

    async def test_context_overflow_is_rejected_before_generation(self):
        with self.assertRaises(ContextWindowExceeded):
            await self.collect(self.engine.stream_chat([{"role": "user", "content": "x" * 4000}], threading.Event()))
        self.assertEqual(self.server.requests, [])

    async def test_oversized_or_abrupt_sse_is_not_a_successful_complete_answer(self):
        for mode, error in [("oversized", "ultrapassou"), ("abrupt", "antes de concluir")]:
            self.server.mode = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, error):
                await self.collect(self.engine.stream_chat([{"role": "user", "content": "Oi"}], threading.Event()))

    def test_readiness_checks_owned_process_and_unique_model_alias(self):
        self.assertTrue(self.engine._healthy())
        self.server.alias = "some-other-local-service"
        self.assertFalse(self.engine._healthy())
        self.server.alias = self.engine.alias
        self.process.returncode = 3
        self.assertFalse(self.engine._healthy())

    def test_redirects_are_not_followed_and_no_external_endpoint_is_accepted(self):
        self.server.redirect = True
        self.assertFalse(self.engine._healthy())
        self.assertEqual(self.server.unexpected, 0)
        with self.assertRaises(ValueError):
            self.engine._json("GET", "https://example.com")

    def test_command_is_cpu_loopback_only_and_preserves_space_paths(self):
        with patch("ivi.native_llm.os.cpu_count", return_value=2):
            engine = NativeEngine(self.settings, self.root / "a folder/server.exe", self.model)
        command = engine.command(12345)
        self.assertEqual(command[0], str(self.root / "a folder/server.exe"))
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--n-gpu-layers") + 1], "0")
        self.assertEqual(command[command.index("--threads") + 1], "1")
        self.assertEqual(command[command.index("--parallel") + 1], "1")

    def test_startup_launches_one_owned_process_without_a_shell(self):
        engine = NativeEngine(self.settings, self.executable, self.model)
        owned = OwnedProcess()
        with patch("ivi.native_llm.subprocess.Popen", return_value=owned) as launch, patch.object(engine, "_healthy", return_value=True):
            engine._ensure_started(threading.Event(), threading.Event())
            engine._ensure_started(threading.Event(), threading.Event())
        launch.assert_called_once()
        arguments, options = launch.call_args
        self.assertEqual(arguments[0][0], str(self.executable))
        self.assertFalse(options["shell"])
        self.assertEqual(options["cwd"], str(self.executable.parent))
        self.assertIs(engine._process, owned)
        self.assertTrue(engine.loaded)

    def test_already_cancelled_turn_does_not_start_a_process(self):
        engine = NativeEngine(self.settings, self.executable, self.model)
        stop = threading.Event()
        stop.set()
        with patch("ivi.native_llm.subprocess.Popen") as launch, self.assertRaises(Exception):
            engine._ensure_started(stop, threading.Event())
        launch.assert_not_called()

    async def test_shutdown_during_spawn_does_not_leave_a_new_child_running(self):
        engine = NativeEngine(self.settings, self.executable, self.model)
        entered, release = threading.Event(), threading.Event()
        owned = OwnedProcess()
        def spawning(*args, **kwargs):
            entered.set()
            if not release.wait(1):
                raise RuntimeError("Spawn fixture was not released")
            return owned
        with patch("ivi.native_llm.subprocess.Popen", side_effect=spawning):
            starting = asyncio.create_task(asyncio.to_thread(engine._ensure_started, threading.Event(), threading.Event()))
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            closing = asyncio.create_task(engine.aclose())
            await asyncio.sleep(.01)
            release.set()
            with self.assertRaises(Exception):
                await starting
            await asyncio.wait_for(closing, 1)
        self.assertEqual(owned.terminated, 1)

    async def test_close_terminates_only_the_owned_process(self):
        await self.engine.aclose()
        self.assertEqual(self.process.terminated, 1)
        self.assertEqual(self.process.killed, 0)
        self.assertFalse(self.engine.loaded)

    def test_missing_runtime_and_cpu_errors_have_actionable_diagnoses(self):
        self.assertIn("Redistributable", str(self.engine._startup_error(0xC0000135)))
        self.assertIn("instrução", str(self.engine._startup_error(0xC000001D)))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = SimpleNamespace(data_dir=self.root, llm_model=None, stt_model=None, tts_model=None, tts_config=None, cpu_threads=2, context_tokens=1024)

    def configure_runtime(self):
        engine, model = self.root / "engine/server.exe", self.root / "models/model.gguf"
        for path in (engine, model):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        (self.root / "runtime.json").write_text(json.dumps({"llm_engine": str(engine), "llm_model": str(model)}))
        return engine, model

    async def test_setup_hot_activation_needs_no_python_binding_or_restart(self):
        provider = LocalProviders(self.settings)
        with patch.object(provider, "_has_dependency", return_value=False):
            self.assertFalse(provider.status()["llm"]["ready"])
            engine_path, model_path = self.configure_runtime()
            self.assertTrue(provider.status()["llm"]["ready"])
            self.assertFalse(provider.status()["llm"]["loaded"])
            class Engine:
                loaded = False
                async def stream_chat(self, messages, stop):
                    self.loaded = True
                    yield "fixture protocol token"
                async def aclose(self):
                    self.loaded = False
            with patch("ivi.native_llm.NativeEngine", return_value=Engine()) as constructor:
                result = [token async for token in provider.stream_chat([{"role": "user", "content": "Oi"}], threading.Event())]
            self.assertEqual(result, ["fixture protocol token"])
            constructor.assert_called_once_with(self.settings, engine_path, model_path)
            self.assertTrue(provider.status()["llm"]["loaded"])
            await provider.aclose()

    def test_valid_explicit_model_wins_and_runtime_escape_is_ignored(self):
        _, model = self.configure_runtime()
        custom = self.root / "custom.gguf"
        custom.write_bytes(b"custom model fixture")
        self.settings.llm_model = custom
        provider = LocalProviders(self.settings)
        self.assertEqual(provider._path("llm_model"), custom)
        self.settings.llm_model = None
        (self.root / "runtime.json").write_text(json.dumps({"llm_model": str(self.root.parent / "outside.gguf"), "llm_engine": "../server.exe"}))
        self.assertIsNone(provider._path("llm_model"))
        self.assertIsNone(provider._path("llm_server"))

    def test_oversized_invalid_runtime_is_ignored_and_low_core_budget_is_bounded(self):
        (self.root / "runtime.json").write_text("x" * 70000)
        provider = LocalProviders(self.settings)
        self.assertIsNone(provider._path("llm_model"))
        with patch("ivi.providers.os.cpu_count", return_value=2):
            self.assertEqual(provider._threads, 1)


if __name__ == "__main__":
    unittest.main()

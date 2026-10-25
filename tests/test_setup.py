"""Preparation job/API tests using fixture workers, never real downloads."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from ivi.app import create_app
from ivi.config import Settings
from ivi.setup import SetupManager, SetupUnavailable


class UnconfiguredProviders:
    def status(self):
        return {name: {"ready": False, "loaded": False, "detail": "Fixture: no model configured"} for name in ("llm", "stt", "tts")}


class ControlledWorker:
    """A bounded, cooperative stand-in for a slow installer; no network/code."""

    def __init__(self, *, result=None, error=None):
        self.result = {"installed": True, "fixture": True} if result is None else result
        self.error = error
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.calls = []

    def __call__(self, settings, progress, cancel):
        self.calls.append(settings)
        progress({"phase": "download", "message": "Fixture: download progress only, no network.", "progress": 25})
        self.started.set()
        try:
            deadline = time.monotonic() + 5
            while not self.release.wait(0.01):
                if cancel.is_set():
                    self.cancelled.set()
                    return {"installed": False}
                if time.monotonic() > deadline:
                    raise RuntimeError("Fixture worker timed out instead of hanging the test suite")
            if cancel.is_set():
                self.cancelled.set()
                return {"installed": False}
            if self.error:
                raise self.error
            return self.result
        finally:
            self.finished.set()


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.settings = Settings(data_dir=self.directory / "data")
        self.providers = UnconfiguredProviders()

    def tearDown(self):
        self.stack.close()

    def client(self, workers=None, capabilities=None, on_complete=None):
        workers = {} if workers is None else workers
        manager = SetupManager(self.settings, workers=workers, capabilities=capabilities, on_complete=on_complete)
        app = create_app(self.settings, providers=self.providers, setup_manager=manager)
        client = self.stack.enter_context(TestClient(app, base_url="http://127.0.0.1"))
        return client, manager

    def state(self, client, target, *, timeout=2):
        deadline = time.monotonic() + timeout
        latest = None
        while time.monotonic() < deadline:
            response = client.get("/api/setup")
            self.assertEqual(response.status_code, 200)
            latest = response.json()
            if latest["state"] == target:
                return latest
            time.sleep(0.01)
        self.fail(f"Expected setup state {target}, got {latest}")

    def test_constructing_default_app_and_getting_state_never_installs_or_downloads(self):
        with patch("ivi.bootstrap.install_conversation") as conversation, patch("ivi.bootstrap.install_voice") as voice, patch("ivi.bootstrap._open") as network:
            app = create_app(self.settings, providers=self.providers)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                for _ in range(3):
                    response = client.get("/api/setup")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["state"], "idle")
                    self.assertIsNone(response.json()["component"])
                self.assertEqual(client.get("/api/status").status_code, 200)
            conversation.assert_not_called()
            voice.assert_not_called()
            network.assert_not_called()

    def test_explicit_start_reports_progress_and_keeps_status_http_nonblocking(self):
        worker = ControlledWorker()
        client, _ = self.client({"conversation": worker})
        started = time.monotonic()
        response = client.post("/api/setup", json={"component": "conversation"})
        self.assertEqual(response.status_code, 202)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(worker.started.wait(1))
        self.assertFalse(worker.finished.is_set())
        state = client.get("/api/setup").json()
        self.assertEqual(state["state"], "running")
        self.assertEqual(state["phase"], "download")
        self.assertEqual(state["progress"], 25)
        self.assertIn("no network", state["message"])
        started = time.monotonic()
        self.assertEqual(client.get("/api/status").status_code, 200)
        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse(worker.finished.is_set(), "HTTP status must remain available while the worker is blocked")
        worker.release.set()
        self.assertEqual(self.state(client, "completed")["progress"], 100)

    def test_duplicate_start_is_409_and_does_not_execute_second_worker(self):
        conversation, voice = ControlledWorker(), ControlledWorker()
        client, _ = self.client({"conversation": conversation, "voice": voice})
        self.assertEqual(client.post("/api/setup", json={"component": "conversation"}).status_code, 202)
        self.assertTrue(conversation.started.wait(1))
        for component in ["conversation", "voice"]:
            self.assertEqual(client.post("/api/setup", json={"component": component}).status_code, 409)
        self.assertEqual(len(conversation.calls), 1)
        self.assertEqual(voice.calls, [])
        conversation.release.set()
        self.state(client, "completed")

    def test_explicit_voice_job_selects_only_the_voice_fixture_worker(self):
        conversation, voice = ControlledWorker(), ControlledWorker()
        voice.release.set()
        client, _ = self.client({"conversation": conversation, "voice": voice})
        self.assertTrue(client.get("/api/setup").json()["can_install_voice"])
        self.assertEqual(client.post("/api/setup", json={"component": "voice"}).status_code, 202)
        completed = self.state(client, "completed")
        self.assertEqual(completed["component"], "voice")
        self.assertEqual(len(voice.calls), 1)
        self.assertEqual(conversation.calls, [])

    def test_invalid_request_bodies_are_422_without_starting_installation(self):
        worker = ControlledWorker()
        client, _ = self.client({"conversation": worker})
        for body in [{}, [], {"component": "all"}, {"component": 7}, {"component": "conversation", "command": "do-not-execute"}]:
            with self.subTest(body=body):
                self.assertEqual(client.post("/api/setup", json=body).status_code, 422)
        self.assertEqual(client.post("/api/setup", content="not json", headers={"Content-Type": "application/json"}).status_code, 422)
        self.assertEqual(worker.calls, [])
        self.assertEqual(client.get("/api/setup").json()["state"], "idle")

    def test_unavailable_components_explain_capability_and_never_call_worker(self):
        worker = ControlledWorker()
        reason = "Fixture: this installer requires the local Windows computer."
        client, _ = self.client({"conversation": worker}, {"conversation": {"can_install": False, "reason": reason}})
        state = client.get("/api/setup").json()
        self.assertFalse(state["can_install"])
        self.assertFalse(state["can_install_voice"])
        self.assertEqual(state["components"]["conversation"]["reason"], reason)
        refused = client.post("/api/setup", json={"component": "conversation"})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["detail"], reason)
        self.assertEqual(client.post("/api/setup", json={"component": "voice"}).status_code, 409)
        self.assertEqual(worker.calls, [])

    def test_success_notifies_once_but_does_not_fabricate_model_readiness(self):
        worker = ControlledWorker()
        completed = Mock()
        client, _ = self.client({"conversation": worker}, on_complete=completed)
        client.post("/api/setup", json={"component": "conversation"})
        self.assertTrue(worker.started.wait(1))
        worker.release.set()
        result = self.state(client, "completed")
        self.assertTrue(result["result"]["installed"])
        self.assertTrue(result["result"]["fixture"])
        completed.assert_called_once_with()
        status = client.get("/api/status").json()
        self.assertTrue(all(not model["ready"] and not model["loaded"] for model in status["models"].values()))

    def test_failed_worker_preserves_honest_error_and_no_ready_models(self):
        worker = ControlledWorker(error=RuntimeError("Fixture: network unavailable; no models installed"))
        worker.release.set()
        completed = Mock()
        client, _ = self.client({"conversation": worker}, on_complete=completed)
        client.post("/api/setup", json={"component": "conversation"})
        failed = self.state(client, "failed")
        self.assertIn("network unavailable", failed["message"])
        self.assertIsNone(failed["progress"])
        self.assertIsNone(failed["result"])
        completed.assert_not_called()
        self.assertTrue(all(not model["ready"] for model in client.get("/api/status").json()["models"].values()))

    def test_worker_that_cannot_confirm_installation_cannot_complete(self):
        for result in [{"installed": False}, {"fixture": "no installation result"}, "not a result"]:
            with self.subTest(result=result):
                worker = ControlledWorker(result=result)
                worker.release.set()
                client, _ = self.client({"conversation": worker})
                client.post("/api/setup", json={"component": "conversation"})
                failed = self.state(client, "failed")
                self.assertIn("não confirmou", failed["message"])
                self.assertIsNone(failed["result"])

    def test_cancel_is_cooperative_and_next_explicit_start_can_retry(self):
        worker = ControlledWorker()
        client, _ = self.client({"conversation": worker})
        client.post("/api/setup", json={"component": "conversation"})
        self.assertTrue(worker.started.wait(1))
        response = client.delete("/api/setup")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["phase"], {"cancelling", "cancelled"})
        cancelled = self.state(client, "cancelled")
        self.assertTrue(worker.cancelled.is_set())
        self.assertIsNone(cancelled["result"])
        worker.release.set()
        self.assertEqual(client.post("/api/setup", json={"component": "conversation"}).status_code, 202)
        self.state(client, "completed")
        self.assertEqual(len(worker.calls), 2)

    def test_closing_app_cancels_and_joins_only_its_active_fixture_worker(self):
        worker = ControlledWorker()
        manager = SetupManager(self.settings, workers={"conversation": worker})
        app = create_app(self.settings, providers=self.providers, setup_manager=manager)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            client.post("/api/setup", json={"component": "conversation"})
            self.assertTrue(worker.started.wait(1))
        self.assertTrue(worker.cancelled.is_set())
        self.assertTrue(worker.finished.is_set())
        self.assertEqual(manager.snapshot()["state"], "cancelled")
        with self.assertRaises(SetupUnavailable):
            asyncio.run(manager.start("conversation"))

    def test_setup_get_and_fixture_completion_preserve_environment_and_existing_dotenv(self):
        dotenv = self.directory / ".env"
        original = b"# existing user configuration\nIVI_CPU_THREADS=2\n"
        dotenv.write_bytes(original)
        worker = ControlledWorker()
        worker.release.set()
        with patch.dict(os.environ, {"IVI_SETUP_TEST_SENTINEL": "keep-this-fixture-value", "IVI_LLM_MODEL": "fixture-original.gguf", "IVI_CPU_THREADS": "2"}):
            original_names = set(os.environ)
            client, _ = self.client({"conversation": worker})
            client.get("/api/setup")
            client.post("/api/setup", json={"component": "conversation"})
            self.state(client, "completed")
            self.assertEqual(os.environ["IVI_SETUP_TEST_SENTINEL"], "keep-this-fixture-value")
            self.assertEqual(os.environ["IVI_LLM_MODEL"], "fixture-original.gguf")
            self.assertEqual(os.environ["IVI_CPU_THREADS"], "2")
            self.assertEqual(set(os.environ), original_names)
            self.assertEqual(dotenv.read_bytes(), original)
            self.assertFalse((self.settings.data_dir / ".env").exists())

    def test_progress_is_bounded_finite_sanitized_and_snapshot_is_detached(self):
        worker = ControlledWorker()
        client, manager = self.client({"conversation": worker})
        client.post("/api/setup", json={"component": "conversation"})
        self.assertTrue(worker.started.wait(1))
        manager._progress({"progress": 150, "message": "Fixture url https://fake-user:fake-password@example.invalid/model"})
        state = manager.snapshot()
        self.assertEqual(state["progress"], 100)
        self.assertNotIn("fake-password", state["message"])
        state["log"].append("mutated copy")
        state["components"]["conversation"]["can_install"] = False
        self.assertNotIn("mutated copy", manager.snapshot()["log"])
        self.assertTrue(manager.snapshot()["can_install"])
        for invalid in [float("nan"), float("inf"), True, "50"]:
            manager._progress({"progress": invalid})
            self.assertIsNone(manager.snapshot()["progress"])
        worker.release.set()
        self.state(client, "completed")

    def test_render_preferences_default_eco_and_persist_strictly(self):
        client, _ = self.client()
        defaults = client.get("/api/status").json()["settings"]
        self.assertEqual(defaults["performance_mode"], "eco")
        self.assertTrue(defaults["animation_enabled"])
        updated = client.patch("/api/settings", json={"performance_mode": "balanced", "animation_enabled": False})
        self.assertEqual(updated.status_code, 200)
        restored, _ = self.client()
        settings = restored.get("/api/status").json()["settings"]
        self.assertEqual(settings["performance_mode"], "balanced")
        self.assertFalse(settings["animation_enabled"])
        for invalid in [{"performance_mode": "turbo"}, {"performance_mode": True}, {"animation_enabled": "false"}]:
            self.assertEqual(client.patch("/api/settings", json=invalid).status_code, 422)


if __name__ == "__main__":
    unittest.main()

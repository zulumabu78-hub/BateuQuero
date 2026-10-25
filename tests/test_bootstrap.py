"""Offline bootstrap contracts: fixture bytes are never executed as programs."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import unquote
import zipfile

from ivi import bootstrap


REVISION = "a" * 40
GGUF = b"GGUF offline contract fixture, not a usable model"


class Response(io.BytesIO):
    def __init__(self, data: bytes, *, declared_length: int | None = None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if declared_length is None else declared_length)}


def archive_bytes(extra_entries=()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("llama-server.exe", b"fixture executable: never run")
        archive.writestr("ggml-cpu-x64.dll", b"baseline fixture DLL")
        archive.writestr("ggml-cpu-piledriver.dll", b"Piledriver fixture DLL")
        for name, data in extra_entries:
            archive.writestr(name, data)
    return buffer.getvalue()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cancel = threading.Event()
        self.progress = []
        self.settings = SimpleNamespace(data_dir=self.root / "data", llm_model=None, llm_engine=None)
        self.archive = archive_bytes()
        self.archive_hash = hashlib.sha256(self.archive).hexdigest()
        self.requests = []

    def _download(self, destination, data, checksum=None, callback=None):
        with patch.object(bootstrap, "_open", return_value=Response(data)):
            return bootstrap.download_verified(
                "https://example.invalid/fixture", destination,
                checksum or hashlib.sha256(data).hexdigest(), self.cancel,
                callback or self.progress.append, phase="fixture",
            )

    def _metadata(self, *, checksum=None):
        return {"sha": REVISION, "siblings": [{
            "rfilename": bootstrap.SPECS["llm"]["required"][0],
            "lfs": {"sha256": checksum or hashlib.sha256(GGUF).hexdigest(), "size": len(GGUF)},
        }]}

    def _transport(self, url):
        self.requests.append(url)
        return Response(self.archive if url == bootstrap.ENGINE_URL else GGUF)

    def _conversation_context(self, *, metadata=None, probe_error=None):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(bootstrap, "conversation_setup_capability", return_value={"can_install": True, "reason": ""}))
        stack.enter_context(patch.object(bootstrap, "ENGINE_SHA256", self.archive_hash))
        stack.enter_context(patch.object(bootstrap, "_open", side_effect=self._transport))
        metadata_mock = stack.enter_context(patch.object(bootstrap, "_json", return_value=metadata or self._metadata()))
        probe_mock = stack.enter_context(patch.object(bootstrap, "_probe_engine", side_effect=probe_error))
        return stack, metadata_mock, probe_mock

    def _voice_fixtures(self):
        stt, tts = bootstrap.SPECS["stt"], bootstrap.SPECS["tts"]
        files = {
            stt["repo"]: {**{name: (b"CT2 fixture" if name == "model.bin" else b'{"fixture":true}') for name in stt["required"]}, "vocabulary.json": b'["fixture"]'},
            tts["repo"]: {tts["required"][0]: b"ONNX fixture: never loaded", tts["required"][1]: b'{"audio":{"sample_rate":22050}}', tts["optional"][0]: b"Voice license fixture"},
        }
        metadata = {}
        for repo, contents in files.items():
            siblings = []
            for name, content in contents.items():
                record = {"rfilename": name, "size": len(content)}
                if name.endswith((".bin", ".onnx")):
                    record["lfs"] = {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
                else:
                    record["blobId"] = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
                siblings.append(record)
            metadata[repo] = {"sha": REVISION, "siblings": siblings}
        return files, metadata

    def _voice_context(self, *, fail_probe=False, corrupt_download=False):
        files, metadata_values = self._voice_fixtures()
        self.voice_requests = []

        def metadata(url):
            for repo, info in metadata_values.items():
                if f"/api/models/{repo}/revision/" in url:
                    return info
            raise AssertionError(f"Unexpected metadata fixture URL: {url}")

        def transport(url):
            self.voice_requests.append(url)
            for repo, content_map in files.items():
                prefix = f"https://huggingface.co/{repo}/resolve/{REVISION}/"
                if url.startswith(prefix):
                    name = unquote(url[len(prefix):].split("?", 1)[0])
                    content = content_map[name]
                    return Response(b"x" * len(content) if corrupt_download else content)
            raise AssertionError(f"Unexpected model fixture URL: {url}")

        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(bootstrap, "voice_setup_capability", return_value={"can_install": True}))
        package_runner = stack.enter_context(patch.object(bootstrap, "_run_python", side_effect=[None, bootstrap.BootstrapError("fixture incompatible CPU")] if fail_probe else None))
        metadata_mock = stack.enter_context(patch.object(bootstrap, "_json", side_effect=metadata))
        stack.enter_context(patch.object(bootstrap, "_open", side_effect=transport))
        return stack, package_runner, metadata_mock

    def test_verified_download_is_reused_without_transport(self):
        destination = self.root / "model.gguf"
        self.assertEqual(self._download(destination, GGUF), destination)
        with patch.object(bootstrap, "_open") as transport:
            result = bootstrap.download_verified("https://example.invalid/fixture", destination, hashlib.sha256(GGUF).hexdigest(), self.cancel, self.progress.append, phase="fixture")
        self.assertEqual(result.read_bytes(), GGUF)
        transport.assert_not_called()

    def test_integrity_failure_preserves_previous_file_and_other_partial(self):
        destination = self.root / "model.gguf"
        destination.write_bytes(b"previous valid user file")
        other_partial = destination.with_name(destination.name + ".part-other-job")
        other_partial.write_bytes(b"unrelated partial")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "SHA256"):
            self._download(destination, b"wrong data", checksum=hashlib.sha256(GGUF).hexdigest())
        self.assertEqual(destination.read_bytes(), b"previous valid user file")
        self.assertEqual(other_partial.read_bytes(), b"unrelated partial")
        self.assertEqual(list(self.root.glob("*.part-*")), [other_partial])

    def test_cancellation_during_transfer_cleans_only_own_partial(self):
        destination = self.root / "model.gguf"
        destination.write_bytes(b"previous user file")

        def cancel_after_chunk(event):
            self.progress.append(event)
            if event.get("downloaded_bytes"):
                self.cancel.set()

        with self.assertRaises(bootstrap.BootstrapCancelled):
            self._download(destination, GGUF, callback=cancel_after_chunk)
        self.assertEqual(destination.read_bytes(), b"previous user file")
        self.assertEqual(list(self.root.glob("*.part-*")), [])

    def test_https_checksum_and_download_size_are_required(self):
        with patch.object(bootstrap, "build_opener") as transport:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "HTTPS"):
                bootstrap._open("http://example.invalid/fixture")
            transport.assert_not_called()
        with patch.object(bootstrap, "_open") as transport:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "SHA256"):
                bootstrap.download_verified("https://example.invalid/fixture", self.root / "missing/file", "", self.cancel, self.progress.append, phase="fixture")
            transport.assert_not_called()
        with patch.object(bootstrap, "_open", return_value=Response(b"", declared_length=bootstrap.MAX_DOWNLOAD_BYTES + 1)):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "limite"):
                bootstrap.download_verified("https://example.invalid/fixture", self.root / "oversize", "0" * 64, self.cancel, self.progress.append, phase="fixture")
        self.assertFalse((self.root / "oversize").exists())
        self.assertEqual(list(self.root.glob("*.part-*")), [])

    def test_safe_extraction_retains_all_variants_and_detects_tampered_cache(self):
        archive = self.root / "engine.zip"
        archive.write_bytes(self.archive)
        directory = self.root / "engine"
        executable = bootstrap._extract_engine(archive, directory, self.cancel)
        self.assertEqual(executable, directory / "llama-server.exe")
        self.assertEqual((directory / "ggml-cpu-x64.dll").read_bytes(), b"baseline fixture DLL")
        self.assertEqual((directory / "ggml-cpu-piledriver.dll").read_bytes(), b"Piledriver fixture DLL")
        self.assertEqual(bootstrap._extract_engine(archive, directory, self.cancel), executable)
        (directory / "ggml-cpu-piledriver.dll").write_bytes(b"changed DLL")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "alterado"):
            bootstrap._extract_engine(archive, directory, self.cancel)
        self.assertEqual((directory / "ggml-cpu-piledriver.dll").read_bytes(), b"changed DLL")

    def test_zip_traversal_and_symlink_are_rejected_before_extraction(self):
        symlink = zipfile.ZipInfo("link.dll")
        symlink.create_system = 3
        symlink.external_attr = 0o120777 << 16
        cases = [archive_bytes([("../escape.txt", b"escape")]), archive_bytes([(symlink, b"../outside")])]
        for index, payload in enumerate(cases):
            with self.subTest(index=index):
                archive = self.root / f"unsafe-{index}.zip"
                archive.write_bytes(payload)
                directory = self.root / f"engine-{index}"
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap._extract_engine(archive, directory, self.cancel)
                self.assertFalse(directory.exists())
        self.assertFalse((self.root / "escape.txt").exists())

    def test_conversation_pins_model_commit_and_activates_only_after_probe(self):
        stack, metadata, probe = self._conversation_context()
        with stack:
            result = bootstrap.install_conversation(self.settings, self.progress.append, self.cancel)
        self.assertTrue(result["installed"])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0], bootstrap.ENGINE_URL)
        self.assertIn(f"/resolve/{REVISION}/", self.requests[1])
        self.assertNotIn("/resolve/main/", self.requests[1])
        self.assertEqual(Path(result["model_path"]).read_bytes(), GGUF)
        probe.assert_called_once()
        metadata.assert_called_once()
        saved = json.loads(Path(result["runtime_config"]).read_text("utf-8"))
        self.assertEqual(saved["llm_engine"], result["engine_path"])
        self.assertEqual(saved["llm_model"], result["model_path"])
        self.assertEqual(self.progress[-1]["progress"], 100)

    def test_existing_user_model_runtime_settings_and_dotenv_are_preserved(self):
        self.settings.data_dir.mkdir()
        configured = self.root / "my-custom-model.gguf"
        configured.write_bytes(GGUF)
        engine = self.root / "configured-engine.exe"
        engine.write_bytes(b"user-configured engine fixture: never executed")
        self.settings.llm_model, self.settings.llm_engine = configured, engine
        environment = self.root / ".env"
        environment.write_text("IVI_LLM_MODEL=my-custom-model.gguf\n", encoding="utf-8")
        runtime = self.settings.data_dir / "runtime.json"
        runtime.write_text(json.dumps({"user_preference": {"keep": True}}), encoding="utf-8")
        with patch.object(bootstrap, "conversation_setup_capability", return_value={"can_install": True}), patch.object(bootstrap, "_probe_engine") as probe, patch.object(bootstrap, "_open") as transport, patch.object(bootstrap, "_json") as metadata:
            result = bootstrap.install_conversation(self.settings, self.progress.append, self.cancel)
        self.assertEqual(result["model_path"], str(configured.resolve()))
        self.assertEqual(json.loads(runtime.read_text("utf-8"))["user_preference"], {"keep": True})
        self.assertEqual(environment.read_text("utf-8"), "IVI_LLM_MODEL=my-custom-model.gguf\n")
        transport.assert_not_called()
        metadata.assert_not_called()
        probe.assert_called_once_with(engine.resolve())

    def test_explicit_server_and_model_override_older_runtime_paths(self):
        self.settings.data_dir.mkdir()
        explicit_engine = self.root / "explicit-server.exe"
        explicit_model = self.root / "explicit-model.gguf"
        legacy_engine = self.root / "legacy-engine.exe"
        for path, data in ((explicit_engine, b"explicit fixture"), (explicit_model, GGUF), (legacy_engine, b"legacy fixture")):
            path.write_bytes(data)
        previous_engine = self.settings.data_dir / "previous-server.exe"
        previous_model = self.settings.data_dir / "previous-model.gguf"
        previous_engine.write_bytes(b"previous engine")
        previous_model.write_bytes(GGUF)
        runtime = self.settings.data_dir / "runtime.json"
        runtime.write_text(json.dumps({"llm_engine": str(previous_engine), "llm_model": str(previous_model), "user_preference": "preserve"}), encoding="utf-8")
        self.settings.llm_server, self.settings.llm_engine, self.settings.llm_model = explicit_engine, legacy_engine, explicit_model
        with patch.object(bootstrap, "conversation_setup_capability", return_value={"can_install": True}), patch.object(bootstrap, "_probe_engine") as probe, patch.object(bootstrap, "_open") as transport, patch.object(bootstrap, "_json") as metadata:
            result = bootstrap.install_conversation(self.settings, self.progress.append, self.cancel)
        probe.assert_called_once_with(explicit_engine.resolve())
        transport.assert_not_called()
        metadata.assert_not_called()
        saved = json.loads(runtime.read_text("utf-8"))
        self.assertEqual(result["engine_path"], str(explicit_engine.resolve()))
        self.assertEqual(saved["llm_engine"], str(explicit_engine.resolve()))
        self.assertEqual(saved["llm_model"], str(explicit_model.resolve()))
        self.assertEqual(saved["user_preference"], "preserve")
        self.assertEqual(previous_engine.read_bytes(), b"previous engine")

    def test_escaping_runtime_paths_are_refused_before_download_or_activation(self):
        outside = self.root / "outside-fixture"
        outside.write_bytes(GGUF)
        for name in ("llm_engine", "llm_model", "tts_model"):
            with self.subTest(name=name):
                data = self.root / ("escaped-" + name)
                data.mkdir()
                runtime = data / "runtime.json"
                original = json.dumps({name: str(outside), "user_preference": "preserve exact bytes"}) + "\n"
                runtime.write_text(original, encoding="utf-8")
                settings = SimpleNamespace(data_dir=data)
                events = []
                with patch.object(bootstrap, "conversation_setup_capability", return_value={"can_install": True}), patch.object(bootstrap, "voice_setup_capability", return_value={"can_install": True}), patch.object(bootstrap, "_probe_engine") as probe, patch.object(bootstrap, "_run_python") as packages, patch.object(bootstrap, "_open") as transport:
                    worker = bootstrap.install_voice if name == "tts_model" else bootstrap.install_conversation
                    with self.assertRaisesRegex(bootstrap.BootstrapError, "fora da pasta de dados"):
                        worker(settings, events.append, self.cancel)
                transport.assert_not_called()
                probe.assert_not_called()
                packages.assert_not_called()
                self.assertEqual(runtime.read_text("utf-8"), original)
                self.assertFalse(any(event.get("progress") == 100 for event in events))

    def test_probe_or_model_integrity_failure_never_activates_runtime(self):
        for failure in ("probe", "checksum"):
            with self.subTest(failure=failure):
                settings = SimpleNamespace(data_dir=self.root / failure, llm_model=None, llm_engine=None)
                events = []
                metadata_value = self._metadata(checksum="0" * 64) if failure == "checksum" else None
                stack, metadata, _ = self._conversation_context(metadata=metadata_value, probe_error=bootstrap.BootstrapError("missing runtime") if failure == "probe" else None)
                with stack:
                    with self.assertRaises(bootstrap.BootstrapError):
                        bootstrap.install_conversation(settings, events.append, self.cancel)
                self.assertFalse((settings.data_dir / "runtime.json").exists())
                self.assertFalse(any(event.get("progress") == 100 for event in events))
                self.assertEqual(list(settings.data_dir.rglob("*.part-*")), [])
                if failure == "probe":
                    metadata.assert_not_called()

    def test_unsupported_platform_stops_before_download_or_data_writes(self):
        with patch.object(bootstrap, "conversation_setup_capability", return_value={"can_install": False, "reason": "unsupported test platform"}), patch.object(bootstrap, "_open") as transport:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "unsupported"):
                bootstrap.install_conversation(self.settings, self.progress.append, self.cancel)
        transport.assert_not_called()
        self.assertFalse(self.settings.data_dir.exists())
        self.assertEqual(self.progress, [])

    def test_git_blob_hash_is_verified_and_mismatch_preserves_existing_file(self):
        data = b'{"sample_rate":22050}'
        expected = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        destination = self.root / "voice.json"
        destination.write_bytes(b"previous user configuration")
        with patch.object(bootstrap, "_open", return_value=Response(b"tampered bytes")):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "hash Git"):
                bootstrap._download_git_blob("https://example.invalid/config", destination, expected, self.cancel, self.progress.append, phase="tts", start=0, end=90)
        self.assertEqual(destination.read_bytes(), b"previous user configuration")
        self.assertEqual(list(self.root.glob("*.part-*")), [])
        with patch.object(bootstrap, "_open", return_value=Response(data)):
            bootstrap._download_git_blob("https://example.invalid/config", destination, expected, self.cancel, self.progress.append, phase="tts", start=0, end=90)
        self.assertEqual(destination.read_bytes(), data)

    def test_voice_setup_uses_binary_packages_and_pinned_verified_assets(self):
        stack, package_runner, metadata = self._voice_context()
        with stack:
            result = bootstrap.install_voice(self.settings, self.progress.append, self.cancel)
        commands = [call.args[0] for call in package_runner.call_args_list]
        self.assertEqual(commands[0], ["-m", "pip", "install", "--only-binary=:all:", "--quiet", "--disable-pip-version-check", "faster-whisper==1.2.1", "piper-tts==1.8.0"])
        self.assertEqual(commands[1], ["-c", "import faster_whisper; from piper import PiperVoice"])
        self.assertEqual(metadata.call_count, 2)
        self.assertTrue(self.voice_requests)
        self.assertTrue(all(f"/resolve/{REVISION}/" in url for url in self.voice_requests))
        self.assertEqual(result["prepared_components"], 2)
        saved = json.loads(Path(result["runtime_config"]).read_text("utf-8"))
        self.assertTrue(Path(saved["stt_model"]).is_dir())
        self.assertTrue(Path(saved["tts_model"]).is_file())
        self.assertTrue(Path(saved["tts_config"]).is_file())
        records = [item for component in result["manifest"]["components"].values() for item in component["files"]]
        self.assertTrue(any("lfs_sha256" in item for item in records))
        self.assertTrue(any("git_blob_sha1" in item for item in records))
        self.assertEqual(self.progress[-1]["progress"], 100)

    def test_voice_setup_preserves_custom_paths_runtime_preferences_and_dotenv(self):
        self.settings.data_dir.mkdir()
        stt = self.root / "custom-stt"
        stt.mkdir()
        for name in bootstrap.SPECS["stt"]["required"] + ["vocabulary.json"]:
            (stt / name).write_bytes(b"custom fixture")
        tts, config = self.root / "custom.onnx", self.root / "custom.onnx.json"
        tts.write_bytes(b"custom voice fixture")
        config.write_bytes(b'{"custom":true}')
        self.settings.stt_model, self.settings.tts_model, self.settings.tts_config = stt, tts, config
        environment = self.root / ".env"
        environment.write_text("USER_CONFIG=preserve\n", encoding="utf-8")
        runtime = self.settings.data_dir / "runtime.json"
        runtime.write_text(json.dumps({"user_preference": "preserve"}), encoding="utf-8")
        with patch.object(bootstrap, "voice_setup_capability", return_value={"can_install": True}), patch.object(bootstrap, "_run_python"), patch.object(bootstrap, "_open") as transport, patch.object(bootstrap, "_json") as metadata:
            result = bootstrap.install_voice(self.settings, self.progress.append, self.cancel)
        self.assertEqual(result["stt_model"], str(stt.resolve()))
        self.assertEqual(result["tts_model"], str(tts.resolve()))
        self.assertEqual(result["tts_config"], str(config.resolve()))
        self.assertEqual(json.loads(runtime.read_text("utf-8"))["user_preference"], "preserve")
        self.assertEqual(environment.read_text("utf-8"), "USER_CONFIG=preserve\n")
        transport.assert_not_called()
        metadata.assert_not_called()

    def test_voice_probe_or_integrity_failure_never_activates_configuration(self):
        for failure in ("probe", "checksum"):
            with self.subTest(failure=failure):
                data = self.root / ("voice-" + failure)
                data.mkdir()
                runtime = data / "runtime.json"
                original = '{"user_preference":"keep exact original"}\n'
                runtime.write_text(original, encoding="utf-8")
                settings = SimpleNamespace(data_dir=data)
                events = []
                stack, _, metadata = self._voice_context(fail_probe=failure == "probe", corrupt_download=failure == "checksum")
                with stack:
                    with self.assertRaises(bootstrap.BootstrapError):
                        bootstrap.install_voice(settings, events.append, self.cancel)
                self.assertEqual(runtime.read_text("utf-8"), original)
                self.assertFalse(any(event.get("progress") == 100 for event in events))
                self.assertEqual(list(data.rglob("*.part-*")), [])
                if failure == "probe":
                    metadata.assert_not_called()

    def test_python_package_cancellation_terminates_only_spawned_process(self):
        process = Mock()

        def running_then_cancel():
            self.cancel.set()
            return None

        process.poll.side_effect = running_then_cancel
        process.wait.return_value = 0
        with patch.object(bootstrap.subprocess, "Popen", return_value=process) as spawn:
            with self.assertRaises(bootstrap.BootstrapCancelled):
                bootstrap._run_python(["-m", "pip", "--version"], self.cancel)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)
        self.assertEqual(spawn.call_args.args[0], [bootstrap.sys.executable, "-m", "pip", "--version"])
        self.assertIs(spawn.call_args.kwargs["shell"], False)

    def test_https_redirect_downgrade_is_closed_and_rejected(self):
        response = SimpleNamespace(geturl=lambda: "http://example.invalid/insecure", close=Mock())
        transport = Mock()
        transport.open.return_value = response
        with patch.object(bootstrap, "build_opener", return_value=transport) as create:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "sem HTTPS"):
                bootstrap._open("https://example.invalid/secure")
        self.assertIsInstance(create.call_args.args[0], bootstrap.HTTPSOnlyRedirect)
        response.close.assert_called_once()

    def test_redirect_handler_refuses_insecure_targets_before_parent_follow(self):
        handler = bootstrap.HTTPSOnlyRedirect()
        request = bootstrap.Request("https://example.invalid/source")
        with patch.object(bootstrap.HTTPRedirectHandler, "redirect_request") as parent:
            for target in ("http://example.invalid/insecure", "ftp://example.invalid/file"):
                with self.subTest(target=target), self.assertRaisesRegex(bootstrap.BootstrapError, "nenhuma requisicao"):
                    handler.redirect_request(request, None, 302, "Found", {}, target)
            parent.assert_not_called()
            handler.redirect_request(request, None, 302, "Found", {}, "https://example.invalid/verified")
            parent.assert_called_once_with(request, None, 302, "Found", {}, "https://example.invalid/verified")

    def test_process_errors_remove_credentials_and_bound_output(self):
        output = ("prefix " * 1000 + "\nhttps://USER_FIXTURE:PASSWORD_FIXTURE@example.invalid/wheels?token=QUERY_FIXTURE#fragment\nAuthorization: Bearer AUTH_FIXTURE\npassword=PASSWORD_VALUE\ntoken=TOKEN_VALUE\npassword='QUOTED PASSWORD'\ntoken=\"QUOTED TOKEN\"\n").encode()
        sanitized = bootstrap._sanitized_output(output)
        for secret in ("USER_FIXTURE", "PASSWORD_FIXTURE", "QUERY_FIXTURE", "AUTH_FIXTURE", "PASSWORD_VALUE", "TOKEN_VALUE", "QUOTED PASSWORD", "QUOTED TOKEN"):
            self.assertNotIn(secret, sanitized)
        self.assertIn("https://example.invalid/", sanitized)
        self.assertNotIn("wheels", sanitized)
        self.assertLessEqual(len(sanitized), 4000)

    def test_partial_custom_voice_is_not_paired_with_unrelated_default_config(self):
        custom = self.root / "custom-without-json.onnx"
        custom.write_bytes(b"custom voice fixture")
        self.settings.tts_model = custom
        with patch.object(bootstrap, "voice_setup_capability", return_value={"can_install": True}), patch.object(bootstrap, "_run_python") as package_runner, patch.object(bootstrap, "_open") as transport:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "JSON correspondente"):
                bootstrap.install_voice(self.settings, self.progress.append, self.cancel)
        self.assertEqual(custom.read_bytes(), b"custom voice fixture")
        package_runner.assert_not_called()
        transport.assert_not_called()
        self.assertFalse((self.settings.data_dir / "runtime.json").exists())


if __name__ == "__main__":
    unittest.main()

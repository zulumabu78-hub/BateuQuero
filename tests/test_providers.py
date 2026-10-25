"""Contract tests with fake native engines; these do not validate model quality."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from ivi.providers import (
    ContextWindowExceeded,
    LocalProviders,
    ProviderUnavailable,
    budget_chat_messages,
    validate_microphone_wav,
)


def wav_bytes(*, rate=16_000, channels=1, width=2, frames=1600):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(b"\x00" * (frames * channels * width))
    return output.getvalue()


class FakeTokenizer:
    def n_ctx(self):
        return 1024

    def tokenize(self, data, *, add_bos, special):
        assert add_bos is False and special is True
        return list(data)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.settings = SimpleNamespace(
            llm_model=None,
            stt_model=None,
            tts_model=None,
            tts_config=None,
            cpu_threads=2,
            context_tokens=1024,
        )
        self.provider = LocalProviders(self.settings)

    def tearDown(self):
        self.temporary.cleanup()

    def configure(self, component):
        if component == "stt":
            folder = self.root / "whisper"
            folder.mkdir()
            for name in ("model.bin", "config.json", "tokenizer.json"):
                (folder / name).write_bytes(b"test-model-placeholder")
            self.settings.stt_model = folder
        elif component == "llm":
            path = self.root / "qwen.gguf"
            path.write_bytes(b"test-model-placeholder")
            self.settings.llm_model = path
        else:
            path = self.root / "voice.onnx"
            path.write_bytes(b"test-model-placeholder")
            Path(f"{path}.json").write_text(json.dumps({"phoneme_type": "espeak"}))
            self.settings.tts_model = path

    def test_no_models_or_imports_during_initialization(self):
        with patch("ivi.providers.importlib.import_module") as importer:
            provider = LocalProviders(self.settings)
            self.assertTrue(all(not value["ready"] for value in provider.status().values()))
            importer.assert_not_called()

    def test_status_distinguishes_configured_from_loaded(self):
        self.configure("llm")
        with patch.object(self.provider, "_has_dependency", return_value=True):
            status = self.provider.status()["llm"]
        self.assertTrue(status["ready"])
        self.assertFalse(status["loaded"])
        self.assertIn("ainda não validado", status["detail"])

    def test_missing_package_is_unavailable(self):
        self.configure("llm")
        with patch.object(self.provider, "_has_dependency", return_value=False):
            self.assertFalse(self.provider.status()["llm"]["ready"])

    def test_whisper_requires_local_tokenizer(self):
        self.configure("stt")
        (self.settings.stt_model / "tokenizer.json").unlink()
        with patch.object(self.provider, "_has_dependency", return_value=True):
            self.assertFalse(self.provider.status()["stt"]["ready"])

    def test_microphone_wav_validation(self):
        validate_microphone_wav(wav_bytes())
        for invalid in (b"not wave", wav_bytes(rate=44_100), wav_bytes(channels=2), wav_bytes(width=1), wav_bytes(frames=0), wav_bytes(frames=480_001), wav_bytes()[:-50]):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                validate_microphone_wav(invalid)

    async def test_missing_model_raises_instead_of_fabricating_a_response(self):
        with self.assertRaises(ProviderUnavailable):
            async for _ in self.provider.stream_chat([{"role": "user", "content": "Olá"}], threading.Event()):
                self.fail("No unconfigured model may generate tokens")

    async def test_stopped_turn_does_not_load_model(self):
        stop = threading.Event()
        stop.set()
        with patch.object(self.provider, "_get_llm") as loader:
            tokens = [part async for part in self.provider.stream_chat([], stop)]
        self.assertEqual(tokens, [])
        loader.assert_not_called()

    async def test_llm_streams_cpu_tokens_and_honors_stop(self):
        self.configure("llm")
        calls = {}

        class Model(FakeTokenizer):
            def __init__(self, **kwargs):
                calls["load"] = kwargs

            def create_chat_completion(self, **kwargs):
                calls["generate"] = kwargs
                yield {"choices": [{"delta": {"content": "Olá"}}]}
                yield {"choices": [{"delta": {"content": ", mundo"}}]}

        stop = threading.Event()
        with patch.object(self.provider, "_has_dependency", return_value=True), patch("ivi.providers.importlib.import_module", return_value=SimpleNamespace(Llama=Model)):
            stream = self.provider.stream_chat([{"role": "user", "content": "Oi"}], stop)
            self.assertEqual(await anext(stream), "Olá")
            stop.set()
            self.assertEqual([part async for part in stream], [])
        self.assertEqual(calls["load"]["n_gpu_layers"], 0)
        self.assertEqual(calls["load"]["n_threads"], 2)
        self.assertEqual(calls["generate"]["max_tokens"], 192)

    async def test_next_llm_turn_waits_for_native_stream_cleanup(self):
        self.configure("llm")
        closing = threading.Event()
        allow_close = threading.Event()
        generations = []

        class Stream:
            def __init__(self):
                self.emitted = False

            def __iter__(self):
                return self

            def __next__(self):
                if self.emitted:
                    raise StopIteration
                self.emitted = True
                return {"choices": [{"delta": {"content": "Oi"}}]}

            def close(self):
                closing.set()
                if not allow_close.wait(timeout=2):
                    raise RuntimeError("Test did not release native cleanup")

        class Model(FakeTokenizer):
            def create_chat_completion(self, **kwargs):
                generations.append(kwargs)
                return Stream()

        self.provider._llm = Model()
        messages = [{"role": "user", "content": "Oi"}]
        first = self.provider.stream_chat(messages, threading.Event())
        second = self.provider.stream_chat(messages, threading.Event())
        with patch.object(self.provider, "_has_dependency", return_value=True):
            try:
                self.assertEqual(await anext(first), "Oi")
                self.assertTrue(await asyncio.to_thread(closing.wait, 1))
                pending = asyncio.create_task(anext(second))
                await asyncio.sleep(0.05)
                self.assertEqual(len(generations), 1)
                self.assertFalse(pending.done())
                allow_close.set()
                self.assertEqual(await asyncio.wait_for(pending, timeout=1), "Oi")
                self.assertEqual([part async for part in first], [])
                self.assertEqual([part async for part in second], [])
                self.assertEqual(len(generations), 2)
            finally:
                allow_close.set()
                await first.aclose()
                await second.aclose()

    async def test_whisper_is_local_cpu_int8_and_returns_transcript(self):
        self.configure("stt")
        calls = {}

        class Model:
            def __init__(self, path, **kwargs):
                calls["path"] = path
                calls["load"] = kwargs

            def transcribe(self, audio, **kwargs):
                self_audio = audio.read()
                assert self_audio[:4] == b"RIFF"
                calls["transcribe"] = kwargs
                return iter([SimpleNamespace(text=" Olá! "), SimpleNamespace(text=" Como vai? ")]), None

        with patch.object(self.provider, "_has_dependency", return_value=True), patch("ivi.providers.importlib.import_module", return_value=SimpleNamespace(WhisperModel=Model)):
            transcript = await self.provider.transcribe(wav_bytes())
        self.assertEqual(transcript, "Olá! Como vai?")
        self.assertTrue(calls["load"]["local_files_only"])
        self.assertEqual(calls["load"]["compute_type"], "int8")
        self.assertEqual(calls["load"]["device"], "cpu")
        self.assertEqual(calls["transcribe"]["language"], "pt")
        self.assertTrue(calls["transcribe"]["vad_filter"])

    async def test_piper_wav_uses_adjustable_rate_and_cpu(self):
        self.configure("tts")
        calls = {}

        class Voice:
            def __init__(self, **kwargs):
                calls["voice"] = kwargs

            def synthesize_wav(self, text, writer, syn_config):
                calls["text"] = text
                calls["scale"] = syn_config.length_scale
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(22_050)
                writer.writeframes(b"\x00\x00" * 100)

        def importer(name):
            if name == "piper":
                return SimpleNamespace(PiperVoice=Voice)
            if name == "piper.config":
                return SimpleNamespace(
                    SynthesisConfig=lambda **kwargs: SimpleNamespace(**kwargs),
                    PiperConfig=SimpleNamespace(from_dict=lambda config: dict(config)),
                )
            if name == "onnxruntime":
                def session(model, **kwargs):
                    calls["session"] = kwargs
                    return "fake-session"

                return SimpleNamespace(
                    disable_telemetry_events=lambda: calls.update(telemetry_disabled=True),
                    SessionOptions=SimpleNamespace,
                    ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
                    InferenceSession=session,
                )
            self.fail(f"Unexpected import {name}")

        with patch.object(self.provider, "_has_dependency", return_value=True), patch("ivi.providers.importlib.import_module", side_effect=importer):
            data = await self.provider.synthesize(" Olá. ", speech_rate=1.25)
        self.assertEqual(calls["session"]["providers"], ["CPUExecutionProvider"])
        self.assertEqual(calls["session"]["sess_options"].intra_op_num_threads, 2)
        self.assertEqual(calls["session"]["sess_options"].inter_op_num_threads, 1)
        self.assertEqual(calls["session"]["sess_options"].execution_mode, "sequential")
        self.assertTrue(calls["telemetry_disabled"])
        self.assertEqual(calls["voice"]["session"], "fake-session")
        self.assertNotIn("espeak_data_dir", calls["voice"])
        self.assertEqual(calls["text"], "Olá.")
        self.assertAlmostEqual(calls["scale"], 0.8)
        with wave.open(io.BytesIO(data), "rb") as reader:
            self.assertEqual(reader.getnframes(), 100)

    async def test_invalid_synthesis_requests_fail_before_importing(self):
        with patch("ivi.providers.importlib.import_module") as importer:
            for text, rate in [("", 1), ("x" * 2001, 1), ("Oi", 0), ("Oi", float("nan"))]:
                with self.subTest(rate=rate), self.assertRaises(ValueError):
                    await self.provider.synthesize(text, rate)
            importer.assert_not_called()

    def test_context_budget_removes_only_oldest_complete_turns(self):
        class SmallContext(FakeTokenizer):
            def n_ctx(self):
                return 512

        messages = [
            {"role": "system", "content": "s" * 20},
            {"role": "user", "content": "old question" * 10},
            {"role": "assistant", "content": "old answer" * 10},
            {"role": "user", "content": "r" * 30},
            {"role": "assistant", "content": "a" * 30},
            {"role": "user", "content": "u" * 40},
        ]
        retained = budget_chat_messages(SmallContext(), messages)
        self.assertEqual(retained, [messages[0], *messages[3:]])
        self.assertEqual(len(messages), 6, "Persistent source history must not be mutated")

    def test_context_budget_uses_native_tokens_not_character_estimates(self):
        class DenseTokenizer(FakeTokenizer):
            def n_ctx(self):
                return 512

            def tokenize(self, data, **kwargs):
                self.assert_kwargs = kwargs
                return [0] * (len(data) * 4)

        messages = [
            {"role": "system", "content": "s" * 5},
            {"role": "user", "content": "o" * 25},
            {"role": "assistant", "content": "a" * 25},
            {"role": "user", "content": "u" * 10},
        ]
        tokenizer = DenseTokenizer()
        self.assertEqual(budget_chat_messages(tokenizer, messages), [messages[0], messages[-1]])
        self.assertEqual(tokenizer.assert_kwargs, {"add_bos": False, "special": True})

    def test_context_budget_rejects_oversize_new_message_without_truncation(self):
        messages = [
            {"role": "system", "content": "Instruções"},
            {"role": "user", "content": "x" * 4000},
        ]
        with self.assertRaisesRegex(ContextWindowExceeded, "Nenhum trecho.*foi cortado"):
            budget_chat_messages(FakeTokenizer(), messages)
        self.assertEqual(len(messages[-1]["content"]), 4000)

    def test_context_budget_omits_orphan_reply_from_history_window(self):
        messages = [
            {"role": "system", "content": "Instruções"},
            {"role": "assistant", "content": "resposta sem a pergunta" * 100},
            {"role": "user", "content": "Pergunta atual"},
        ]
        self.assertEqual(budget_chat_messages(FakeTokenizer(), messages), [messages[0], messages[2]])

    async def test_oversize_context_never_reaches_native_generation(self):
        self.configure("llm")

        class Model(FakeTokenizer):
            def create_chat_completion(self, **kwargs):
                raise AssertionError("Overflow should fail before generation")

        self.provider._llm = Model()
        with patch.object(self.provider, "_has_dependency", return_value=True):
            with self.assertRaisesRegex(ContextWindowExceeded, "excedem o contexto"):
                async for _ in self.provider.stream_chat(
                    [{"role": "user", "content": "x" * 4000}], threading.Event()
                ):
                    self.fail("No tokens should be emitted")
            self.assertTrue(self.provider.status()["llm"]["ready"])


if __name__ == "__main__":
    unittest.main()

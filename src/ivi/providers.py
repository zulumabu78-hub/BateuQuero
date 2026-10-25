"""Local, lazy neural backends with no model downloads or remote API calls.

The application can start without any of the optional inference packages. A
configured backend is loaded only when a real request reaches it. Native CPU
wheels still need validation on the target machine: the AMD A4 has no AVX2 and
cannot use the GT 420 for these backends.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import threading
from typing import Any, AsyncIterator, Callable
import wave


MAX_AUDIO_SECONDS = 30
MAX_AUDIO_BYTES = MAX_AUDIO_SECONDS * 16_000 * 2 + 4_096
MAX_SPEECH_CHARACTERS = 2_000
MAX_COMPLETION_TOKENS = 192
CHAT_TEMPLATE_RESERVE = 96
CHAT_MESSAGE_RESERVE = 12


class ProviderUnavailable(RuntimeError):
    """A local dependency/model is missing or cannot be used."""


class ContextWindowExceeded(ValueError):
    """Required instructions/current user text cannot fit the local context."""


def budget_chat_messages(model: Any, messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Use the loaded tokenizer and context size; remove whole oldest turns.

    Completion tokens and a conservative text-chat template allowance are
    reserved separately. System messages and the latest user turn are never
    shortened or removed. An oversized current question gets an actionable
    error rather than silent truncation. Persistent history remains untouched.
    """
    context_size = int(model.n_ctx())
    prompt_budget = context_size - MAX_COMPLETION_TOKENS - CHAT_TEMPLATE_RESERVE
    user_indices = [index for index, message in enumerate(messages) if message["role"] == "user"]
    if not user_indices:
        raise ValueError("O histórico precisa conter uma mensagem do usuário.")
    token_counts = [
        len(model.tokenize(message["content"].encode("utf-8"), add_bos=False, special=True))
        + CHAT_MESSAGE_RESERVE
        for message in messages
    ]
    # A fixed-size database window can start with a reply whose question fell
    # outside that window. Do not send such an orphan assistant prefix as a turn.
    retained = {
        index for index, message in enumerate(messages)
        if index >= user_indices[0] or message["role"] == "system"
    }

    def fits() -> bool:
        return sum(token_counts[index] for index in retained) <= prompt_budget

    for start, end in zip(user_indices[:-1], user_indices[1:]):
        if fits():
            break
        # A historical user message and its following assistant response(s)
        # form one removable turn. Keep any system instruction in that range.
        retained.difference_update(
            index for index in range(start, end) if messages[index]["role"] != "system"
        )
    if not fits():
        raise ContextWindowExceeded(
            "A mensagem atual e as instruções excedem o contexto do modelo local "
            f"({context_size} tokens, incluindo reserva para a resposta). "
            "Reduza a mensagem ou as memórias selecionadas; alternativamente, "
            "aumente IVI_CONTEXT_TOKENS se houver RAM disponível. Nenhum trecho "
            "da mensagem atual foi cortado."
        )
    return [dict(message) for index, message in enumerate(messages) if index in retained]


def validate_microphone_wav(audio: bytes) -> None:
    """Accept bounded PCM16/16 kHz/mono utterances, including actual frame data."""
    if not isinstance(audio, bytes) or not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("Áudio ausente ou maior que o limite de 30 segundos.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as reader:
            if (
                reader.getnchannels() != 1
                or reader.getsampwidth() != 2
                or reader.getframerate() != 16_000
                or reader.getcomptype() != "NONE"
            ):
                raise ValueError("O microfone deve enviar WAV PCM16 mono a 16 kHz.")
            frames = reader.getnframes()
            if not 0 < frames <= 16_000 * MAX_AUDIO_SECONDS:
                raise ValueError("Envie uma fala entre 1 amostra e 30 segundos.")
            if len(reader.readframes(frames)) != frames * 2:
                raise ValueError("O arquivo WAV está incompleto.")
    except (wave.Error, EOFError) as error:
        raise ValueError("O áudio recebido não é um arquivo WAV válido.") from error


class LocalProviders:
    """CPU-only llama.cpp, faster-whisper and Piper adapters.

    ``status.ready`` means the package and expected local files are present; the
    detail/loaded fields distinguish configuration from successful loading. It
    never means model quality or microphone hardware has been tested.
    """

    def __init__(self, settings: Any):
        self.settings = settings
        self._llm: Any = None
        self._stt: Any = None
        self._tts: Any = None
        self._native: Any = None
        self._locks = {name: threading.Lock() for name in ("llm", "stt", "tts")}
        self._errors: dict[str, str] = {}

    @staticmethod
    def _has_dependency(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, AttributeError):
            return False

    def _runtime(self) -> dict[str, str]:
        directory = getattr(self.settings, "data_dir", None)
        if directory is None:
            return {}
        root = Path(directory).expanduser().resolve()
        try:
            path = root / "runtime.json"
            if not path.resolve().is_relative_to(root) or not path.is_file() or path.stat().st_size > 65_536:
                return {}
            values = json.loads(path.read_text("utf-8"))
            if not isinstance(values, dict):
                return {}
            selected = {}
            for name in ("llm_engine", "llm_model", "stt_model", "tts_model", "tts_config"):
                value = values.get(name)
                if not isinstance(value, str) or not value:
                    continue
                candidate = Path(value).expanduser()
                if candidate.is_absolute() and candidate.resolve().is_relative_to(root):
                    selected[name] = str(candidate.resolve())
            return selected
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _valid_path(name: str, path: Path) -> bool:
        if name == "stt_model":
            return path.is_dir() and all((path / part).is_file() for part in ("model.bin", "config.json", "tokenizer.json"))
        if name == "llm_model":
            return path.is_file() and path.suffix.lower() == ".gguf"
        return path.is_file()

    def _path(self, name: str) -> Path | None:
        value = getattr(self.settings, name, None)
        explicit = Path(value).expanduser() if value else None
        if explicit and self._valid_path(name, explicit):
            return explicit
        runtime = self._runtime().get("llm_engine" if name == "llm_server" else name)
        return Path(runtime) if runtime else explicit

    def _voice_config(self) -> Path | None:
        explicit = self._path("tts_config")
        model = self._path("tts_model")
        return explicit or (Path(f"{model}.json") if model else None)

    @property
    def _threads(self) -> int:
        return max(1, min(4, int(getattr(self.settings, "cpu_threads", 2)), max(1, (os.cpu_count() or 2) - 1)))

    def _availability(self, component: str) -> dict[str, Any]:
        package, variable = {
            "llm": ("llama_cpp", "llm_model"),
            "stt": ("faster_whisper", "stt_model"),
            "tts": ("piper", "tts_model"),
        }[component]
        path = self._path(variable)
        if path is None:
            return {"ready": False, "detail": "Modelo local não configurado.", "loaded": False}
        if component == "stt":
            required = ("model.bin", "config.json", "tokenizer.json")
            if not path.is_dir() or any(not (path / name).is_file() for name in required):
                return {
                    "ready": False,
                    "detail": "Pasta Whisper incompleta: model.bin, config.json e tokenizer.json são obrigatórios.",
                    "loaded": False,
                }
        elif not path.is_file():
            return {"ready": False, "detail": "Arquivo do modelo local não encontrado.", "loaded": False}
        if component == "llm" and path.suffix.lower() != ".gguf":
            return {"ready": False, "detail": "O modelo de linguagem deve ser um arquivo GGUF.", "loaded": False}
        if component == "llm":
            native = self._path("llm_server")
            if native and native.is_file():
                loaded = bool(self._native and self._native.loaded)
                return {
                    "ready": True,
                    "loaded": loaded,
                    "detail": "Conversa local carregada em CPU." if loaded else "Modelo e mecanismo locais instalados; o primeiro carregamento acontece ao conversar.",
                }
        if component == "tts":
            config = self._voice_config()
            if config is None or not config.is_file():
                return {"ready": False, "detail": "A voz Piper precisa do arquivo ONNX e de sua configuração JSON.", "loaded": False}
        if not self._has_dependency(package):
            return {"ready": False, "detail": f"Dependência opcional {package} não instalada.", "loaded": False}
        loaded = getattr(self, f"_{component}") is not None
        return {
            "ready": True,
            "detail": "Modelo local carregado em CPU." if loaded else "Arquivos locais presentes; carregamento sob demanda ainda não validado.",
            "loaded": loaded,
        }

    def status(self) -> dict[str, dict[str, Any]]:
        result = {name: self._availability(name) for name in ("llm", "stt", "tts")}
        for name, error in self._errors.items():
            if result[name]["ready"]:
                result[name].update(ready=False, detail=error)
        return result

    def _require(self, component: str) -> None:
        availability = self._availability(component)
        if not availability["ready"]:
            raise ProviderUnavailable(availability["detail"])

    def reset_errors(self) -> None:
        """A completed explicit setup can make a previously missing engine usable."""
        self._errors.clear()

    async def aclose(self) -> None:
        if self._native:
            await self._native.aclose()

    def _get_native(self):
        if self._native is None:
            from .native_llm import NativeEngine
            self._native = NativeEngine(self.settings, self._path("llm_server"), self._path("llm_model"))
        return self._native

    def _get_llm(self) -> Any:
        if self._llm is None:
            module = importlib.import_module("llama_cpp")
            self._llm = module.Llama(
                model_path=str(self._path("llm_model")),
                n_ctx=max(512, min(8192, int(getattr(self.settings, "context_tokens", 1024)))),
                n_threads=self._threads,
                n_threads_batch=self._threads,
                n_gpu_layers=0,
                n_batch=64,
                use_mmap=True,
                use_mlock=False,
                verbose=False,
            )
        return self._llm

    def _get_stt(self) -> Any:
        if self._stt is None:
            module = importlib.import_module("faster_whisper")
            self._stt = module.WhisperModel(
                str(self._path("stt_model")),
                device="cpu",
                compute_type="int8",
                cpu_threads=self._threads,
                num_workers=1,
                local_files_only=True,
            )
        return self._stt

    def _get_tts(self) -> Any:
        if self._tts is None:
            config_path = self._voice_config()
            assert config_path is not None
            with config_path.open(encoding="utf-8") as handle:
                config = json.load(handle)
            # Other Piper phonemizers may download additional resources. The
            # Portuguese espeak voice (and TEXT voices) are entirely local.
            if config.get("phoneme_type", "espeak") not in ("espeak", "text"):
                raise ProviderUnavailable("Esta voz requer um fonemizador extra; use uma voz Piper pt_BR local.")
            module = importlib.import_module("piper")
            config_module = importlib.import_module("piper.config")
            ort = importlib.import_module("onnxruntime")
            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = self._threads
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            # PiperVoice.load() does not accept session options. Its public
            # constructor accepts this exact session/config pair, preserving
            # the package's bundled espeak data path through its default.
            session = ort.InferenceSession(
                str(self._path("tts_model")),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._tts = module.PiperVoice(
                session=session,
                config=config_module.PiperConfig.from_dict(config),
                download_dir=self._path("tts_model").parent,
            )
        return self._tts

    async def stream_chat(
        self, messages: list[dict[str, str]], stop: threading.Event
    ) -> AsyncIterator[str]:
        """Yield model tokens without blocking asyncio; cancel between tokens.

        Cancellation cannot interrupt a native CPU kernel already running. The
        worker exits at its next token boundary and never emits further tokens
        after cancellation. Its lock remains held until native work has stopped.
        """
        if stop.is_set():
            return
        self._require("llm")
        if not messages or any(
            message.get("role") not in ("system", "user", "assistant")
            or not isinstance(message.get("content"), str)
            for message in messages
        ):
            raise ValueError("O histórico enviado ao modelo é inválido.")
        native = self._path("llm_server")
        if native and native.is_file():
            try:
                async for token in self._get_native().stream_chat(messages, stop):
                    yield token
                self._errors.pop("llm", None)
            except ContextWindowExceeded:
                raise
            except (RuntimeError, OSError) as error:
                self._errors["llm"] = str(error)
                raise RuntimeError(str(error)) from error
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        cancelled = threading.Event()

        def emit(kind: str, payload: Any = None) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))
            except RuntimeError:
                cancelled.set()  # The application event loop has shut down.

        def worker() -> None:
            stream: Any = None
            try:
                with self._locks["llm"]:
                    try:
                        if stop.is_set() or cancelled.is_set():
                            return
                        model = self._get_llm()
                        if stop.is_set() or cancelled.is_set():
                            return
                        bounded_messages = budget_chat_messages(model, messages)
                        stream = model.create_chat_completion(
                            messages=bounded_messages,
                            stream=True,
                            max_tokens=MAX_COMPLETION_TOKENS,
                            temperature=0.65,
                            top_p=0.9,
                            repeat_penalty=1.1,
                        )
                        for chunk in stream:
                            if stop.is_set() or cancelled.is_set():
                                break
                            choices = chunk.get("choices", [])
                            text = choices[0].get("delta", {}).get("content") if choices else None
                            if isinstance(text, str) and text:
                                emit("token", text)
                        self._errors.pop("llm", None)
                    finally:
                        # Closing a generator may touch native model state, so
                        # finish it before another request can acquire the model.
                        if stream is not None and hasattr(stream, "close"):
                            stream.close()
            except ContextWindowExceeded as error:
                # Oversized user input does not make the installed model bad.
                emit("error", error)
            except Exception as error:
                message = f"Falha no modelo de linguagem local: {error}"
                self._errors["llm"] = message
                emit("error", RuntimeError(message))
            finally:
                emit("done")

        future = loop.run_in_executor(None, worker)
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "done" or stop.is_set():
                    break
                if kind == "error":
                    raise payload
                yield payload
        finally:
            cancelled.set()
            # Retrieve unexpected executor failures without waiting on a native
            # token during barge-in. Normal worker errors travel via the queue.
            future.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    async def _run(self, component: str, work: Callable[[], Any]) -> Any:
        self._require(component)

        def serialized() -> Any:
            with self._locks[component]:
                result = work()
                self._errors.pop(component, None)
                return result

        try:
            return await asyncio.to_thread(serialized)
        except ProviderUnavailable:
            raise
        except Exception as error:
            message = f"Falha no componente local {component}: {error}"
            self._errors[component] = message
            raise RuntimeError(message) from error

    async def transcribe(self, wav_bytes: bytes) -> str:
        validate_microphone_wav(wav_bytes)

        def work() -> str:
            model = self._get_stt()
            segments, _ = model.transcribe(
                io.BytesIO(wav_bytes),
                language="pt",
                beam_size=1,
                best_of=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
            )
            return " ".join(segment.text.strip() for segment in segments if segment.text.strip())

        return await self._run("stt", work)

    async def synthesize(self, text: str, speech_rate: float = 1.0) -> bytes:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Não há texto para sintetizar.")
        if len(text) > MAX_SPEECH_CHARACTERS:
            raise ValueError("O trecho de voz excede 2.000 caracteres; divida-o em frases.")
        if not isinstance(speech_rate, (int, float)) or not math.isfinite(speech_rate) or not 0.5 <= speech_rate <= 2:
            raise ValueError("A velocidade da voz deve estar entre 0,5 e 2,0.")

        def work() -> bytes:
            voice = self._get_tts()
            config_module = importlib.import_module("piper.config")
            synthesis_config = config_module.SynthesisConfig(length_scale=1.0 / speech_rate)
            output = io.BytesIO()
            with wave.open(output, "wb") as writer:
                voice.synthesize_wav(text.strip(), writer, syn_config=synthesis_config)
            data = output.getvalue()
            with wave.open(io.BytesIO(data), "rb") as reader:
                if reader.getnframes() <= 0:
                    raise RuntimeError("A voz local não produziu amostras de áudio.")
            return data

        return await self._run("tts", work)

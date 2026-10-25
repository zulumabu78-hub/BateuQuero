"""Local configuration; merely importing this module never loads AI models."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw else default
    except ValueError as exc:
        raise ValueError(f"{name} deve ser um número inteiro.") from exc
    if not low <= value <= high:
        raise ValueError(f"{name} deve estar entre {low} e {high}.")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    llm_model: Path | None = None
    stt_model: Path | None = None
    tts_model: Path | None = None
    tts_config: Path | None = None
    context_tokens: int = 1024
    cpu_threads: int = 2
    speech_rate: float = 1.0
    port: int = 8765

    @classmethod
    def from_env(cls) -> "Settings":
        # Only the explicitly selected file or the current project's .env is read.
        # Existing process variables take precedence over file values.
        load_dotenv(Path(os.environ.get("IVI_ENV_FILE", ".env")), override=False)
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "IVI"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "ivi"
        data_dir = Path(os.environ.get("IVI_DATA_DIR", str(base))).expanduser().resolve()
        return cls(
            data_dir=data_dir,
            llm_model=_optional_path("IVI_LLM_MODEL"),
            stt_model=_optional_path("IVI_STT_MODEL"),
            tts_model=_optional_path("IVI_TTS_MODEL"),
            tts_config=_optional_path("IVI_TTS_CONFIG"),
            context_tokens=_bounded_int("IVI_CONTEXT_TOKENS", 1024, 512, 8192),
            cpu_threads=_bounded_int("IVI_CPU_THREADS", 2, 1, 32),
            port=_bounded_int("IVI_PORT", 8765, 1024, 65535),
        )

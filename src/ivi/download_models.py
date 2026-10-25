"""Explicit, optional downloads of small local models; never called at startup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SPECS: dict[str, dict[str, Any]] = {
    "llm": {
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "required": ["qwen2.5-0.5b-instruct-q4_k_m.gguf"],
        "optional": ["README.md", "LICENSE"],
    },
    "stt": {
        "repo": "Systran/faster-whisper-tiny",
        "required": ["model.bin", "config.json", "tokenizer.json"],
        "optional": ["vocabulary.json", "vocabulary.txt", "preprocessor_config.json", "README.md", "LICENSE"],
    },
    "tts": {
        "repo": "rhasspy/piper-voices",
        "required": [
            "pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
            "pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json",
        ],
        "optional": ["pt/pt_BR/faber/medium/MODEL_CARD", "README.md", "LICENSE"],
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata_value(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _resolve_revision(api: Any, component: str, requested_revision: str | None) -> tuple[Any, list[Any]]:
    spec = SPECS[component]
    info = api.model_info(
        spec["repo"], revision=requested_revision or "main", files_metadata=True, token=False
    )
    revision = str(info.sha or "")
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision.lower()):
        raise RuntimeError(f"O registro nao informou um commit verificavel para {spec['repo']}.")
    siblings = {item.rfilename: item for item in info.siblings or []}
    missing = [name for name in spec["required"] if name not in siblings]
    if missing:
        raise RuntimeError(f"Arquivos ausentes em {spec['repo']}@{revision}: {', '.join(missing)}")
    names = spec["required"] + [name for name in spec["optional"] if name in siblings]
    if component == "stt" and not any(name in siblings for name in ("vocabulary.json", "vocabulary.txt")):
        raise RuntimeError("O modelo STT nao contem vocabulary.json ou vocabulary.txt.")
    return info, [siblings[name] for name in names]


def download_component(api: Any, download: Any, component: str, destination: Path, revision: str | None) -> dict[str, Any]:
    """Resolve once, pin downloads to that commit, and verify available LFS hashes."""
    info, files = _resolve_revision(api, component, revision)
    repo = SPECS[component]["repo"]
    component_dir = destination / component
    component_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    print(f"{component.upper()}: {repo}@{info.sha}", flush=True)
    for item in files:
        # Selection above is an explicit list: no pickle/PyTorch checkpoints.
        path = Path(download(
            repo_id=repo,
            filename=item.rfilename,
            revision=info.sha,
            local_dir=component_dir,
            token=False,
        )).resolve()
        if not path.is_relative_to(component_dir.resolve()):
            raise RuntimeError("O downloader retornou um arquivo fora do diretorio selecionado.")
        observed_hash = sha256_file(path)
        expected_hash = _metadata_value(getattr(item, "lfs", None), "sha256")
        if expected_hash and observed_hash.lower() != str(expected_hash).lower():
            quarantine = path.with_name(path.name + f".unverified-{observed_hash[:12]}")
            if quarantine.exists():
                quarantine = path.with_name(path.name + f".unverified-{datetime.now(timezone.utc).timestamp()}")
            path.rename(quarantine)
            raise RuntimeError(f"SHA256 invalido em {item.rfilename}; arquivo isolado em {quarantine}.")
        manifest_files.append({
            "path": str(path.relative_to(destination.resolve())),
            "source_file": item.rfilename,
            "sha256": observed_hash,
            "expected_lfs_sha256": expected_hash,
            "size_bytes": path.stat().st_size,
        })
    card = getattr(info, "card_data", None)
    license_value = _metadata_value(card, "license")
    return {
        "repo": repo,
        "revision": info.sha,
        "source": f"https://huggingface.co/{repo}/tree/{info.sha}",
        "repository_license_metadata": license_value,
        "license_note": "A licenca do repositorio pode diferir da voz ou dataset; consulte os arquivos MODEL_CARD/LICENSE baixados e a fonte.",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "files": manifest_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baixa explicitamente modelos pequenos para a I.V.I.; nao usa APIs de inferencia.")
    parser.add_argument("--component", choices=["all", *SPECS], default="all")
    parser.add_argument("--directory", type=Path, help="Diretorio dos modelos (padrao: IVI_DATA_DIR/models).")
    parser.add_argument("--revision", help="Commit do repositorio; exige selecionar um unico --component.")
    parser.add_argument("--list", action="store_true", help="Mostra as fontes sem acessar a rede ou baixar arquivos.")
    args = parser.parse_args(argv)
    components = list(SPECS) if args.component == "all" else [args.component]
    if args.revision and args.component == "all":
        parser.error("--revision exige --component llm, stt ou tts.")
    if args.list:
        for component in components:
            spec = SPECS[component]
            print(f"{component}: https://huggingface.co/{spec['repo']}")
            for filename in spec["required"]:
                print(f"  {filename}")
        return 0
    try:
        from huggingface_hub import HfApi, hf_hub_download
        from .config import Settings
    except ImportError:
        print('Instale o downloader: python -m pip install -e ".[models]"', file=sys.stderr)
        return 2

    try:
        destination = (args.directory or Settings.from_env().data_dir / "models").expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {"components": {}}
        if not isinstance(manifest, dict) or not isinstance(manifest.get("components"), dict):
            raise RuntimeError("manifest.json existente tem formato invalido; preserve-o e escolha outro diretorio.")
        api = HfApi(token=False)
        for component in components:
            result = download_component(api, hf_hub_download, component, destination, args.revision)
            manifest["components"][component] = result
            # Persist completed components even if a later download is interrupted.
            temporary = manifest_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
            os.replace(temporary, manifest_path)
        print(f"\nManifesto: {manifest_path}")
        print("Caminhos para conferir no .env (nenhum arquivo .env foi alterado):")
        mapping = {
            "llm": [("IVI_LLM_MODEL", destination / "llm" / SPECS["llm"]["required"][0])],
            "stt": [("IVI_STT_MODEL", destination / "stt")],
            "tts": [
                ("IVI_TTS_MODEL", destination / "tts" / SPECS["tts"]["required"][0]),
                ("IVI_TTS_CONFIG", destination / "tts" / SPECS["tts"]["required"][1]),
            ],
        }
        for component in components:
            for name, path in mapping[component]:
                print(f"{name}={path.as_posix()}")
        print("\nRevise a licenca de cada modelo/voz na fonte registrada. Reinicie a I.V.I. para carregar os caminhos.")
        return 0
    except KeyboardInterrupt:
        print("\nDownload interrompido; componentes ja concluidos permanecem no manifesto.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Falha no download ({type(exc).__name__}): {exc}", file=sys.stderr)
        print("Confira acesso HTTPS a huggingface.co e aos hosts de arquivos indicados pelo provedor. Nao desative a verificacao TLS.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Atualizador local: somente arquivos do programa, com backup e sem instalacao."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import tomllib
from uuid import uuid4


def _safe(root: Path, relative: Path) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Caminho fora da pasta selecionada: {relative}")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"Links simbolicos nao sao atualizados: {relative}")
        current = current.parent
    return path


def _project(root: Path) -> None:
    metadata = _safe(root, Path("pyproject.toml"))
    package = _safe(root, Path("src/ivi/__init__.py"))
    try:
        name = tomllib.loads(metadata.read_text("utf-8"))["project"]["name"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"Esta pasta nao e uma instalacao valida da I.V.I.: {root}") from error
    if name != "ivi-assistant" or not package.is_file():
        raise ValueError(f"Esta pasta nao e uma instalacao valida da I.V.I.: {root}")


def _files(source: Path) -> list[Path]:
    selected = {Path(name) for name in ("README.md", "pyproject.toml", "INICIAR-IVI.cmd", "ATUALIZAR-IVI.cmd", ".env.example") if (source / name).is_file()}
    for folder in ("src/ivi", "scripts", "docs"):
        base = _safe(source, Path(folder))
        if not base.exists():
            continue
        for entry in base.rglob("*"):
            relative = entry.relative_to(source)
            _safe(source, relative)
            if not entry.is_file() or any(part in {"__pycache__", "models", ".ivi", ".venv", ".git"} for part in relative.parts):
                continue
            suffix = entry.suffix.lower()
            if (folder == "src/ivi" and (suffix == ".py" or ("static" in relative.parts and suffix in {".js", ".css", ".html", ".svg", ".json", ".png", ".webp", ".ico", ".woff2"}))) or (folder == "scripts" and suffix in {".py", ".ps1"}) or (folder == "docs" and suffix in {".md", ".json", ".png"}):
                selected.add(relative)
    return sorted(selected)


def update_installation(source: Path, target: Path) -> Path | None:
    source, target = source.resolve(strict=True), target.resolve(strict=True)
    _project(source)
    _project(target)
    if source == target:
        return None
    files = _files(source)
    for relative in files:
        _safe(source, relative)
        destination = _safe(target, relative)
        if destination.exists() and not destination.is_file():
            raise ValueError(f"O destino esperado como arquivo e uma pasta: {relative}")
    backup = _safe(target, Path(".ivi-backups") / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]))
    backup.mkdir(parents=True)
    existing = {relative for relative in files if (target / relative).exists()}
    for relative in existing:
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / relative, saved)
    touched = []
    try:
        for relative in files:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            touched.append(relative)
            shutil.copy2(source / relative, destination)
    except (Exception, KeyboardInterrupt) as error:
        failures = []
        for relative in reversed(touched):
            try:
                if relative in existing:
                    shutil.copy2(backup / relative, target / relative)
                else:
                    (target / relative).unlink(missing_ok=True)
            except OSError:
                failures.append(str(relative))
        detail = "Arquivos alterados restaurados." if not failures else "Restaure manualmente do backup: " + ", ".join(failures)
        raise RuntimeError(f"Atualizacao interrompida. {detail} Backup: {backup}") from error
    return backup


def _choose_target() -> Path | None:
    window = None
    try:
        import tkinter
        from tkinter import filedialog
        window = tkinter.Tk()
        window.withdraw()
        selected = filedialog.askdirectory(title="Selecione a pasta IVI antiga, que contem sua .venv", mustexist=True)
    except Exception:
        selected = input("Caminho da pasta IVI antiga: ").strip().strip('"')
    finally:
        if window is not None:
            window.destroy()
    return Path(selected) if selected else None


def main() -> int:
    print("Feche a janela antiga da I.V.I. e encerre o servidor com Ctrl+C antes de atualizar.")
    try:
        target = _choose_target()
        if target is None:
            print("Atualizacao cancelada. Nenhum arquivo foi alterado.")
            return 0
        backup = update_installation(Path(__file__).resolve().parents[1], target)
        if backup is None:
            print("A pasta selecionada ja contem esta versao dos arquivos; nenhuma copia foi feita.")
        else:
            print(f"Atualizacao concluida. Backup dos arquivos anteriores: {backup}")
        print(f"Agora abra INICIAR-IVI.cmd na sua pasta instalada: {target.resolve()}")
        print("Configuracao, ambiente Python e dados pessoais foram preservados.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Atualizacao cancelada.")
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Nao foi possivel atualizar: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

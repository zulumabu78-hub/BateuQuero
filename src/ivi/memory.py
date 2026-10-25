"""Explicit, local SQLite conversation history and user-approved memories."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


DEFAULT_SETTINGS: dict[str, Any] = {
    "require_wake_word": False,
    "speech_rate": 1.0,
    "voice_enabled": True,
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _content(value: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError("O conteúdo precisa ser texto.")
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError(f"Use um texto entre 1 e {maximum} caracteres.")
    return value


class MemoryStore:
    """Open a short-lived connection for each operation; usable across threads.

    The database remains on the local machine. A memory is written only when
    add_memory is explicitly called; ordinary conversation does not create facts.
    """

    def __init__(self, db_path: Path | str):
        if str(db_path) == ":memory:":
            raise ValueError("Use um arquivo SQLite para manter a memória persistente.")
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def recent_messages(self, limit: int = 30) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("O limite de mensagens deve estar entre 1 e 200.")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, role, content, created_at FROM "
                "(SELECT id, role, content, created_at FROM messages ORDER BY id DESC LIMIT ?) "
                "ORDER BY id ASC",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_message(self, role: str, content: str) -> None:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Papel de mensagem inválido.")
        content = _content(content, maximum=16000)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, _timestamp()),
            )

    def clear_history(self) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM messages")

    def list_memories(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, content, created_at FROM memories ORDER BY id DESC LIMIT 200"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_memory(self, content: str) -> dict[str, Any]:
        content = _content(content, maximum=2000)
        created_at = _timestamp()
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO memories (content, created_at) VALUES (?, ?)",
                (content, created_at),
            )
            identifier = cursor.lastrowid
        return {"id": identifier, "content": content, "created_at": created_at}

    def delete_memory(self, identifier: int) -> bool:
        if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 1:
            raise ValueError("Identificador de memória inválido.")
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE id = ?", (identifier,))
            return cursor.rowcount > 0

    def get_settings(self) -> dict[str, Any]:
        with self._connection() as connection:
            rows = connection.execute("SELECT name, value FROM settings").fetchall()
        result = dict(DEFAULT_SETTINGS)
        for row in rows:
            if row["name"] in DEFAULT_SETTINGS:
                result[row["name"]] = json.loads(row["value"])
        return result

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict) or set(values) - DEFAULT_SETTINGS.keys():
            raise ValueError("Configuração desconhecida.")
        validated: dict[str, Any] = {}
        for key, value in values.items():
            if key in {"require_wake_word", "voice_enabled"}:
                if not isinstance(value, bool):
                    raise ValueError(f"{key} deve ser verdadeiro ou falso.")
            elif key == "speech_rate":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.7 <= value <= 1.5:
                    raise ValueError("A velocidade da voz deve estar entre 0,7 e 1,5.")
                value = float(value)
            validated[key] = value
        with self._connection() as connection:
            connection.executemany(
                "INSERT INTO settings (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                [(key, json.dumps(value)) for key, value in validated.items()],
            )
        return self.get_settings()

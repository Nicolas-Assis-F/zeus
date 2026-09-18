"""Memória explícita persistente, separada do código versionado."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "zeus.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.path.chmod(0o600)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "source TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        self.connection.commit()

    def close(self):
        self.connection.close()

    def remember(self, key: str, value: str, source: str = "user"):
        if not key.strip() or not value.strip() or not source.strip():
            raise ValueError("Chave, valor e origem precisam estar preenchidos.")
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                "INSERT INTO facts VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "source=excluded.source, updated_at=excluded.updated_at",
                (key, value, source, now),
            )

    def recall(self, key: str):
        row = self.connection.execute(
            "SELECT value, source, updated_at FROM facts WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        return dict(zip(("value", "source", "updated_at"), row))

    def forget(self, key: str) -> bool:
        with self.connection:
            result = self.connection.execute("DELETE FROM facts WHERE key=?", (key,))
        return result.rowcount > 0

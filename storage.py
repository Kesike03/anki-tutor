"""Profile-scoped, locally persisted card conversations."""

import hashlib
import json
import sqlite3
import time
from pathlib import Path


class ConversationStore:
    def __init__(self, user_files: Path, collection_path: str) -> None:
        user_files.mkdir(parents=True, exist_ok=True)
        profile_id = hashlib.sha256(
            str(Path(collection_path).resolve()).encode("utf-8")
        ).hexdigest()[:24]
        self.path = user_files / f"chats-{profile_id}.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS messages_by_card ON messages(card_id, id)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS contexts (
                card_id INTEGER PRIMARY KEY,
                system_prompt TEXT NOT NULL,
                images_json TEXT NOT NULL DEFAULT '[]'
            )"""
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(contexts)")}
        if "images_json" not in columns:
            self.connection.execute(
                "ALTER TABLE contexts ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'"
            )
        self.connection.commit()

    def messages(self, card_id: int) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT role, content FROM messages WHERE card_id = ? ORDER BY id",
            (card_id,),
        ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def append(self, card_id: int, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("Unsupported message role")
        with self.connection:
            self.connection.execute(
                "INSERT INTO messages(card_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (card_id, role, content, int(time.time())),
            )

    def context(self, card_id: int) -> tuple[str, list[dict[str, str]]] | None:
        row = self.connection.execute(
            "SELECT system_prompt, images_json FROM contexts WHERE card_id = ?", (card_id,)
        ).fetchone()
        if row:
            return row[0], json.loads(row[1])
        return None

    def add_user_message(
        self, card_id: int, content: str, system_prompt: str, images: list[dict[str, str]]
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO contexts(card_id, system_prompt, images_json) VALUES (?, ?, ?)",
                (card_id, system_prompt, json.dumps(images)),
            )
            self.connection.execute(
                "INSERT INTO messages(card_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (card_id, content, int(time.time())),
            )

    def clear(self, card_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM messages WHERE card_id = ?", (card_id,))
            self.connection.execute("DELETE FROM contexts WHERE card_id = ?", (card_id,))

    def close(self) -> None:
        self.connection.close()

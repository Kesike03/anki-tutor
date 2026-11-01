"""Profile-scoped conversations, migration, and portable history backups."""

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path


class ConversationStore:
    def __init__(self, user_files: Path, collection_path: str) -> None:
        user_files.mkdir(parents=True, exist_ok=True)
        profile_id = hashlib.sha256(
            str(Path(collection_path).resolve()).encode("utf-8")
        ).hexdigest()[:24]
        self.path = user_files / f"chats-{profile_id}.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        with self.connection:
            self.connection.executescript(
                """CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY,
                    uuid TEXT NOT NULL UNIQUE,
                    card_id INTEGER NOT NULL,
                    card_label TEXT NOT NULL,
                    deck_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversations_by_card
                    ON conversations(card_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chat_messages_by_conversation
                    ON chat_messages(conversation_id, id);
                CREATE TABLE IF NOT EXISTS chat_contexts (
                    conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
                    system_prompt TEXT NOT NULL,
                    images_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS card_selection (
                    card_id INTEGER PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE
                );"""
            )
            if self.connection.execute("PRAGMA user_version").fetchone()[0] < 2:
                self._migrate_legacy()
                self.connection.execute("PRAGMA user_version = 2")

    def _migrate_legacy(self) -> None:
        tables = {
            row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "messages" not in tables:
            return
        context_columns = (
            {row[1] for row in self.connection.execute("PRAGMA table_info(contexts)")}
            if "contexts" in tables else set()
        )
        for (card_id,) in self.connection.execute(
            "SELECT DISTINCT card_id FROM messages ORDER BY card_id"
        ).fetchall():
            rows = self.connection.execute(
                "SELECT role, content, created_at FROM messages WHERE card_id = ? ORDER BY id",
                (card_id,),
            ).fetchall()
            if not rows:
                continue
            title = next((text for role, text, _ in rows if role == "user"), "New conversation")
            created_at = rows[0][2]
            conversation_id = self._insert_conversation(
                card_id, f"Card {card_id}", "", self._title(title), created_at, rows[-1][2]
            )
            self.connection.executemany(
                "INSERT INTO chat_messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                ((conversation_id, role, text, timestamp) for role, text, timestamp in rows),
            )
            if context_columns:
                images_column = "images_json" if "images_json" in context_columns else "'[]'"
                context = self.connection.execute(
                    f"SELECT system_prompt, {images_column} FROM contexts WHERE card_id = ?",
                    (card_id,),
                ).fetchone()
                if context:
                    self.connection.execute(
                        "INSERT INTO chat_contexts VALUES (?, ?, ?)",
                        (conversation_id, *context),
                    )
            self.connection.execute(
                "INSERT INTO card_selection(card_id, conversation_id) VALUES (?, ?)",
                (card_id, conversation_id),
            )
        self.connection.execute("DROP TABLE IF EXISTS messages")
        self.connection.execute("DROP TABLE IF EXISTS contexts")

    @staticmethod
    def _title(text: str) -> str:
        return " ".join(text.split())[:64] or "New conversation"

    def _insert_conversation(
        self, card_id: int, card_label: str, deck_name: str, title: str,
        created_at: int, updated_at: int, identity: str | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """INSERT INTO conversations
               (uuid, card_id, card_label, deck_name, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (identity or uuid.uuid4().hex, card_id, card_label, deck_name, title, created_at, updated_at),
        )
        return cursor.lastrowid

    def create(self, card_id: int, card_label: str, deck_name: str) -> int:
        now = int(time.time())
        with self.connection:
            conversation_id = self._insert_conversation(
                card_id, card_label, deck_name, "New conversation", now, now
            )
            self.select(card_id, conversation_id)
        return conversation_id

    def select(self, card_id: int, conversation_id: int) -> None:
        row = self.connection.execute(
            "SELECT card_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None or row[0] != card_id:
            raise ValueError("Conversation does not belong to this card")
        with self.connection:
            self.connection.execute(
                """INSERT INTO card_selection(card_id, conversation_id) VALUES (?, ?)
                   ON CONFLICT(card_id) DO UPDATE SET conversation_id = excluded.conversation_id""",
                (card_id, conversation_id),
            )

    def active(self, card_id: int) -> int | None:
        row = self.connection.execute(
            """SELECT c.id FROM card_selection AS s
               JOIN conversations AS c ON c.id = s.conversation_id
               WHERE s.card_id = ? AND c.card_id = ?""", (card_id, card_id),
        ).fetchone()
        if row:
            return row[0]
        row = self.connection.execute(
            "SELECT id FROM conversations WHERE card_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (card_id,),
        ).fetchone()
        return row[0] if row else None

    def update_card(self, card_id: int, card_label: str, deck_name: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE conversations SET card_label = ?, deck_name = ? WHERE card_id = ?",
                (card_label, deck_name, card_id),
            )

    def list_conversations(self, card_id: int | None = None) -> list[dict]:
        where = "WHERE c.card_id = ?" if card_id is not None else ""
        rows = self.connection.execute(
            f"""SELECT c.id, c.uuid, c.card_id, c.card_label, c.deck_name,
                       c.title, c.created_at, c.updated_at, COUNT(m.id)
                FROM conversations AS c
                LEFT JOIN chat_messages AS m ON m.conversation_id = c.id
                {where}
                GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC""",
            (card_id,) if card_id is not None else (),
        ).fetchall()
        fields = ("id", "uuid", "card_id", "card_label", "deck_name", "title", "created_at", "updated_at", "message_count")
        return [dict(zip(fields, row)) for row in rows]

    def messages(self, conversation_id: int) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT role, content FROM chat_messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def context(self, conversation_id: int) -> tuple[str, list[dict[str, str]]] | None:
        row = self.connection.execute(
            "SELECT system_prompt, images_json FROM chat_contexts WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def add_user_message(
        self, conversation_id: int, content: str, system_prompt: str, images: list[dict[str, str]]
    ) -> None:
        now = int(time.time())
        with self.connection:
            first = not self.messages(conversation_id)
            self.connection.execute(
                "INSERT OR IGNORE INTO chat_contexts VALUES (?, ?, ?)",
                (conversation_id, system_prompt, json.dumps(images)),
            )
            self.connection.execute(
                "INSERT INTO chat_messages(conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (conversation_id, content, now),
            )
            self.connection.execute(
                "UPDATE conversations SET title = CASE WHEN ? THEN ? ELSE title END, updated_at = ? WHERE id = ?",
                (first, self._title(content), now, conversation_id),
            )

    def append(self, conversation_id: int, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("Unsupported message role")
        with self.connection:
            self.connection.execute(
                "INSERT INTO chat_messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, int(time.time())),
            )
            self.connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (int(time.time()), conversation_id),
            )

    def delete(self, conversation_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def delete_card(self, card_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM conversations WHERE card_id = ?", (card_id,))

    def delete_all(self) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM conversations")
            self.connection.execute("DELETE FROM card_selection")

    def export_data(self) -> dict:
        conversations = []
        for entry in self.list_conversations():
            backup = {key: value for key, value in entry.items() if key not in ("id", "message_count")}
            backup["messages"] = self.messages(entry["id"])
            context = self.context(entry["id"])
            backup["context"] = {
                "system_prompt": context[0], "images": context[1]
            } if context else None
            conversations.append(backup)
        return {"format": "anki-tutor-history", "version": 1, "conversations": conversations}

    def import_data(self, backup: dict) -> tuple[int, int]:
        if not isinstance(backup, dict) or backup.get("format") != "anki-tutor-history" or backup.get("version") != 1:
            raise ValueError("Unsupported history file")
        conversations = backup.get("conversations")
        if not isinstance(conversations, list):
            raise ValueError("Invalid conversations")
        identities = set()
        for entry in conversations:
            if not isinstance(entry, dict) or not isinstance(entry.get("uuid"), str) or entry["uuid"] in identities:
                raise ValueError("Invalid conversation identifier")
            identities.add(entry["uuid"])
            if not isinstance(entry.get("card_id"), int) or entry["card_id"] <= 0:
                raise ValueError("Invalid card identifier")
            if any(not isinstance(entry.get(key), str) for key in ("card_label", "deck_name", "title")):
                raise ValueError("Invalid conversation metadata")
            if any(not isinstance(entry.get(key), int) for key in ("created_at", "updated_at")):
                raise ValueError("Invalid conversation timestamps")
            messages = entry.get("messages")
            if not isinstance(messages, list) or any(
                not isinstance(message, dict) or message.get("role") not in ("user", "assistant")
                or not isinstance(message.get("content"), str) for message in messages
            ):
                raise ValueError("Invalid messages")
            context = entry.get("context")
            if context is not None and (
                not isinstance(context, dict) or not isinstance(context.get("system_prompt"), str)
                or not isinstance(context.get("images"), list)
                or any(not isinstance(image, dict) or any(not isinstance(image.get(key), str) for key in ("name", "mime", "data")) for image in context["images"])
            ):
                raise ValueError("Invalid context")
        added = skipped = 0
        with self.connection:
            for entry in conversations:
                if self.connection.execute("SELECT 1 FROM conversations WHERE uuid = ?", (entry["uuid"],)).fetchone():
                    skipped += 1
                    continue
                conversation_id = self._insert_conversation(
                    entry["card_id"], entry["card_label"], entry["deck_name"],
                    entry["title"], entry["created_at"], entry["updated_at"], entry["uuid"],
                )
                self.connection.executemany(
                    "INSERT INTO chat_messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                    ((conversation_id, message["role"], message["content"], entry["created_at"])
                     for message in entry["messages"]),
                )
                if entry["context"] is not None:
                    self.connection.execute(
                        "INSERT INTO chat_contexts VALUES (?, ?, ?)",
                        (conversation_id, entry["context"]["system_prompt"], json.dumps(entry["context"]["images"])),
                    )
                added += 1
        return added, skipped

    def close(self) -> None:
        self.connection.close()

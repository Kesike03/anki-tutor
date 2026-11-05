"""Profile-local token usage ledger and aggregations."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path


class UsageStore:
    def __init__(self, user_files: Path, collection_path: str) -> None:
        user_files.mkdir(parents=True, exist_ok=True)
        profile_id = hashlib.sha256(
            str(Path(collection_path).resolve()).encode("utf-8")
        ).hexdigest()[:24]
        self.path = user_files / f"usage-{profile_id}.sqlite3"
        self.connection = sqlite3.connect(self.path)
        with self.connection:
            self.connection.executescript(
                """CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY,
                    created_at INTEGER NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    conversation_id INTEGER,
                    message_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS usage_by_time
                    ON usage_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS usage_by_model
                    ON usage_events(model, created_at DESC);
                CREATE INDEX IF NOT EXISTS usage_by_message
                    ON usage_events(message_id);"""
            )

    @staticmethod
    def _since(days: int = 0) -> int | None:
        if not days:
            return None
        return int((time.time() - days * 86400) * 1000)

    def record(
        self, usage: dict, model: str, mode: str, source: str,
        conversation_id: int | None = None, message_id: int | None = None,
        created_at: int | None = None,
    ) -> int:
        input_tokens = int(usage.get("input", 0) or 0)
        output_tokens = int(usage.get("output", 0) or 0)
        total_tokens = int(usage.get("total", 0) or (input_tokens + output_tokens))
        cached_tokens = int(usage.get("cached", 0) or 0)
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO usage_events
                   (created_at, model, mode, source, input_tokens, output_tokens,
                    total_tokens, cached_tokens, conversation_id, message_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    created_at if created_at is not None else int(time.time() * 1000),
                    model or "", mode or "", source or "", input_tokens,
                    output_tokens, total_tokens, cached_tokens,
                    conversation_id, message_id,
                ),
            )
        return cursor.lastrowid

    def attach(self, event_ids: list[int], message_id: int) -> None:
        if not event_ids:
            return
        with self.connection:
            self.connection.executemany(
                "UPDATE usage_events SET message_id = ? WHERE id = ?",
                ((message_id, event_id) for event_id in event_ids),
            )

    def message_usage(self, message_id: int) -> dict | None:
        row = self.connection.execute(
            """SELECT SUM(input_tokens), SUM(output_tokens), SUM(total_tokens),
                      SUM(cached_tokens), COUNT(*), GROUP_CONCAT(DISTINCT model)
               FROM usage_events WHERE message_id = ?""",
            (message_id,),
        ).fetchone()
        if not row or not row[4]:
            return None
        return {
            "input": int(row[0] or 0),
            "output": int(row[1] or 0),
            "total": int(row[2] or 0),
            "cached": int(row[3] or 0),
            "requests": int(row[4] or 0),
            "model": row[5] or "",
        }

    def summary(self, days: int = 0) -> dict:
        since = self._since(days)
        where = "WHERE created_at >= ?" if since else ""
        args = (since,) if since else ()
        row = self.connection.execute(
            f"""SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens),
                       SUM(total_tokens), SUM(cached_tokens),
                       COUNT(DISTINCT model), MIN(created_at), MAX(created_at)
                FROM usage_events {where}""",
            args,
        ).fetchone()
        return {
            "requests": int(row[0] or 0),
            "input": int(row[1] or 0),
            "output": int(row[2] or 0),
            "total": int(row[3] or 0),
            "cached": int(row[4] or 0),
            "models": int(row[5] or 0),
            "first": int(row[6] or 0),
            "last": int(row[7] or 0),
        }

    def by_model(self, days: int = 0) -> list[dict]:
        since = self._since(days)
        where = "WHERE created_at >= ?" if since else ""
        args = (since,) if since else ()
        rows = self.connection.execute(
            f"""SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens),
                       SUM(total_tokens), SUM(cached_tokens)
                FROM usage_events {where}
                GROUP BY model ORDER BY SUM(total_tokens) DESC, model""",
            args,
        ).fetchall()
        return [
            {
                "model": row[0] or "(unknown)",
                "requests": int(row[1] or 0),
                "input": int(row[2] or 0),
                "output": int(row[3] or 0),
                "total": int(row[4] or 0),
                "cached": int(row[5] or 0),
            }
            for row in rows
        ]

    def by_day(self, days: int = 0) -> list[dict]:
        since = self._since(days)
        where = "WHERE created_at >= ?" if since else ""
        args = (since,) if since else ()
        rows = self.connection.execute(
            f"""SELECT strftime('%Y-%m-%d', created_at / 1000, 'unixepoch', 'localtime'),
                       COUNT(*), SUM(input_tokens), SUM(output_tokens),
                       SUM(total_tokens), SUM(cached_tokens)
                FROM usage_events {where}
                GROUP BY 1 ORDER BY 1 DESC""",
            args,
        ).fetchall()
        return [
            {
                "date": row[0] or "",
                "requests": int(row[1] or 0),
                "input": int(row[2] or 0),
                "output": int(row[3] or 0),
                "total": int(row[4] or 0),
                "cached": int(row[5] or 0),
            }
            for row in rows
        ]

    def recent(self, days: int = 0, limit: int = 100) -> list[dict]:
        since = self._since(days)
        where = "WHERE created_at >= ?" if since else ""
        args = (since,) if since else ()
        rows = self.connection.execute(
            f"""SELECT created_at, model, mode, source, input_tokens, output_tokens,
                       total_tokens, cached_tokens, conversation_id, message_id
                FROM usage_events {where}
                ORDER BY created_at DESC LIMIT ?""",
            (*args, max(1, int(limit))),
        ).fetchall()
        return [
            {
                "created_at": int(row[0]),
                "model": row[1] or "",
                "mode": row[2] or "",
                "source": row[3] or "",
                "input": int(row[4] or 0),
                "output": int(row[5] or 0),
                "total": int(row[6] or 0),
                "cached": int(row[7] or 0),
                "conversation_id": row[8],
                "message_id": row[9],
            }
            for row in rows
        ]

    def csv_rows(self, days: int = 0) -> list[dict]:
        return self.recent(days, limit=1_000_000)

    def close(self) -> None:
        self.connection.close()

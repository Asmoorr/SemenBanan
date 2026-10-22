"""Persistent reply chains and group-level character requests."""
from __future__ import annotations

import re
import json
import sqlite3
from pathlib import Path
from typing import Any


STYLE_CHANGE = re.compile(
    r"(?:\b(?:поменя\w*|измени\w*|смен[иья]\w*|настро\w*|перестань|начни|будь|стань)\b"
    r".{0,90}\b(?:характер\w*|стил\w*|манер\w*|поведен\w*|шут\w*|мат\w*|добр\w*|злее|мягче|грубее|дерзче|агрессивн\w*|вес[её]л\w*|спокойн\w*|серь[её]зн\w*|ироничн\w*|саркастичн\w*|приветлив\w*|токсичн\w*|мрачн\w*|ж[её]стч\w*|смешн\w*)\b)"
    r"|(?:\b(?:характер\w*|стил\w*|манер\w*|поведен\w*)\b.{0,90}"
    r"\b(?:поменя\w*|измен\w*|смен\w*|друг\w*)\b)"
    r"|(?:\b(?:без мата|не матерись|меньше мата|больше мата)\b)",
    re.I | re.S,
)


class ConversationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("""CREATE TABLE IF NOT EXISTS messages (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL, parent_id INTEGER,
                name TEXT NOT NULL, body TEXT NOT NULL,
                is_bot INTEGER NOT NULL, in_bot_chain INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )""")
            self.db.execute("""CREATE INDEX IF NOT EXISTS messages_recent
                ON messages(chat_id, topic_id, message_id)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS style_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL, instruction TEXT NOT NULL
            )""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS pending_replies (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                due_at REAL NOT NULL, kind TEXT NOT NULL, message_json TEXT NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )""")

    def close(self) -> None:
        self.db.close()

    def get(self, chat_id: int, message_id: int | None) -> sqlite3.Row | None:
        if message_id is None:
            return None
        return self.db.execute(
            "SELECT * FROM messages WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        ).fetchone()

    def record_incoming(self, message: dict[str, Any], bot_id: int, direct: bool) -> bool:
        chat_id = message["chat"]["id"]
        message_id = message["message_id"]
        topic_id = message.get("message_thread_id") or 0
        quoted = message.get("reply_to_message") or {}
        parent_id = quoted.get("message_id")
        with self.db:
            parent = self.get(chat_id, parent_id)
            if parent is None and parent_id is not None:
                quoted_author = quoted.get("from") or {}
                quoted_is_bot = quoted_author.get("id") == bot_id
                quoted_body = (quoted.get("text") or quoted.get("caption") or "")[:2000]
                self.db.execute(
                    "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, NULL, ?, ?, ?, ?)",
                    (chat_id, parent_id, topic_id,
                     "Семён" if quoted_is_bot else quoted_author.get("first_name", "Участник")[:80],
                     quoted_body, int(quoted_is_bot), int(quoted_is_bot)),
                )
                parent = self.get(chat_id, parent_id)
            chain_active = direct or bool(parent and parent["in_bot_chain"])
            sender = message.get("from") or {}
            self.db.execute(
                "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                (chat_id, message_id, topic_id, parent_id,
                 sender.get("first_name", "Участник")[:80],
                 (message.get("text") or message.get("caption") or "")[:2000],
                 int(chain_active)),
            )
        return chain_active

    def record_bot(self, sent: dict[str, Any], chat_id: int, topic_id: int,
                   parent_id: int, body: str) -> None:
        message_id = sent.get("message_id") if isinstance(sent, dict) else None
        if message_id is None:
            return
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, 'Семён', ?, 1, 1)",
                (chat_id, message_id, topic_id, parent_id, body[:2000]),
            )

    def context(self, chat_id: int, topic_id: int, parent_id: int | None,
                current_id: int, max_chars: int = 60000) -> list[dict[str, str]]:
        if parent_id is None:
            rows = self.db.execute(
                """SELECT name, body FROM messages
                   WHERE chat_id=? AND topic_id=? AND message_id<?
                   ORDER BY message_id DESC LIMIT 12""",
                (chat_id, topic_id, current_id),
            ).fetchall()
        else:
            rows = []
            seen: set[int] = set()
            cursor = parent_id
            while cursor is not None and cursor not in seen:
                seen.add(cursor)
                row = self.get(chat_id, cursor)
                if row is None:
                    break
                rows.append(row)
                cursor = row["parent_id"]
        result: list[dict[str, str]] = []
        size = 0
        for row in rows:
            body = row["body"]
            if size + len(body) > max_chars and result:
                break
            result.append({"name": row["name"], "text": body})
            size += len(body)
        result.reverse()
        if len(result) < len(rows):
            result.insert(0, {"name": "Контекст", "text": "Начало длинной цепочки сохранено в базе, но не вошло в текущий запрос."})
        return result

    def add_style_request(self, chat_id: int, text: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO style_requests(chat_id, instruction) VALUES (?, ?)",
                (chat_id, text[:500]),
            )

    def style_requests(self, chat_id: int) -> list[str]:
        rows = self.db.execute(
            """SELECT instruction FROM style_requests WHERE chat_id=?
               ORDER BY request_id DESC LIMIT 5""",
            (chat_id,),
        ).fetchall()
        return [row[0] for row in reversed(rows)]

    def queue_reply(self, message: dict[str, Any], kind: str, due_at: float) -> None:
        chat_id = message["chat"]["id"]
        with self.db:
            self.db.execute(
                """INSERT INTO pending_replies VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id, message_id) DO UPDATE SET due_at=excluded.due_at""",
                (chat_id, message["message_id"], due_at, kind,
                 json.dumps(message, ensure_ascii=False)),
            )

    def next_reply_due(self) -> float | None:
        row = self.db.execute("SELECT MIN(due_at) FROM pending_replies").fetchone()
        return row[0]

    def due_reply(self, now: float) -> tuple[dict[str, Any], str] | None:
        row = self.db.execute(
            """SELECT message_json, kind FROM pending_replies WHERE due_at<=?
               ORDER BY due_at, chat_id, message_id LIMIT 1""",
            (now,),
        ).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def forget_reply(self, chat_id: int, message_id: int) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM pending_replies WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            )

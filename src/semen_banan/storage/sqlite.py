from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

from semen_banan.conversation.models import RecentMessage, StoredMessage, TelegramMessage


class SqliteConversationStore:
    """SQLite-хранилище истории, характера и отложенных заданий."""

    def __init__(self, path: Path) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param path: Путь к файлу настроек или хранилища.
        :return: Не возвращает значение.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row

        with self.connection:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS messages (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL, parent_id INTEGER,
                name TEXT NOT NULL, body TEXT NOT NULL,
                is_bot INTEGER NOT NULL, in_bot_chain INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )""")
            self.connection.execute("""CREATE INDEX IF NOT EXISTS messages_recent
                ON messages(chat_id, topic_id, message_id)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS style_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL, instruction TEXT NOT NULL
            )""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS pending_replies (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                due_at REAL NOT NULL, kind TEXT NOT NULL, message_json TEXT NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )""")

    def __enter__(self) -> SqliteConversationStore:
        """Открывает область использования хранилища.

        :return: Текущее хранилище сообщений.
        """
        return self

    def __exit__(self, *exc: object) -> None:
        """Закрывает соединение после выхода из области использования.

        :param exc: Сведения об исключении при выходе из контекстного менеджера.
        :return: Не возвращает значение.
        """
        self.close()

    def close(self) -> None:
        """Закрывает соединение с базой данных.

        :return: Не возвращает значение.
        """
        self.connection.close()

    def get(self, chat_id: int, message_id: int | None) -> StoredMessage | None:
        """Находит сохранённое сообщение по группе и идентификатору.

        :param chat_id: Идентификатор Telegram-группы.
        :param message_id: Идентификатор сообщения Telegram.
        :return: Запись сообщения либо None, если её нет.
        """
        if message_id is None:
            return None

        stored_record = self.connection.execute(
            "SELECT * FROM messages WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        ).fetchone()

        return cast(StoredMessage, dict(stored_record)) if stored_record is not None else None

    def record_incoming(self, message: TelegramMessage, bot_id: int, direct: bool) -> bool:
        """Сохраняет сообщение и его принадлежность цепочке бота.

        :param message: Исходное сообщение Telegram.
        :param bot_id: Идентификатор бота в Telegram.
        :param direct: Признак начала или продолжения цепочки обращения к боту.
        :return: Признак включения сообщения в цепочку Семёна.
        """
        chat_id = message["chat"]["id"]
        message_id = message["message_id"]
        topic_id = message.get("message_thread_id") or 0
        quoted_message = message.get("reply_to_message") or {}
        parent_id = quoted_message.get("message_id")

        with self.connection:
            parent_record = self.get(chat_id, parent_id)

            if parent_record is None and parent_id is not None:
                quoted_sender = quoted_message.get("from") or {}
                quoted_is_bot = quoted_sender.get("id") == bot_id
                quoted_body = (quoted_message.get("text") or quoted_message.get("caption") or "")[
                    :2000
                ]
                self.connection.execute(
                    "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, NULL, ?, ?, ?, ?)",
                    (
                        chat_id,
                        parent_id,
                        topic_id,
                        "Семён"
                        if quoted_is_bot
                        else quoted_sender.get("first_name", "Участник")[:80],
                        quoted_body,
                        int(quoted_is_bot),
                        int(quoted_is_bot),
                    ),
                )
                parent_record = self.get(chat_id, parent_id)

            chain_active = direct or bool(parent_record and parent_record["in_bot_chain"])
            sender_data = message.get("from") or {}
            self.connection.execute(
                """INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(chat_id, message_id) DO UPDATE
                   SET in_bot_chain=MAX(messages.in_bot_chain, excluded.in_bot_chain)""",
                (
                    chat_id,
                    message_id,
                    topic_id,
                    parent_id,
                    sender_data.get("first_name", "Участник")[:80],
                    (message.get("text") or message.get("caption") or "")[:2000],
                    int(chain_active),
                ),
            )

        return chain_active

    def record_bot(
        self, sent: dict[str, Any], chat_id: int, topic_id: int, parent_id: int, body: str
    ) -> None:
        """Сохраняет отправленный ответ и его связь с исходным сообщением.

        :param sent: Данные отправленного ответа Telegram.
        :param chat_id: Идентификатор Telegram-группы.
        :param topic_id: Идентификатор темы группы, 0 для общего чата.
        :param parent_id: Идентификатор родительского сообщения либо None.
        :param body: Текст ответа для сохранения в истории.
        :return: Не возвращает значение.
        """
        message_id = sent.get("message_id") if isinstance(sent, dict) else None

        if message_id is None:
            return

        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, 'Семён', ?, 1, 1)",
                (chat_id, message_id, topic_id, parent_id, body[:2000]),
            )

    def add_style_request(self, chat_id: int, text: str) -> None:
        """Сохраняет пожелание к характеру бота для группы.

        :param chat_id: Идентификатор Telegram-группы.
        :param text: Текст сообщения или речевой фразы.
        :return: Не возвращает значение.
        """
        with self.connection:
            self.connection.execute(
                "INSERT INTO style_requests(chat_id, instruction) VALUES (?, ?)",
                (chat_id, text[:500]),
            )

    def style_requests(self, chat_id: int) -> list[str]:
        """Читает последние пожелания к характеру для группы.

        :param chat_id: Идентификатор Telegram-группы.
        :return: До пяти инструкций в порядке поступления.
        """
        stored_records = self.connection.execute(
            """SELECT instruction FROM style_requests WHERE chat_id=?
               ORDER BY request_id DESC LIMIT 5""",
            (chat_id,),
        ).fetchall()

        return [stored_record[0] for stored_record in reversed(stored_records)]

    def queue_reply(self, message: TelegramMessage, kind: str, due_at: float) -> None:
        """Добавляет или обновляет отложенное задание вместе с параметрами.

        :param message: Исходное сообщение Telegram.
        :param kind: Тип композитора или отложенного задания.
        :param due_at: Временная метка следующей попытки обработки.
        :return: Не возвращает значение.
        """
        chat_id = message["chat"]["id"]

        with self.connection:
            self.connection.execute(
                """INSERT INTO pending_replies VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id, message_id) DO UPDATE SET due_at=excluded.due_at,
                   kind=excluded.kind, message_json=excluded.message_json""",
                (
                    chat_id,
                    message["message_id"],
                    due_at,
                    kind,
                    json.dumps(message, ensure_ascii=False),
                ),
            )

    def next_reply_due(self) -> float | None:
        """Определяет ближайшее время обработки очереди.

        :return: Временная метка либо None, если очередь пуста.
        """
        stored_record = self.connection.execute(
            "SELECT MIN(due_at) FROM pending_replies"
        ).fetchone()

        return stored_record[0]

    def due_reply(self, now: float) -> tuple[TelegramMessage, str] | None:
        """Выбирает первое задание, срок обработки которого наступил.

        :param now: Текущая временная метка.
        :return: Сообщение и вид задания либо None.
        """
        stored_record = self.connection.execute(
            """SELECT message_json, kind FROM pending_replies WHERE due_at<=?
               ORDER BY due_at, chat_id, message_id LIMIT 1""",
            (now,),
        ).fetchone()

        return (json.loads(stored_record[0]), stored_record[1]) if stored_record else None

    def forget_reply(self, chat_id: int, message_id: int) -> None:
        """Удаляет обработанное или устаревшее задание.

        :param chat_id: Идентификатор Telegram-группы.
        :param message_id: Идентификатор сообщения Telegram.
        :return: Не возвращает значение.
        """
        with self.connection:
            self.connection.execute(
                "DELETE FROM pending_replies WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            )

    def recent_messages(self, chat_id: int, topic_id: int, current_id: int) -> list[RecentMessage]:
        """Читает последние сообщения одной темы до текущего сообщения.

        :param chat_id: Идентификатор Telegram-группы.
        :param topic_id: Идентификатор темы группы, 0 для общего чата.
        :param current_id: Идентификатор текущего сообщения.
        :return: До двенадцати записей от новых к старым.
        """
        stored_records = self.connection.execute(
            "SELECT name, body FROM messages WHERE chat_id=? AND topic_id=? AND message_id<? "
            "ORDER BY message_id DESC LIMIT 12",
            (chat_id, topic_id, current_id),
        ).fetchall()

        return [cast(RecentMessage, dict(stored_record)) for stored_record in stored_records]

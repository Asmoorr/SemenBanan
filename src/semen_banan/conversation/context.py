from __future__ import annotations

from semen_banan.conversation.ports import ConversationStore


class ContextBuilder:
    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    def build(
        self,
        chat_id: int,
        topic_id: int,
        parent_id: int | None,
        current_id: int,
        max_chars: int = 60000,
    ) -> list[dict[str, str]]:
        if parent_id is None:
            rows = self.store.recent_messages(chat_id, topic_id, current_id)
        else:
            rows = []
            seen: set[int] = set()
            cursor = parent_id
            while cursor is not None and cursor not in seen:
                seen.add(cursor)
                row = self.store.get(chat_id, cursor)
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
            result.insert(
                0,
                {
                    "name": "Контекст",
                    "text": "Начало длинной цепочки сохранено в базе, но не вошло в текущий запрос.",
                },
            )
        return result

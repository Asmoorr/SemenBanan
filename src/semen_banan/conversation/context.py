from __future__ import annotations

from semen_banan.conversation.models import ConversationContext, RecentMessage, StoredMessage
from semen_banan.conversation.ports import ConversationStore
from semen_banan.generation.prompts import load_prompts


class ContextBuilder:
    """Сборка ограниченного контекста темы или ветки ответов."""

    def __init__(self, store: ConversationStore) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param store: Хранилище истории диалога.
        :return: Не возвращает значение.
        """
        self.store = store

    def build(
        self,
        chat_id: int,
        topic_id: int,
        parent_id: int | None,
        current_id: int,
        max_chars: int = 60000,
    ) -> ConversationContext:
        """Собирает контекст темы или ветки ответов в пределах лимита.

        :param chat_id: Идентификатор Telegram-группы.
        :param topic_id: Идентификатор темы группы, 0 для общего чата.
        :param parent_id: Идентификатор родительского сообщения либо None.
        :param current_id: Идентификатор текущего сообщения.
        :param max_chars: Максимальная длина контекста в символах.
        :return: Сообщения контекста в хронологическом порядке.
        """
        if parent_id is None:
            message_records: list[RecentMessage | StoredMessage] = list(
                self.store.recent_messages(chat_id, topic_id, current_id)
            )
        else:
            message_records = []
            visited_message_ids: set[int] = set()
            ancestor_message_id: int | None = parent_id

            while (
                ancestor_message_id is not None and ancestor_message_id not in visited_message_ids
            ):
                visited_message_ids.add(ancestor_message_id)
                ancestor_record = self.store.get(chat_id, ancestor_message_id)

                if ancestor_record is None:
                    break

                message_records.append(ancestor_record)
                ancestor_message_id = ancestor_record["parent_id"]

        conversation_context: ConversationContext = []
        context_length = 0

        for message_record in message_records:
            message_text = message_record["body"]

            if context_length + len(message_text) > max_chars and conversation_context:
                break

            conversation_context.append({"name": message_record["name"], "text": message_text})
            context_length += len(message_text)

        conversation_context.reverse()

        if len(conversation_context) < len(message_records):
            conversation_context.insert(
                0,
                {
                    "name": "Контекст",
                    "text": load_prompts().context_notice,
                },
            )

        return conversation_context

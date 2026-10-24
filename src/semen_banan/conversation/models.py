from __future__ import annotations

from typing import Any, NotRequired, TypedDict

type TelegramMessage = dict[str, Any]


class BotIdentity(TypedDict):
    """Идентификатор, username и необязательное имя Telegram-бота."""

    id: int
    username: str
    name: NotRequired[str]


class ContextMessage(TypedDict):
    """Текст реплики, имя автора и необязательная цитата бота."""

    name: str
    text: str
    in_reply_to_semyon: NotRequired[str]


type ConversationContext = list[ContextMessage]


class RoutingMetadata(TypedDict, total=False):
    """Признаки обращения и цепочки для классификации сообщения."""

    bot: BotIdentity
    in_chain: bool
    reply_to_bot: bool
    mentions_bot: bool
    force_addressed: bool


class Correction(TypedDict):
    """Причина ошибки и предыдущий ответ модели для исправления."""

    error: str
    previous_json: str


class RecentMessage(TypedDict):
    """Имя автора и текст реплики, прочитанные из истории."""

    name: str
    body: str


class StoredMessage(RecentMessage):
    """Сохранённая реплика с идентификаторами, родителем и признаком цепочки."""

    chat_id: int
    message_id: int
    topic_id: int
    parent_id: int | None
    is_bot: int
    in_bot_chain: int

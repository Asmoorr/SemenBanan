from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass

from semen_banan.config import Settings
from semen_banan.conversation.models import (
    BotIdentity,
    ContextMessage,
    ConversationContext,
    RoutingMetadata,
    TelegramMessage,
)
from semen_banan.conversation.ports import Gateway, Telegram
from semen_banan.errors import BotError

LOGGER = logging.getLogger(__name__)
# Обычные реакции Telegram Bot API; ограничения конкретной группы уточняются через getChat.
STANDARD_REACTIONS = tuple(
    "❤|👍|👎|🔥|🥰|👏|😁|🤔|🤯|😱|🤬|😢|🎉|🤩|🤮|💩|🙏|👌|🕊|🤡|🥱|🥴|😍|🐳|❤‍🔥|🌚|🌭|💯|🤣|⚡|🍌|🏆|💔|🤨|😐|🍓|🍾|💋|🖕|😈|😴|😭|🤓|👻|👨‍💻|👀|🎃|🙈|😇|😨|🤝|✍|🤗|🫡|🎅|🎄|☃|💅|🤪|🗿|🆒|💘|🙉|🦄|😘|💊|🙊|😎|👾|🤷‍♂|🤷|🤷‍♀|😡".split(
        "|"
    )
)
_CONTENT_TYPES = (
    "text",
    "photo",
    "video",
    "animation",
    "voice",
    "audio",
    "document",
    "sticker",
    "video_note",
    "dice",
    "poll",
    "contact",
    "location",
    "venue",
    "live_photo",
    "paid_media",
)


@dataclass(frozen=True, slots=True)
class ReactionSelection:
    """Смысловое решение модели об обращении и подходящей реакции."""

    addressed_to_bot: bool
    emoji: str
    explicit_request: bool

    @classmethod
    def parse(cls, content: str, available: list[str]) -> ReactionSelection:
        """Проверяет JSON и принадлежность эмодзи разрешённому набору.

        :param content: Ответ модели с признаком обращения и эмодзи.
        :param available: Обычные реакции, разрешённые в группе.
        :return: Проверенное смысловое решение.
        """
        try:
            data = json.loads(content)
            if not isinstance(data, dict) or set(data) != {
                "addressed_to_bot",
                "emoji",
                "explicit_request",
            }:
                raise ValueError
            if (
                type(data["addressed_to_bot"]) is not bool
                or type(data["explicit_request"]) is not bool
                or not isinstance(data["emoji"], str)
            ):
                raise ValueError
            normalized = {emoji.replace("\ufe0f", ""): emoji for emoji in available}
            emoji = normalized[data["emoji"].replace("\ufe0f", "")]
            return cls(data["addressed_to_bot"], emoji, data["explicit_request"])
        except (ValueError, TypeError, KeyError) as error:
            raise BotError("Модель вернула недопустимую реакцию.") from error


class ReactionService:
    """Независимые реакции на сообщения с вероятностью и смысловым выбором LLM."""

    def __init__(
        self, settings: Settings, telegram: Telegram, gateway: Gateway, bot_identity: BotIdentity
    ) -> None:
        """Сохраняет клиентов, вероятности и личность бота.

        :param settings: Настройки доступа и вероятностей.
        :param telegram: Клиент Telegram.
        :param gateway: Модель, выбирающая реакцию по контексту.
        :param bot_identity: Идентификатор и имя Семёна.
        :return: Не возвращает значение.
        """
        self.settings = settings
        self.telegram = telegram
        self.gateway = gateway
        self.bot_identity = bot_identity
        self.allowed_cache: dict[int, tuple[float, list[str]]] = {}
        self.seen: dict[tuple[int, int], None] = {}

    def eligible(self, message: TelegramMessage) -> bool:
        """Допускает сообщения других авторов в разрешённых группах.

        :param message: Сообщение Telegram, в том числе медиа или сообщение другого бота.
        :return: Признак допустимости реакции без проверки шанса.
        """
        chat = message.get("chat", {})
        return bool(
            chat.get("id") in self.settings.chats
            and chat.get("type") in {"group", "supergroup"}
            and (message.get("from") or {}).get("id") != self.bot_identity["id"]
            and message.get("message_id")
            and 0 <= time.time() - message.get("date", 0) <= 120
            and any(key in message for key in _CONTENT_TYPES)
        )

    async def available_reactions(self, chat_id: int) -> list[str]:
        """Читает разрешённые реакции группы с кешированием на пять минут.

        :param chat_id: Идентификатор группы Telegram.
        :return: Допустимые обычные эмодзи без платных и пользовательских реакций.
        """
        cached = self.allowed_cache.get(chat_id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        chat = await self.telegram.call("getChat", chat_id=chat_id)
        if not isinstance(chat, dict):
            raise BotError("Telegram вернул неверные настройки реакций группы.")
        configured = chat.get("available_reactions")
        if configured is None:
            allowed = list(STANDARD_REACTIONS)
        elif isinstance(configured, list):
            allowed = list(
                dict.fromkeys(
                    item["emoji"]
                    for item in configured
                    if isinstance(item, dict)
                    and item.get("type") == "emoji"
                    and item.get("emoji") in STANDARD_REACTIONS
                )
            )
        else:
            raise BotError("Telegram вернул неверный список реакций.")
        self.allowed_cache[chat_id] = (time.monotonic() + 300, allowed)
        return allowed

    async def maybe_react(
        self,
        message: TelegramMessage,
        context: ConversationContext,
        style_requests: list[str] | None = None,
    ) -> None:
        """Независимо выбирает шанс и просит модель подобрать реакцию по смыслу.

        :param message: Новое сообщение другого автора.
        :param context: Контекст соответствующей темы или цепочки.
        :param style_requests: Сохранённые пожелания к манере общения.
        :return: Не возвращает значение.
        """
        if not self.eligible(message):
            return
        key = (message["chat"]["id"], message["message_id"])
        if key in self.seen:
            return
        self.seen[key] = None
        if len(self.seen) > 4096:
            del self.seen[next(iter(self.seen))]

        chance = random.random()
        try:
            allowed = await self.available_reactions(key[0])
            if not allowed:
                return
            sender = message.get("from") or message.get("sender_chat") or {}
            current: ContextMessage = {
                "name": sender.get("first_name") or sender.get("title") or "Участник",
                "text": (message.get("text") or message.get("caption") or "")[:2000],
            }
            metadata: RoutingMetadata = {
                "bot": self.bot_identity,
                "reply_to_bot": (message.get("reply_to_message") or {}).get("from", {}).get("id")
                == self.bot_identity["id"],
                "mentions_bot": any(
                    entity.get("type") == "text_mention"
                    and (entity.get("user") or {}).get("id") == self.bot_identity["id"]
                    for entity in (message.get("entities") or message.get("caption_entities") or [])
                ),
                "content_type": next((key for key in _CONTENT_TYPES if key in message), "unknown"),
                "sticker_emoji": (message.get("sticker") or {}).get("emoji", ""),
            }
            content = await asyncio.wait_for(
                self.gateway.select_reaction(context, current, metadata, allowed, style_requests),
                timeout=min(15, self.settings.timeout),
            )
            selection = ReactionSelection.parse(content, allowed)
            addressed = selection.addressed_to_bot or bool(
                metadata.get("reply_to_bot") or metadata.get("mentions_bot")
            )
            probability = (
                self.settings.addressed_reaction_probability
                if addressed
                else self.settings.reaction_probability
            )
            if not selection.explicit_request and chance >= probability:
                return
            await self.telegram.call(
                "setMessageReaction",
                chat_id=key[0],
                message_id=key[1],
                reaction=[{"type": "emoji", "emoji": selection.emoji}],
                is_big=False,
            )
            LOGGER.info(
                "Реакция отправлена: chat_id=%s, message_id=%s, emoji=%s, addressed=%s",
                key[0],
                key[1],
                selection.emoji,
                addressed,
            )
        except (BotError, TimeoutError) as error:
            self.allowed_cache.pop(key[0], None)
            LOGGER.warning(
                "Реакция пропущена: chat_id=%s, message_id=%s, причина=%s", key[0], key[1], error
            )

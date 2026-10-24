from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

from semen_banan.audio.jobs import AudioError
from semen_banan.config import Settings
from semen_banan.conversation.context import ContextBuilder
from semen_banan.conversation.models import (
    BotIdentity,
    ContextMessage,
    RoutingMetadata,
    TelegramMessage,
)
from semen_banan.conversation.ports import ConversationStore, Cooldowns, Gateway, Telegram
from semen_banan.conversation.reactions import ReactionService
from semen_banan.conversation.routing import MessageRouter, ReplyMode, ReplyTrigger, RouteDecision
from semen_banan.conversation.style import normalize_reply_style
from semen_banan.errors import BotError
from semen_banan.generation.service import MusicGenerator
from semen_banan.group import ParticipantPhotosError
from semen_banan.integrations.openclaw_images import ImageGenerationError, OpenClawImageGenerator

LOGGER = logging.getLogger(__name__)


class ConversationService:
    """Обработка диалога с учётом доступа, очереди и интервалов."""

    def __init__(
        self,
        settings: Settings,
        telegram: Telegram,
        gateway: Gateway,
        bot_identity: BotIdentity,
        memory: ConversationStore,
        cooldown: Cooldowns,
        music: MusicGenerator,
        images: OpenClawImageGenerator | None = None,
        reactions: ReactionService | None = None,
    ) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param settings: Проверенные настройки приложения.
        :param telegram: Клиент Telegram для получения и отправки сообщений.
        :param gateway: Клиент OpenClaw для работы с языковой моделью.
        :param bot_identity: Идентификатор и имя Telegram-бота.
        :param memory: Хранилище истории, характера и очереди.
        :param cooldown: Хранилище интервалов между ответами.
        :param music: Сервис создания музыкального ответа.
        :param images: Генератор картинок через OpenClaw.
        :param reactions: Независимый сервис смысловых реакций.
        :return: Не возвращает значение.
        """
        self.settings = settings
        self.telegram = telegram
        self.gateway = gateway
        self.bot_identity = bot_identity
        self.memory = memory
        self.cooldown = cooldown
        self.music = music
        self.images = images
        self.reactions = reactions
        self.context_builder = ContextBuilder(memory)
        self.router = MessageRouter(gateway)
        self.last = cooldown.load()

    def save(self) -> None:
        """Сохраняет интервалы между ответами в рабочем файле.

        :return: Не возвращает значение.
        """
        self.cooldown.save(self.last)

    def eligible(self, message: TelegramMessage, max_age: float = 120) -> bool:
        """Проверяет локальные ограничения обработки сообщения.

        :param message: Исходное сообщение Telegram.
        :param max_age: Допустимый возраст сообщения в секундах.
        :return: Признак допустимости обработки сообщения.
        """
        chat_data = message.get("chat", {})
        sender_data = message.get("from", {})

        return bool(
            chat_data.get("id") in self.settings.chats
            and chat_data.get("type") in {"group", "supergroup"}
            and not sender_data.get("is_bot")
            and not message.get("sender_chat")
            and (message.get("text") or message.get("caption"))
            and time.time() - message.get("date", 0) <= max_age
        )

    def current_message(self, message: TelegramMessage) -> ContextMessage:
        """Готовит текст и цитату текущего сообщения для модели.

        :param message: Исходное сообщение Telegram.
        :return: Сообщение в формате контекста LLM.
        """
        sender_data = message.get("from") or {}
        current_message: ContextMessage = {
            "name": sender_data.get("first_name", "Участник")[:80],
            "text": (message.get("text") or message.get("caption") or "")[:2000],
        }
        replied_message = message.get("reply_to_message") or {}

        if replied_message.get("from", {}).get("id") == self.bot_identity["id"]:
            quoted = replied_message.get("text") or replied_message.get("caption")

            if quoted:
                current_message["in_reply_to_semyon"] = quoted[:1200]

        return current_message

    async def handle(self, message: TelegramMessage) -> None:
        """Проверяет входящее сообщение и запускает маршрутизацию.

        :param message: Исходное сообщение Telegram.
        :return: Не возвращает значение.
        """
        reply_eligible = self.eligible(message)
        if self.reactions is not None and self.reactions.eligible(message):
            context = self.context_builder.build(
                message["chat"]["id"],
                message.get("message_thread_id") or 0,
                (message.get("reply_to_message") or {}).get("message_id"),
                message["message_id"],
                max_chars=4000,
            )
            await self.reactions.maybe_react(
                message, context, self.memory.style_requests(message["chat"]["id"])
            )
        if not reply_eligible:
            return

        await self.classify_and_respond(message)

    async def classify_and_respond(self, message: TelegramMessage) -> None:
        """Определяет намерение, сохраняет параметры и инициирует ответ.

        :param message: Исходное сообщение Telegram.
        :return: Не возвращает значение.
        """
        chat_id = message["chat"]["id"]
        topic_id = message.get("message_thread_id") or 0
        replied_message = message.get("reply_to_message") or {}
        in_chain = self.memory.record_incoming(message, self.bot_identity["id"], False)
        conversation_context = self.context_builder.build(
            chat_id,
            topic_id,
            replied_message.get("message_id"),
            message["message_id"],
            max_chars=8000,
        )
        entities = message.get("entities") or message.get("caption_entities") or []
        metadata: RoutingMetadata = {
            "bot": {
                "id": self.bot_identity["id"],
                "username": self.bot_identity["username"],
                "name": "Семён",
            },
            "in_chain": in_chain,
            "reply_to_bot": replied_message.get("from", {}).get("id") == self.bot_identity["id"],
            "mentions_bot": any(
                entity.get("type") == "text_mention"
                and entity.get("user", {}).get("id") == self.bot_identity["id"]
                for entity in entities
            ),
        }

        try:
            decision = await self.router.route(
                conversation_context,
                self.current_message(message),
                metadata,
                self.memory.style_requests(chat_id),
            )
        except BotError as exc:
            LOGGER.warning("Не удалось определить режим: %s", exc)
            self.memory.queue_reply(message, "classify", time.time() + 30)

            return

        LOGGER.info(
            "Режим определён: chat_id=%s, message_id=%s, mode=%s, trigger=%s",
            chat_id,
            message["message_id"],
            decision.mode,
            decision.trigger,
        )

        if decision.mode == ReplyMode.IGNORE or decision.trigger == ReplyTrigger.BANANA:
            if (
                time.time() - self.last.get(str(chat_id), 0) < self.settings.cooldown
                or random.random() >= self.settings.spontaneous_probability
            ):
                self.memory.forget_reply(chat_id, message["message_id"])
                return
            mode = (
                ReplyMode.VOICE
                if random.random() < self.settings.spontaneous_voice_probability
                else ReplyMode.TEXT
            )
            decision = RouteDecision(mode, ReplyTrigger.SPONTANEOUS)
        else:
            self.memory.record_incoming(message, self.bot_identity["id"], True)

        if decision.style_request is not None:
            self.memory.add_style_request(chat_id, decision.style_request)

        routed_message = {**message, "_routing": decision.to_payload()}
        reply_kind = (
            decision.trigger.value
            if decision.trigger in {ReplyTrigger.BANANA, ReplyTrigger.SPONTANEOUS}
            else decision.mode.value
        )
        await self.respond(routed_message, reply_kind)

    async def respond(self, message: TelegramMessage, reply_kind: str) -> None:
        """Выполняет сохранённое решение или откладывает ответ.

        :param message: Исходное сообщение Telegram.
        :param reply_kind: Тип отложенного ответа.
        :return: Не возвращает значение.
        """
        if "_routing" not in message:
            # Задания прежней версии классифицируются при ближайшей попытке.
            await self.classify_and_respond(message)

            return

        try:
            decision = RouteDecision.parse(json.dumps(message["_routing"]))
        except ValueError:
            retry_message = {
                chat_key: value for chat_key, value in message.items() if chat_key != "_routing"
            }
            self.memory.queue_reply(retry_message, "classify", time.time() + 30)

            return

        if decision.mode == ReplyMode.IGNORE:
            self.memory.forget_reply(message["chat"]["id"], message["message_id"])

            return

        reply_kind = (
            decision.trigger.value
            if decision.trigger in {ReplyTrigger.BANANA, ReplyTrigger.SPONTANEOUS}
            else decision.mode.value
        )
        chat_id = message["chat"]["id"]
        topic_id = message.get("message_thread_id") or 0
        chat_key = str(chat_id)
        now = time.time()

        if now - self.last.get(chat_key, 0) < self.settings.cooldown:
            if reply_kind not in {"banana", "spontaneous"}:
                self.memory.queue_reply(
                    message, reply_kind, self.last[chat_key] + self.settings.cooldown
                )
                LOGGER.info(
                    "Ответ поставлен в очередь: chat_id=%s, message_id=%s, trigger=%s",
                    chat_id,
                    message["message_id"],
                    reply_kind,
                )
            else:
                self.memory.forget_reply(chat_id, message["message_id"])
                LOGGER.info("Случайный ответ пропущен: действует интервал между репликами")

            return

        # Резервируем интервал до сетевого запроса, включая неудачные попытки.
        self.last[chat_key] = now
        self.save()

        try:
            current_message = self.current_message(message)
            if decision.trigger == ReplyTrigger.SPONTANEOUS:
                current_message["spontaneous_reply"] = True
            if decision.load_participant_photos:
                current_message["load_participant_photos"] = True
            parent_message_id = (message.get("reply_to_message") or {}).get("message_id")
            conversation_context = self.context_builder.build(
                chat_id, topic_id, parent_message_id, message["message_id"]
            )

            if decision.mode == ReplyMode.MUSIC:
                assert decision.music is not None
                reply = await self.music.generate(
                    conversation_context,
                    current_message,
                    self.memory.style_requests(chat_id),
                    options=decision.music,
                )
                sent = await self.telegram.send_voice(
                    chat_id,
                    message["message_id"],
                    reply.audio.voice,
                    reply.audio.duration,
                    topic_id,
                )
                answer = reply.description
            elif decision.mode == ReplyMode.IMAGE:
                assert decision.image is not None
                if self.images is None:
                    raise ImageGenerationError("Генерация картинок не настроена.")
                if decision.load_participant_photos:
                    image_reply = await self.images.generate(
                        decision.image,
                        f"{chat_id}:{message['message_id']}",
                        load_participant_photos=True,
                    )
                else:
                    image_reply = await self.images.generate(
                        decision.image, f"{chat_id}:{message['message_id']}"
                    )
                sent = await self.telegram.send_photo(
                    chat_id,
                    message["message_id"],
                    image_reply.path.read_bytes(),
                    normalize_reply_style(image_reply.caption),
                    topic_id,
                )
                answer = image_reply.description
            else:
                answer = normalize_reply_style(
                    await self.gateway.reply(
                        conversation_context, current_message, self.memory.style_requests(chat_id)
                    )
                )
                if decision.mode == ReplyMode.VOICE:
                    try:
                        audio = await self.music.audio.speak(
                            answer, timeout=self.settings.audio_timeout
                        )
                    except AudioError as error:
                        raise BotError(str(error)) from error
                    sent = await self.telegram.send_voice(
                        chat_id, message["message_id"], audio.voice, audio.duration, topic_id
                    )
                else:
                    sent = await self.send_text(chat_id, message["message_id"], answer, topic_id)

            self.memory.record_bot(sent, chat_id, topic_id, message["message_id"], answer)
            self.memory.forget_reply(chat_id, message["message_id"])
            LOGGER.info("Ответ отправлен: chat_id=%s, trigger=%s", chat_id, reply_kind)
        except (ImageGenerationError, ParticipantPhotosError) as exc:
            LOGGER.warning("%s", exc)
            try:
                error_message = normalize_reply_style(str(exc))
                sent = await self.send_text(chat_id, message["message_id"], error_message, topic_id)
                self.memory.record_bot(
                    sent, chat_id, topic_id, message["message_id"], error_message
                )
                self.memory.forget_reply(chat_id, message["message_id"])
            except BotError:
                self.memory.queue_reply(message, reply_kind, time.time() + 30)
        except BotError as exc:
            LOGGER.warning("%s", exc)

            if reply_kind not in {"banana", "spontaneous"}:
                self.memory.queue_reply(message, reply_kind, time.time() + 30)
            else:
                self.memory.forget_reply(chat_id, message["message_id"])
        finally:
            self.last[chat_key] = time.time()
            self.save()

    async def send_text(
        self, chat_id: int, message_id: int, answer: str, topic_id: int
    ) -> dict[str, Any]:
        """Отправляет текст или понятную ошибку в исходную тему диалога.

        :param chat_id: Идентификатор группы.
        :param message_id: Идентификатор исходного сообщения.
        :param answer: Готовая реплика бота.
        :param topic_id: Идентификатор темы, ноль для общего чата.
        :return: Данные отправленного сообщения.
        """
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": normalize_reply_style(answer),
            "reply_parameters": {"message_id": message_id, "allow_sending_without_reply": False},
            "link_preview_options": {"is_disabled": True},
        }
        if topic_id:
            payload["message_thread_id"] = topic_id
        return await self.telegram.call("sendMessage", **payload)

    async def process_pending(self) -> None:
        """Обрабатывает готовые задания и удаляет устаревшие.

        :return: Не возвращает значение.
        """
        for _ in range(20):
            pending_reply = self.memory.due_reply(time.time())

            if pending_reply is None:
                return

            message, reply_kind = pending_reply
            chat_id = message["chat"]["id"]
            message_id = message["message_id"]

            if not self.eligible(message, max_age=600):
                self.memory.forget_reply(chat_id, message_id)
                LOGGER.info(
                    "Устаревший отложенный ответ удалён: chat_id=%s, message_id=%s",
                    chat_id,
                    message_id,
                )
                continue

            await self.respond(message, reply_kind)

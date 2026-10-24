from __future__ import annotations

import logging
import random
import time
from typing import Any

from semen_banan.config import Settings
from semen_banan.conversation.context import ContextBuilder
from semen_banan.conversation.policies import STYLE_CHANGE, music_requested, trigger
from semen_banan.conversation.ports import ConversationStore, Cooldowns, Gateway, Telegram
from semen_banan.errors import BotError
from semen_banan.generation.service import MusicGenerator

LOG = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        settings: Settings,
        telegram: Telegram,
        gateway: Gateway,
        me: dict[str, Any],
        memory: ConversationStore,
        cooldown: Cooldowns,
        music: MusicGenerator,
    ) -> None:
        self.settings = settings
        self.telegram = telegram
        self.gateway = gateway
        self.me = me
        self.memory = memory
        self.cooldown = cooldown
        self.music = music
        self.context = ContextBuilder(memory)
        self.last = cooldown.load()

    def save(self) -> None:
        self.cooldown.save(self.last)

    async def handle(self, message: dict[str, Any]) -> None:
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        sender = message.get("from", {})
        LOG.info(
            "Получено: chat_id=%s, type=%s, text=%s, sender_bot=%s",
            chat_id,
            chat.get("type"),
            bool(message.get("text") or message.get("caption")),
            sender.get("is_bot"),
        )
        if chat_id not in self.settings.chats or chat.get("type") not in {"group", "supergroup"}:
            LOG.info("Пропуск: группа не разрешена")
            return
        if sender.get("is_bot") or message.get("sender_chat"):
            LOG.info("Пропуск: сообщение от бота или анонимного администратора")
            return
        text = message.get("text") or message.get("caption")
        if not text or time.time() - message.get("date", 0) > 120:
            LOG.info("Пропуск: нет текста или сообщение старше двух минут")
            return
        replied_to = message.get("reply_to_message") or {}
        parent_id = replied_to.get("message_id")
        base_kind = trigger(message, self.me["username"], self.me["id"])
        style_change = bool(STYLE_CHANGE.search(text))
        music_change = music_requested(text)
        in_chain = self.memory.record_incoming(
            message, self.me["id"], base_kind == "direct" or style_change
        )
        if style_change:
            self.memory.add_style_request(chat_id, text)
            LOG.info("Изменение характера сохранено: chat_id=%s", chat_id)
        kind = (
            "music"
            if music_change
            else "direct"
            if base_kind == "direct"
            else "chain"
            if parent_id is not None and in_chain
            else "style"
            if style_change
            else base_kind
        )
        if not kind:
            LOG.info("Пропуск: нет обращения, цепочки или банана")
            return
        if kind == "banana" and random.random() >= self.settings.probability:
            LOG.info("Пропуск: вероятность 25%%")
            return
        await self.respond(message, kind)

    async def respond(self, message: dict[str, Any], kind: str) -> None:
        chat_id = message["chat"]["id"]
        topic = message.get("message_thread_id") or 0
        key = str(chat_id)
        now = time.time()
        if now - self.last.get(key, 0) < self.settings.cooldown:
            if kind != "banana":
                self.memory.queue_reply(message, kind, self.last[key] + self.settings.cooldown)
                LOG.info(
                    "Ответ поставлен в очередь: chat_id=%s, message_id=%s, trigger=%s",
                    chat_id,
                    message["message_id"],
                    kind,
                )
            else:
                LOG.info("Пропуск: интервал 10 секунд, trigger=banana")
            return
        # Reserve before network I/O; failures stay silent and cannot cause a request storm.
        self.last[key] = now
        self.save()
        try:
            sender = message.get("from") or {}
            text = message.get("text") or message.get("caption") or ""
            current = {"name": sender.get("first_name", "Участник")[:80], "text": text[:2000]}
            replied_to = message.get("reply_to_message") or {}
            parent_id = replied_to.get("message_id")
            if replied_to.get("from", {}).get("id") == self.me["id"]:
                quoted = replied_to.get("text") or replied_to.get("caption")
                if quoted:
                    current["in_reply_to_semyon"] = quoted[:1200]
            context = self.context.build(chat_id, topic, parent_id, message["message_id"])
            if kind == "music":
                reply = await self.music.generate(
                    context, current, self.memory.style_requests(chat_id)
                )
                sent = await self.telegram.send_voice(
                    chat_id,
                    message["message_id"],
                    reply.audio.voice,
                    reply.audio.duration,
                    topic,
                )
                answer = reply.description
            else:
                answer = await self.gateway.reply(
                    context, current, self.memory.style_requests(chat_id)
                )
                payload: dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": answer,
                    "reply_parameters": {
                        "message_id": message["message_id"],
                        "allow_sending_without_reply": False,
                    },
                    "link_preview_options": {"is_disabled": True},
                }
                if topic:
                    payload["message_thread_id"] = topic
                sent = await self.telegram.call("sendMessage", **payload)
            self.memory.record_bot(sent, chat_id, topic, message["message_id"], answer)
            self.memory.forget_reply(chat_id, message["message_id"])
            LOG.info("Ответ отправлен: chat_id=%s, trigger=%s", chat_id, kind)
        except BotError as exc:
            LOG.warning("%s", exc)
            if kind != "banana":
                self.memory.queue_reply(message, kind, time.time() + 30)
        finally:
            self.last[key] = time.time()
            self.save()

    async def process_pending(self) -> None:
        for _ in range(20):
            pending = self.memory.due_reply(time.time())
            if pending is None:
                return
            message, kind = pending
            chat_id = message["chat"]["id"]
            message_id = message["message_id"]
            if chat_id not in self.settings.chats or time.time() - message.get("date", 0) > 600:
                self.memory.forget_reply(chat_id, message_id)
                LOG.info(
                    "Устаревший отложенный ответ удалён: chat_id=%s, message_id=%s",
                    chat_id,
                    message_id,
                )
                continue
            await self.respond(message, kind)

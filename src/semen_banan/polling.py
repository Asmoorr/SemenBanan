from __future__ import annotations

import asyncio
import logging
import math
import time

from semen_banan.conversation.models import BotIdentity
from semen_banan.conversation.ports import Telegram
from semen_banan.conversation.service import ConversationService
from semen_banan.errors import BotError

LOGGER = logging.getLogger(__name__)


async def poll(
    telegram: Telegram,
    conversation_service: ConversationService | None,
    bot_identity: BotIdentity,
    discover: bool = False,
) -> None:
    """Получает обновления Telegram и обслуживает очередь ответов.

    :param telegram: Клиент Telegram для получения и отправки сообщений.
    :param conversation_service: Сервис обработки диалога.
    :param bot_identity: Идентификатор и имя Telegram-бота.
    :param discover: Признак режима определения ID групп.
    :return: Не возвращает значение.
    """
    if not discover and conversation_service is None:
        raise ValueError("Для получения обновлений нужен сервис диалога.")

    # Пропускаем накопившиеся обновления, чтобы запуск не вызывал старых ответов.
    latest_updates = await telegram.call("getUpdates", offset=-1, timeout=0, allowed_updates=[])
    offset = latest_updates[-1]["update_id"] + 1 if latest_updates else 0

    print(
        "Режим поиска групп: напиши /id в группе, ID появится здесь."
        if discover
        else f"Семён @{bot_identity['username']} слушает группу. Остановка: Ctrl+C.",
        flush=True,
    )

    while True:
        if conversation_service is not None:
            await conversation_service.process_pending()

        next_reply_time = (
            conversation_service.memory.next_reply_due()
            if conversation_service is not None
            else None
        )
        poll_timeout = (
            25
            if next_reply_time is None
            else max(1, min(25, math.ceil(next_reply_time - time.time())))
        )

        try:
            updates = await telegram.call(
                "getUpdates", offset=offset, timeout=poll_timeout, allowed_updates=[]
            )
        except BotError as exc:
            if "409" in str(exc) or "401" in str(exc):
                raise

            LOGGER.warning("%s Повтор через 10 секунд.", exc)
            await asyncio.sleep(10)
            continue

        for update in updates:
            LOGGER.info(
                "Telegram update_id=%s, type=%s",
                update.get("update_id"),
                next((key for key in update if key != "update_id"), "unknown"),
            )
            offset = update["update_id"] + 1
            message = update.get("message", {})

            if discover:
                chat_data = message.get("chat", {})

                if chat_data.get("type") in {"group", "supergroup"}:
                    print(
                        f"ALLOWED_CHAT_IDS={chat_data['id']}  ({chat_data.get('title', '')})",
                        flush=True,
                    )
            elif conversation_service is not None:
                await conversation_service.handle(message)

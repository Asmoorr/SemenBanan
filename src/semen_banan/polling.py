from __future__ import annotations

import asyncio
import logging
import math
import time

from semen_banan.conversation.ports import Telegram
from semen_banan.conversation.service import ConversationService
from semen_banan.errors import BotError

LOG = logging.getLogger(__name__)


async def poll(
    telegram: Telegram, bot: ConversationService | None, me: dict, discover: bool = False
) -> None:
    if not discover and bot is None:
        raise ValueError("A conversation service is required for polling")
    # Discard offline backlog so starting the script never causes unsolicited replies.
    tail = await telegram.call("getUpdates", offset=-1, timeout=0, allowed_updates=[])
    offset = tail[-1]["update_id"] + 1 if tail else 0

    print(
        "Режим поиска групп: напиши /id в группе, ID появится здесь."
        if discover
        else f"Семён @{me['username']} слушает группу. Остановка: Ctrl+C.",
        flush=True,
    )
    while True:
        if bot is not None:
            await bot.process_pending()
        next_due = bot.memory.next_reply_due() if bot is not None else None
        poll_timeout = (
            25 if next_due is None else max(1, min(25, math.ceil(next_due - time.time())))
        )
        try:
            updates = await telegram.call(
                "getUpdates", offset=offset, timeout=poll_timeout, allowed_updates=[]
            )
        except BotError as exc:
            if "409" in str(exc) or "401" in str(exc):
                raise
            LOG.warning("%s Повтор через 10 секунд.", exc)
            await asyncio.sleep(10)
            continue
        for update in updates:
            LOG.info(
                "Telegram update_id=%s, type=%s",
                update.get("update_id"),
                next((key for key in update if key != "update_id"), "unknown"),
            )
            offset = update["update_id"] + 1
            message = update.get("message", {})
            if discover:
                chat = message.get("chat", {})
                if chat.get("type") in {"group", "supergroup"}:
                    print(f"ALLOWED_CHAT_IDS={chat['id']}  ({chat.get('title', '')})", flush=True)
            elif bot is not None:
                await bot.handle(message)

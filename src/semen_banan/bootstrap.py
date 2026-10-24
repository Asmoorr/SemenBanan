from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path

import httpx

from semen_banan.audio.jobs import AudioJobRunner
from semen_banan.config import AppPaths, Settings
from semen_banan.conversation.service import ConversationService
from semen_banan.errors import BotError
from semen_banan.generation.service import MusicGenerator
from semen_banan.integrations.openclaw import OpenClawClient
from semen_banan.integrations.telegram import TelegramClient
from semen_banan.polling import poll
from semen_banan.storage.cooldown import CooldownStore
from semen_banan.storage.sqlite import SqliteConversationStore


async def run(
    mode: str, output: Path | None = None, request: str = "Семён, сыграй весёлую мелодию про бананы"
) -> None:
    paths = AppPaths.load()
    settings = Settings.load(paths)
    async with AsyncExitStack() as stack:
        gateway_client = await stack.enter_async_context(
            httpx.AsyncClient(follow_redirects=False, trust_env=False),
        )
        gateway = OpenClawClient(gateway_client, settings)
        music = MusicGenerator(gateway, AudioJobRunner(paths), settings.audio_timeout)
        if mode == "check-gateway":
            print(
                "Gateway отвечает:",
                await gateway.reply(
                    [], {"name": "Проверка", "text": "Семён, скажи одним словом: банан"}
                ),
            )
            return
        if mode == "check-music":
            reply = await music.generate([], {"name": "Проверка", "text": request})
            destination = output or paths.runtime / "checks" / "music.ogg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(reply.audio.voice)
            print(f"Музыка готова: {destination.resolve()} ({reply.audio.duration} с)")
            return
        if not settings.token:
            raise BotError("Заполни TELEGRAM_BOT_TOKEN в .env.")
        client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
        telegram = TelegramClient(client, settings.token)
        me = await telegram.call("getMe")
        if mode == "check":
            print(f"Telegram OK: @{me['username']}; ID {me['id']}")
            print(
                "Gateway OK:",
                await gateway.reply(
                    [], {"name": "Проверка", "text": "Семён, скажи одним словом: банан"}
                ),
            )
            return
        if mode == "run" and not settings.chats:
            raise BotError("Сначала --discover-chats, затем заполни ALLOWED_CHAT_IDS.")
        if (await telegram.call("getWebhookInfo")).get("url"):
            raise BotError("У бота уже настроен webhook. Отключи прежнюю интеграцию; см. README.")
        bot = None
        if mode == "run":
            memory = stack.enter_context(SqliteConversationStore(paths.database))
            bot = ConversationService(
                settings, telegram, gateway, me, memory, CooldownStore(paths.state), music
            )
        await poll(telegram, bot, me, discover=mode == "discover-chats")

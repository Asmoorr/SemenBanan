from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path

import httpx

from semen_banan.audio.jobs import AudioJobRunner
from semen_banan.config import AppPaths, Settings
from semen_banan.conversation.models import ContextMessage
from semen_banan.conversation.reactions import ReactionService
from semen_banan.conversation.routing import MessageRouter, ReplyMode
from semen_banan.conversation.service import ConversationService
from semen_banan.errors import BotError
from semen_banan.generation.prompts import load_prompts
from semen_banan.generation.service import MusicGenerator
from semen_banan.group import GroupCatalog
from semen_banan.integrations.openclaw import OpenClawClient
from semen_banan.integrations.openclaw_images import OpenClawImageGenerator
from semen_banan.integrations.telegram import TelegramClient
from semen_banan.polling import poll
from semen_banan.storage.cooldown import CooldownStore
from semen_banan.storage.sqlite import SqliteConversationStore


async def run(mode: str, output: Path | None = None, request: str | None = None) -> None:
    """Создаёт зависимости и выполняет выбранный режим приложения.

    :param mode: Режим запуска или тип ответа.
    :param output: Путь для сохранения результата проверки.
    :param request: Исходная просьба или задание генерации.
    :return: Не возвращает значение.
    """
    prompts = load_prompts()
    paths = AppPaths.load()
    settings = Settings.load(paths)

    async with AsyncExitStack() as resource_stack:
        gateway_client = await resource_stack.enter_async_context(
            httpx.AsyncClient(follow_redirects=False, trust_env=False),
        )
        group = GroupCatalog.load(paths)
        gateway = OpenClawClient(gateway_client, settings, group=group)
        music = MusicGenerator(gateway, AudioJobRunner(paths), settings.audio_timeout)
        images = OpenClawImageGenerator(paths, settings, group=group)

        if mode == "check-gateway":
            print(
                "Gateway отвечает:",
                await gateway.reply([], {"name": "Проверка", "text": prompts.gateway_request}),
            )

            return

        if mode == "check-music":
            current_message: ContextMessage = {
                "name": "Проверка",
                "text": request if request is not None else prompts.music_request,
            }
            decision = await MessageRouter(gateway).route(
                [], current_message, {"force_addressed": True}
            )

            if decision.mode != ReplyMode.MUSIC or decision.music is None:
                raise BotError("Модель не распознала музыкальную просьбу для проверки.")

            if decision.load_participant_photos:
                current_message["load_participant_photos"] = True
            reply = await music.generate([], current_message, options=decision.music)
            destination = output or paths.runtime / "checks" / "music.ogg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(reply.audio.voice)
            print(f"Музыка готова: {destination.resolve()} ({reply.audio.duration} с)")

            return

        if mode == "check-image":
            current_image_message: ContextMessage = {
                "name": "Проверка",
                "text": request or prompts.image_request,
            }
            decision = await MessageRouter(gateway).route(
                [], current_image_message, {"force_addressed": True}
            )
            if decision.mode != ReplyMode.IMAGE or decision.image is None:
                raise BotError("Модель не распознала просьбу нарисовать картинку.")
            image_reply = await images.generate(
                decision.image,
                "diagnostic:" + decision.image.prompt,
                load_participant_photos=decision.load_participant_photos,
            )
            destination = output or paths.runtime / "checks" / "image.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(image_reply.path.read_bytes())
            print(f"Картинка готова: {destination.resolve()}")
            return

        if not settings.token:
            raise BotError("Заполни TELEGRAM_BOT_TOKEN в .env.")

        telegram_http_client = await resource_stack.enter_async_context(
            httpx.AsyncClient(follow_redirects=False)
        )
        telegram = TelegramClient(telegram_http_client, settings.token)
        bot_identity = await telegram.call("getMe")

        if mode == "check":
            print(f"Telegram OK: @{bot_identity['username']}; ID {bot_identity['id']}")
            print(
                "Gateway OK:",
                await gateway.reply([], {"name": "Проверка", "text": prompts.gateway_request}),
            )

            return

        if mode == "run" and not settings.chats:
            raise BotError("Сначала --discover-chats, затем заполни ALLOWED_CHAT_IDS.")

        if (await telegram.call("getWebhookInfo")).get("url"):
            raise BotError("У бота уже настроен webhook. Отключи прежнюю интеграцию; см. README.")

        conversation_service = None

        if mode == "run":
            memory = resource_stack.enter_context(SqliteConversationStore(paths.database))
            conversation_service = ConversationService(
                settings,
                telegram,
                gateway,
                bot_identity,
                memory,
                CooldownStore(paths.state),
                music,
                images,
                ReactionService(settings, telegram, gateway, bot_identity),
            )

        await poll(telegram, conversation_service, bot_identity, discover=mode == "discover-chats")

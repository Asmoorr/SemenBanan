from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

from semen_banan.config import AppPaths, Settings
from semen_banan.conversation.routing import RouteDecision
from semen_banan.errors import BotError
from semen_banan.images.models import ImageOptions, ImageReply
from semen_banan.integrations.openclaw_images import (
    ImageGenerationError,
    OpenClawImageGenerator,
    prepare_photo,
)
from semen_banan.integrations.telegram import TelegramClient
from tests.fixtures import route_json
from tests.unit.test_bot import create_service, message


def image_bytes() -> bytes:
    """Создаёт небольшое реальное изображение для тестирования.

    :return: Байты PNG с прозрачностью.
    """
    output = io.BytesIO()
    Image.new("RGBA", (120, 80), (255, 200, 0, 128)).save(output, format="PNG")
    return output.getvalue()


class ImageValidation(unittest.TestCase):
    """Проверки схемы режима и подготовки фото."""

    def test_route_roundtrip_and_validation(self) -> None:
        """Проверяет сохранение картинки и отклонение неподдерживаемых полей.

        :return: Не возвращает значение.
        """
        parameters = {"prompt": "Нарисуй жёлтого кота", "size": "1024x1536", "caption": "Вот кот"}
        route = RouteDecision.parse(route_json("image", parameters=parameters))
        self.assertEqual(RouteDecision.parse(json.dumps(route.to_payload())), route)
        self.assertEqual(route.image.prompt, parameters["prompt"])
        self.assertIsNone(route.music)
        for changes in (
            {"prompt": ""},
            {"prompt": 123},
            {"size": "1x1"},
            {"caption": "x" * 501},
            {"command": "whoami"},
            {"image": "/etc/passwd"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                RouteDecision.parse(route_json("image", parameters={**parameters, **changes}))

    def test_prepare_photo_and_corruption(self) -> None:
        """Проверяет декодирование, прозрачность, размер и повреждённые файлы.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            target = Path(directory) / "target.jpg"
            source.write_bytes(image_bytes())
            prepare_photo(source, target)
            with Image.open(target) as prepared:
                self.assertEqual(prepared.format, "JPEG")
                self.assertEqual(prepared.mode, "RGB")
            source.write_bytes(b"not an image")
            with self.assertRaises(ImageGenerationError):
                prepare_photo(source, target)


class ImageExecution(unittest.IsolatedAsyncioTestCase):
    """Проверки отдельного процесса, кеша и обработки ошибок."""

    async def test_generation_cache_and_cancellation(self) -> None:
        """Не запускает повторную генерацию и останавливает отменённый процесс.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            generator = OpenClawImageGenerator(
                AppPaths(Path(directory)), Settings("", frozenset(), "http://localhost", "")
            )
            source = Path(directory) / "fixture.png"
            source.write_bytes(image_bytes())
            options = ImageOptions("Кот; $(whoami)")
            script = "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(Path(sys.argv[2]).read_bytes())"
            with patch.object(
                generator,
                "command",
                side_effect=lambda options, output: [
                    sys.executable,
                    "-c",
                    script,
                    str(output),
                    str(source),
                ],
            ) as command:
                first = await generator.generate(options, "chat:message")
                second = await generator.generate(options, "chat:message")
                self.assertEqual(first.path, second.path)
                self.assertEqual(command.call_count, 1)
            command_arguments = generator.command(options, source)
            self.assertEqual(
                command_arguments[command_arguments.index("--prompt") + 1], options.prompt
            )

            process = AsyncMock()
            process.returncode = None
            process.wait.side_effect = asyncio.CancelledError
            with (
                patch(
                    "semen_banan.integrations.openclaw_images.asyncio.create_subprocess_exec",
                    return_value=process,
                ),
                patch(
                    "semen_banan.integrations.openclaw_images.stop_worker", new_callable=AsyncMock
                ) as stop,
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await generator.generate(options, "another-message")
                stop.assert_awaited_once_with(process)

    @unittest.skipUnless(os.name == "nt", "Проверка путей WSL только для Windows")
    async def test_wsl_output_uses_linux_file_share(self) -> None:
        """Не предполагает, что диск Windows автоматически смонтирован в WSL.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                "", frozenset(), "http://localhost", "", image_wsl_distro="OpenClawGateway"
            )
            generator = OpenClawImageGenerator(AppPaths(Path(directory)), settings)
            linux_path, readable_path = generator.output_paths(
                Path(directory) / "generation-test" / "image.png"
            )
            self.assertTrue(linux_path.startswith("/tmp/semen-banan-"))
            self.assertTrue(
                str(readable_path).startswith("\\\\wsl.localhost\\OpenClawGateway\\tmp\\")
            )
            self.assertNotIn("/mnt/", linux_path)

    async def test_failed_provider_is_reported(self) -> None:
        """Возвращает понятную ошибку при отказе внешнего генератора.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            generator = OpenClawImageGenerator(
                AppPaths(Path(directory)), Settings("", frozenset(), "http://localhost", "")
            )
            with patch.object(
                generator, "command", return_value=[sys.executable, "-c", "raise SystemExit(1)"]
            ):
                with self.assertRaises(ImageGenerationError):
                    await generator.generate(ImageOptions("Кот"), "failed")


class ImageDelivery(unittest.IsolatedAsyncioTestCase):
    """Проверка ответа фото, очереди и сообщения об ошибке."""

    async def test_queued_image_restores_without_reclassification(self) -> None:
        """Восстанавливает решение из SQLite и отправляет фото в нужную тему.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            telegram, gateway = AsyncMock(), AsyncMock()
            settings = Settings("", frozenset({-123}), "http://localhost", "", cooldown=0)
            bot = create_service(
                settings, telegram, gateway, {"id": 1, "username": "semen_bot"}, root / "state.json"
            )
            try:
                generator = AsyncMock()
                bot.images = generator
                photo = root / "ready.jpg"
                photo.write_bytes(b"photo")
                generator.generate.return_value = ImageReply(photo, "Кот", "[Семён нарисовал кота]")
                decision = RouteDecision.parse(
                    route_json(
                        "image", parameters={"prompt": "Кот", "size": "1024x1024", "caption": "Кот"}
                    )
                )
                incoming = {
                    **message("Семён, нарисуй кота", topic=42),
                    "_routing": decision.to_payload(),
                }
                bot.memory.queue_reply(incoming, "image", time.time() - 1)
                telegram.send_photo.side_effect = [BotError("Сеть недоступна"), {"message_id": 99}]
                await bot.process_pending()
                pending = bot.memory.due_reply(time.time() + 60)
                self.assertIsNotNone(pending)
                await bot.respond(*pending)
                self.assertIsNone(bot.memory.next_reply_due())
                gateway.classify.assert_not_awaited()
                telegram.send_photo.assert_awaited_with(-123, 10, b"photo", "Кот", 42)
                self.assertEqual(bot.memory.get(-123, 99)["body"], "[Семён нарисовал кота]")
                self.assertEqual(
                    generator.generate.await_args_list[0], generator.generate.await_args_list[1]
                )
            finally:
                bot.memory.close()

    async def test_permanent_failure_sends_text_once(self) -> None:
        """Сообщает об ошибке генерации и не оставляет бесконечный повтор.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            telegram, gateway = AsyncMock(), AsyncMock()
            gateway.classify.return_value = route_json(
                "image", parameters={"prompt": "Кот", "size": "1024x1024", "caption": ""}
            )
            telegram.call.return_value = {"message_id": 99}
            bot = create_service(
                Settings("", frozenset({-123}), "http://localhost", "", cooldown=0),
                telegram,
                gateway,
                {"id": 1, "username": "semen_bot"},
                Path(directory) / "state.json",
            )
            try:
                bot.images = AsyncMock()
                bot.images.generate.side_effect = ImageGenerationError("Генератор недоступен")
                await bot.handle(message("Нарисуй кота"))
                self.assertEqual(telegram.call.await_args.kwargs["text"], "Генератор недоступен")
                self.assertIsNone(bot.memory.next_reply_due())
                telegram.send_photo.assert_not_awaited()
            finally:
                bot.memory.close()

    async def test_telegram_multipart_reply_and_topic(self) -> None:
        """Проверяет загрузку JPEG с подписью, ответом и идентификатором темы.

        :return: Не возвращает значение.
        """
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Сохраняет запрос и возвращает успешный ответ Telegram.

            :param request: Исходящий HTTP-запрос клиента.
            :return: Ответ с идентификатором фото.
            """
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            telegram = TelegramClient(client, "unused")
            result = await telegram.send_photo(-123, 10, b"\xff\xd8\xffphoto", "Кот", 42)
            self.assertEqual(result["message_id"], 99)
        self.assertEqual(requests[0].url.path, "/botunused/sendPhoto")
        self.assertIn(b'name="message_thread_id"', requests[0].content)
        self.assertIn(b'name="reply_parameters"', requests[0].content)
        self.assertIn(b"image/jpeg", requests[0].content)

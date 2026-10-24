from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

from semen_banan.config import AppPaths, Settings
from semen_banan.conversation.routing import RouteDecision
from semen_banan.group import GroupCatalog, Participant, ParticipantPhotosError
from semen_banan.images.models import ImageOptions, ImageReply
from semen_banan.integrations.openclaw import OpenClawClient
from semen_banan.integrations.openclaw_images import OpenClawImageGenerator
from tests.fixtures import route_json
from tests.unit.test_bot import create_service, message


def sample_group(directory: Path) -> GroupCatalog:
    """Создаёт пять подписанных фотографий без обращения к личным данным.

    :param directory: Временный каталог теста.
    :return: Тестовая группа с пятью разными изображениями.
    """
    members = []
    for index in range(5):
        output = directory / f"member-{index}.png"
        Image.new("RGB", (64, 64), (index * 40, 100, 200)).save(output)
        members.append(
            Participant(str(index), f"Участник {index + 1}", (), ("музыкант",), (), output)
        )
    return GroupCatalog("Тестовая группа", "Пять участников", tuple(members))


class GroupRouting(unittest.TestCase):
    """Проверка строгого флага загрузки и совместимости очереди."""

    def test_photo_flag_and_legacy_format(self) -> None:
        """Сохраняет флаг и не включает фотографии для старого формата.

        :return: Не возвращает значение.
        """
        original = json.loads(route_json())
        self.assertFalse(RouteDecision.parse(json.dumps(original)).load_participant_photos)
        requested = {**original, "load_participant_photos": True}
        decision = RouteDecision.parse(json.dumps(requested))
        self.assertTrue(decision.load_participant_photos)
        self.assertEqual(RouteDecision.parse(json.dumps(decision.to_payload())), decision)
        for value in (1, "true", None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RouteDecision.parse(json.dumps({**original, "load_participant_photos": value}))
        with self.assertRaises(ValueError):
            RouteDecision.parse(
                json.dumps({**json.loads(route_json("ignore")), "load_participant_photos": True})
            )

    def test_missing_requested_photo_is_not_silently_skipped(self) -> None:
        """Не заменяет отсутствие фотографий выдуманным описанием внешности.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            group = sample_group(Path(directory))
            group.members[0].photo.unlink()
            with self.assertRaises(ParticipantPhotosError):
                group.photos()


class GroupGateway(unittest.IsolatedAsyncioTestCase):
    """Проверки постоянного контекста и условных мультимодальных запросов."""

    async def test_all_requests_include_facts_without_photos(self) -> None:
        """Передаёт справочник во всех режимах без чтения фотографий.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            group = sample_group(Path(directory))
            requests = []

            def handler(request: httpx.Request) -> httpx.Response:
                """Запоминает запрос модели и возвращает текст.

                :param request: HTTP-запрос к Gateway.
                :return: Успешный ответ модели.
                """
                requests.append(json.loads(request.content))
                return httpx.Response(200, json={"choices": [{"message": {"content": "ответ"}}]})

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                gateway = OpenClawClient(
                    client, Settings("", frozenset(), "http://localhost", ""), group=group
                )
                with patch.object(
                    GroupCatalog, "photos", side_effect=AssertionError("Фото не запрошены")
                ):
                    await gateway.classify([], {"text": "Кто играет на басу?"}, {})
                    await gateway.reply([], {"text": "Привет"})
                    await gateway.compose([], {"text": "Музыка"})
                    await gateway.arrange([], {"text": "Музыка"})
            for request in requests:
                user_content = request["messages"][1]["content"]
                self.assertIsInstance(user_content, str)
                data = json.loads(user_content)
                self.assertEqual(data["group_profile"]["name"], group.name)
                self.assertEqual(len(data["group_profile"]["members"]), 5)
                self.assertFalse(data["participant_photos_loaded"])
                self.assertNotIn("base64", user_content)

    async def test_requested_photos_are_all_labeled_in_order(self) -> None:
        """Передаёт ровно пять фотографий и явное соответствие именам.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            gateway = OpenClawClient(
                AsyncMock(),
                Settings("", frozenset(), "http://localhost", ""),
                group=sample_group(Path(directory)),
            )
            content = gateway.user_content(
                json.dumps({"reply_to": {"text": "Опиши одежду", "load_participant_photos": True}})
            )
            self.assertIsInstance(content, list)
            self.assertTrue(json.loads(content[0]["text"])["participant_photos_loaded"])
            photos = [part for part in content if part["type"] == "image_url"]
            self.assertEqual(len(photos), 5)
            for index in range(5):
                label = json.loads(content[1 + index * 2]["text"])
                self.assertEqual(label["photo_index"], index + 1)
                self.assertEqual(label["participant_name"], f"Участник {index + 1}")
                self.assertTrue(
                    photos[index]["image_url"]["url"].startswith("data:image/jpeg;base64,")
                )

    async def test_photo_request_survives_queue_and_reaches_image_generator(self) -> None:
        """Восстанавливает флаг из очереди без повторной классификации.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            telegram, gateway = AsyncMock(), AsyncMock()
            bot = create_service(
                Settings("", frozenset({-123}), "http://localhost", "", cooldown=0),
                telegram,
                gateway,
                {"id": 1, "username": "semen_bot"},
                Path(directory) / "state.json",
            )
            try:
                ready = Path(directory) / "ready.jpg"
                ready.write_bytes(b"image")
                bot.images = AsyncMock()
                bot.images.generate.return_value = ImageReply(ready, "Готово", "Рисунок участника")
                telegram.send_photo.return_value = {"message_id": 99}
                payload = json.loads(
                    route_json(
                        "image",
                        parameters={
                            "prompt": "Участник с бананом",
                            "size": "1024x1024",
                            "caption": "Готово",
                        },
                    )
                )
                payload["load_participant_photos"] = True
                incoming = {**message("Нарисуй участника"), "_routing": payload}
                bot.memory.queue_reply(incoming, "image", 0)
                await bot.process_pending()
                self.assertTrue(bot.images.generate.await_args.kwargs["load_participant_photos"])
                gateway.classify.assert_not_awaited()
                self.assertIsNone(bot.memory.next_reply_due())
            finally:
                bot.memory.close()

    async def test_image_command_contains_five_reference_files_only_on_request(self) -> None:
        """Выбирает edit с пятью образцами только после явного флага.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generator = OpenClawImageGenerator(
                AppPaths(root),
                Settings("", frozenset(), "http://localhost", ""),
                group=sample_group(root),
            )
            options = ImageOptions("Нарисуй участника")
            arguments = generator.command(options, root / "output.png")
            self.assertIn("generate", arguments)
            self.assertNotIn("--file", arguments)
            self.assertIn("Тестовая группа", arguments[arguments.index("--prompt") + 1])
            references = tuple(str(member.photo) for member in generator.group.members)
            arguments = generator.command(options, root / "output.png", reference_paths=references)
            self.assertIn("edit", arguments)
            self.assertEqual(arguments.count("--file"), 5)

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from semen_banan.config import AppPaths, Settings
from semen_banan.conversation.reactions import ReactionSelection, ReactionService
from semen_banan.errors import BotError
from semen_banan.integrations.telegram import TelegramClient
from tests.fixtures import route_json
from tests.unit.test_bot import create_service, message


class ReactionSchema(unittest.TestCase):
    """Проверки смыслового выбора и настроек вероятностей."""

    def test_allowed_emoji_only(self) -> None:
        """Отклоняет неизвестный эмодзи и неправильные типы без случайной замены.

        :return: Не возвращает значение.
        """
        result = ReactionSelection.parse(
            '{"addressed_to_bot":true,"emoji":"❤️","explicit_request":false}', ["❤"]
        )
        self.assertEqual(result.emoji, "❤")
        for content in (
            "{}",
            '{"addressed_to_bot":true,"emoji":"👍"}',
            '{"addressed_to_bot":true,"emoji":"👍","explicit_request":"true"}',
            '{"addressed_to_bot":"true","emoji":"👍","explicit_request":false}',
            '{"addressed_to_bot":false,"emoji":"🔥","explicit_request":false}',
            '{"addressed_to_bot":false,"emoji":"👍👍","explicit_request":false}',
        ):
            with self.subTest(content=content), self.assertRaises(BotError):
                ReactionSelection.parse(content, ["👍"])

    def test_configuration_probabilities(self) -> None:
        """Читает отдельные вероятности и отклоняет неверные значения.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            with patch.dict(
                "os.environ",
                {
                    "REACTION_PROBABILITY": "0.1",
                    "ADDRESSED_REACTION_PROBABILITY": "0.3333333333333333",
                },
            ):
                settings = Settings.load(paths)
                self.assertEqual(settings.reaction_probability, 0.1)
                self.assertEqual(settings.addressed_reaction_probability, 1 / 3)
            for value in ("-1", "1.1", "nan", "inf"):
                with (
                    patch.dict("os.environ", {"REACTION_PROBABILITY": value}),
                    self.assertRaises(BotError),
                ):
                    Settings.load(paths)


class ReactionBehavior(unittest.IsolatedAsyncioTestCase):
    """Проверки вероятностей и независимости от обычных ответов."""

    async def asyncSetUp(self) -> None:
        """Создаёт сервис реакций с заглушками Telegram и LLM.

        :return: Не возвращает значение.
        """
        self.settings = Settings("", frozenset({-123}), "http://localhost", "")
        self.telegram, self.gateway = AsyncMock(), AsyncMock()
        self.telegram.call.return_value = {
            "available_reactions": [
                {"type": "emoji", "emoji": "👍"},
                {"type": "emoji", "emoji": "😢"},
            ]
        }
        self.gateway.select_reaction.return_value = (
            '{"addressed_to_bot":false,"emoji":"👍","explicit_request":false}'
        )
        self.service = ReactionService(
            self.settings,
            self.telegram,
            self.gateway,
            {"id": 1, "username": "semen_bot", "name": "Семён"},
        )

    async def test_normal_probability_boundary(self) -> None:
        """Ставит реакцию ниже 0.1 и пропускает на границе.

        :return: Не возвращает значение.
        """
        for index, chance in enumerate((0.0999, 0.1)):
            incoming = {**message("Отличная репетиция"), "message_id": index + 10}
            with patch("semen_banan.conversation.reactions.random.random", return_value=chance):
                await self.service.maybe_react(incoming, [])
        reactions = [
            call
            for call in self.telegram.call.await_args_list
            if call.args[0] == "setMessageReaction"
        ]
        self.assertEqual(len(reactions), 1)
        self.assertEqual(reactions[0].kwargs["reaction"], [{"type": "emoji", "emoji": "👍"}])

    async def test_addressed_probability_boundary(self) -> None:
        """Применяет 1/3 для обращения и пропускает реакцию на границе вероятности.

        :return: Не возвращает значение.
        """
        self.gateway.select_reaction.return_value = (
            '{"addressed_to_bot":true,"emoji":"👍","explicit_request":false}'
        )
        with patch("semen_banan.conversation.reactions.random.random", return_value=0.3):
            await self.service.maybe_react(message("Семён, лайкни"), [])
        self.assertEqual(self.telegram.call.await_args.args[0], "setMessageReaction")
        self.gateway.select_reaction.reset_mock()
        with patch("semen_banan.conversation.reactions.random.random", return_value=1 / 3):
            await self.service.maybe_react({**message(), "message_id": 11}, [])
        self.gateway.select_reaction.assert_awaited_once()

    async def test_explicit_request_bypasses_probability(self) -> None:
        """Выполняет явную просьбу даже при нулевых вероятностях.

        :return: Не возвращает значение.
        """
        self.service.allowed_cache[-123] = (float("inf"), ["👻"])
        self.service.settings = replace(
            self.settings, reaction_probability=0, addressed_reaction_probability=0
        )
        self.gateway.select_reaction.return_value = (
            '{"addressed_to_bot":true,"emoji":"👻","explicit_request":true}'
        )
        with patch("semen_banan.conversation.reactions.random.random", return_value=0.999):
            await self.service.maybe_react(
                message("Семен а поставь реакт призрака на это сообщение"), []
            )
        self.assertEqual(self.telegram.call.await_args.args[0], "setMessageReaction")
        self.assertEqual(
            self.telegram.call.await_args.kwargs["reaction"], [{"type": "emoji", "emoji": "👻"}]
        )

    async def test_own_message_is_excluded_but_other_bots_and_media_allowed(self) -> None:
        """Исключает самого Семёна, но допускает медиа и других ботов.

        :return: Не возвращает значение.
        """
        incoming = message()
        incoming["from"]["id"] = 1
        with patch("semen_banan.conversation.reactions.random.random") as random:
            await self.service.maybe_react(incoming, [])
        random.assert_not_called()
        media = message()
        del media["text"]
        media["photo"] = [{"file_id": "photo"}]
        media["from"]["is_bot"] = True
        with patch("semen_banan.conversation.reactions.random.random", return_value=0.01):
            await self.service.maybe_react(media, [])
        self.assertEqual(self.gateway.select_reaction.await_args.args[2]["content_type"], "photo")
        self.assertEqual(self.telegram.call.await_args.args[0], "setMessageReaction")

    async def test_no_default_reaction_after_invalid_model_output(self) -> None:
        """Не заменяет неподходящий ответ модели стандартным эмодзи.

        :return: Не возвращает значение.
        """
        self.gateway.select_reaction.return_value = (
            '{"addressed_to_bot":false,"emoji":"🔥","explicit_request":false}'
        )
        with patch("semen_banan.conversation.reactions.random.random", return_value=0):
            await self.service.maybe_react(message(), [])
        self.assertEqual(self.telegram.call.await_count, 1)
        self.assertEqual(self.telegram.call.await_args.args[0], "getChat")

    async def test_chat_limits_and_duplicate_update(self) -> None:
        """Не реагирует повторно и соблюдает отключённые реакции группы.

        :return: Не возвращает значение.
        """
        with patch("semen_banan.conversation.reactions.random.random", return_value=0) as random:
            await self.service.maybe_react(message(), [])
            await self.service.maybe_react(message(), [])
        self.assertEqual(random.call_count, 1)
        self.service.allowed_cache.clear()
        self.telegram.call.return_value = {"available_reactions": []}
        self.gateway.select_reaction.reset_mock()
        with patch("semen_banan.conversation.reactions.random.random", return_value=0):
            await self.service.maybe_react({**message(), "message_id": 11}, [])
        self.gateway.select_reaction.assert_not_awaited()

    async def test_reaction_failure_does_not_block_regular_reply(self) -> None:
        """Продолжает обычный ответ при недопустимой реакции в общей классификации.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            payload = json.loads(route_json())
            payload["reaction"] = {
                "addressed_to_bot": True,
                "emoji": "🔥",
                "explicit_request": False,
            }
            self.gateway.classify.return_value = json.dumps(payload)
            self.gateway.reply.return_value = "Привет"
            bot = create_service(
                replace(self.settings, cooldown=0),
                self.telegram,
                self.gateway,
                {"id": 1, "username": "semen_bot"},
                Path(directory) / "state.json",
            )
            bot.reactions = self.service
            try:
                with patch("semen_banan.conversation.reactions.random.random", return_value=0):
                    await bot.handle(message())
                self.gateway.reply.assert_awaited_once()
                self.gateway.select_reaction.assert_not_awaited()
                self.assertEqual(self.telegram.call.await_args.args[0], "sendMessage")
                self.assertIsNone(bot.memory.next_reply_due())
            finally:
                bot.memory.close()

    async def test_combined_classification_avoids_separate_reaction_call(self) -> None:
        """Получает реакцию вместе с маршрутом, сохраняя вероятности и явные просьбы."""
        cases = (
            ("ignore", False, False, 0.099, True),
            ("ignore", False, False, 0.1, False),
            ("text", True, False, 0.3, True),
            ("text", True, False, 1 / 3, False),
            ("ignore", True, True, 0.999, True),
        )
        for mode, addressed, explicit, chance, sends in cases:
            with self.subTest(mode=mode, chance=chance), tempfile.TemporaryDirectory() as directory:
                self.telegram.reset_mock()
                self.gateway.reset_mock()
                self.service.seen.clear()
                self.service.allowed_cache[-123] = (float("inf"), ["👍"])
                payload = json.loads(route_json(mode))
                payload["reaction"] = {
                    "addressed_to_bot": addressed,
                    "emoji": "👍",
                    "explicit_request": explicit,
                }
                self.gateway.classify.return_value = json.dumps(payload)
                self.gateway.reply.return_value = "Привет"
                bot = create_service(
                    replace(self.settings, cooldown=0, spontaneous_probability=0),
                    self.telegram,
                    self.gateway,
                    {"id": 1, "username": "semen_bot"},
                    Path(directory) / "state.json",
                )
                bot.reactions = self.service
                try:
                    with patch(
                        "semen_banan.conversation.reactions.random.random", return_value=chance
                    ):
                        await bot.handle(message())
                    self.gateway.classify.assert_awaited_once()
                    self.gateway.select_reaction.assert_not_awaited()
                    metadata = self.gateway.classify.await_args.args[2]
                    self.assertEqual(metadata["available_reactions"], ["👍"])
                    sent = any(
                        call.args[0] == "setMessageReaction"
                        for call in self.telegram.call.await_args_list
                    )
                    self.assertEqual(sent, sends)
                finally:
                    bot.memory.close()

    async def test_telegram_payload(self) -> None:
        """Проверяет настоящий формат HTTP-запроса реакции без отправки в группу.

        :return: Не возвращает значение.
        """
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Сохраняет исходящий запрос для проверки формата.

            :param request: HTTP-запрос Telegram.
            :return: Успешный ответ API.
            """
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "result": True})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await TelegramClient(client, "unused").call(
                "setMessageReaction",
                chat_id=-123,
                message_id=10,
                reaction=[{"type": "emoji", "emoji": "👍"}],
                is_big=False,
            )
        self.assertEqual(requests[0].url.path, "/botunused/setMessageReaction")
        self.assertEqual(
            json.loads(requests[0].content)["reaction"], [{"type": "emoji", "emoji": "👍"}]
        )

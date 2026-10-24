from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from semen_banan.config import Settings
from semen_banan.conversation.routing import MessageRouter, ReplyMode, RouteDecision
from semen_banan.errors import BotError
from semen_banan.integrations.openclaw import OpenClawClient
from tests.fixtures import route_json
from tests.unit.test_bot import create_service, message


class RoutingSchema(unittest.TestCase):
    """Проверки схемы решений маршрутизатора."""

    def test_valid_music_options_and_style(self) -> None:
        """Проверяет типизированные параметры музыки и характера.

        :return: Не возвращает значение.
        """
        result = RouteDecision.parse(
            route_json(
                "music",
                parameters={
                    "composer": "nanomaestro",
                    "drums": False,
                    "speech": False,
                },
                style="Будь добрее",
            )
        )
        self.assertTrue(result.music.use_nano)
        self.assertTrue(result.music.solo)
        self.assertEqual(result.style_request, "Будь добрее")
        self.assertEqual(RouteDecision.parse(json.dumps(result.to_payload())), result)

    def test_invalid_or_unsupported_decisions_are_rejected(self) -> None:
        """Проверяет отклонение неподдерживаемых решений маршрутизатора.

        :return: Не возвращает значение.
        """
        valid = json.loads(route_json("music"))
        invalid = [
            None,
            [],
            {},
            {**valid, "mode": "shell"},
            {**valid, "parameters": {**valid["parameters"], "speech": "false"}},
            {**valid, "parameters": {**valid["parameters"], "composer": "other"}},
            {**valid, "parameters": {**valid["parameters"], "duration": 300}},
            {**valid, "trigger": "banana"},
            {**valid, "trigger": "none"},
            {**valid, "style_request": "x" * 501},
            {**json.loads(route_json("ignore")), "style_request": "Новый стиль"},
        ]

        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                RouteDecision.parse(json.dumps(payload))


class RouterContract(unittest.IsolatedAsyncioTestCase):
    """Проверки контракта маршрутизации через Gateway."""

    async def test_invalid_json_is_corrected_once(self) -> None:
        """Проверяет единственную попытку исправления JSON маршрутизации.

        :return: Не возвращает значение.
        """
        gateway = AsyncMock()
        gateway.classify.side_effect = ["```bad json```", route_json()]
        result = await MessageRouter(gateway).route([], {"text": "Привет"}, {})
        self.assertEqual(result.mode, ReplyMode.TEXT)
        self.assertIn("previous_json", gateway.classify.await_args.kwargs["correction"])
        self.assertEqual(gateway.classify.await_count, 2)

    async def test_repeated_invalid_response_fails_without_a_guessed_mode(self) -> None:
        """Проверяет ошибку без локального угадывания режима.

        :return: Не возвращает значение.
        """
        gateway = AsyncMock()
        gateway.classify.return_value = "no JSON"

        with self.assertRaises(BotError):
            await MessageRouter(gateway).route([], {"text": "Сыграй"}, {})

        self.assertEqual(gateway.classify.await_count, 2)

    async def test_http_request_contains_context_and_routing_schema(self) -> None:
        """Проверяет передачу контекста и инструкции маршрутизации.

        :return: Не возвращает значение.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Имитирует ответ внешнего HTTP-сервиса.

            :param request: Исходная просьба или задание генерации.
            :return: Подготовленный HTTP-ответ для проверяемого запроса.
            """
            body = json.loads(request.content)
            self.assertEqual(body["model"], "openclaw/semyon")
            self.assertEqual(body["tool_choice"], "none")
            system, user = body["messages"]
            self.assertIn("маршрутизатор", system["content"])
            data = json.loads(user["content"])
            self.assertEqual(data["conversation_chain"][0]["text"], "Предыдущий трек")
            self.assertEqual(data["current"]["text"], "Теперь убери голос")
            self.assertTrue(data["metadata"]["in_chain"])

            return httpx.Response(
                200, json={"choices": [{"message": {"content": route_json("music")}}]}
            )

        settings = Settings("unused", frozenset(), "http://localhost", "unused")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await MessageRouter(OpenClawClient(client, settings)).route(
                [{"name": "Семён", "text": "Предыдущий трек"}],
                {"text": "Теперь убери голос"},
                {"in_chain": True},
            )

        self.assertEqual(result.mode, ReplyMode.MUSIC)


class RoutingBehavior(unittest.IsolatedAsyncioTestCase):
    """Проверки очереди и контекста при маршрутизации через LLM."""

    async def asyncSetUp(self) -> None:
        """Подготавливает временные ресурсы и зависимости теста.

        :return: Не возвращает значение.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings("unused", frozenset({-123}), "http://localhost", "unused")
        self.telegram = AsyncMock()
        self.gateway = AsyncMock()
        self.gateway.classify.return_value = route_json()
        self.gateway.reply.return_value = "Ответ"
        self.path = Path(self.temp.name) / "state.json"
        self.bot = create_service(
            self.settings,
            self.telegram,
            self.gateway,
            {"id": 1, "username": "semen_bot"},
            self.path,
        )

    async def asyncTearDown(self) -> None:
        """Освобождает временные ресурсы после теста.

        :return: Не возвращает значение.
        """
        self.bot.memory.close()

    async def test_forbidden_messages_never_reach_classifier(self) -> None:
        """Проверяет фильтрацию запрещённых сообщений до запроса LLM.

        :return: Не возвращает значение.
        """
        samples = [message(chat=-999), message(), message(), message(), message()]
        samples[1]["from"]["is_bot"] = True
        samples[2]["chat"]["type"] = "private"
        samples[3]["date"] -= 121
        samples[4]["sender_chat"] = {"id": -123}

        for item in samples:
            await self.bot.handle(item)

        self.gateway.classify.assert_not_awaited()

    async def test_saved_music_options_survive_restart_without_reclassification(self) -> None:
        """Проверяет восстановление музыкальных параметров без повторной классификации.

        :return: Не возвращает значение.
        """
        self.bot.last["-123"] = time.time()
        self.gateway.classify.return_value = route_json(
            "music",
            parameters={
                "composer": "nanomaestro",
                "drums": True,
                "speech": False,
            },
        )
        await self.bot.handle(message("Сделай как раньше, но без голоса"))
        due = self.bot.memory.next_reply_due()
        self.bot.memory.close()
        self.bot = create_service(
            self.settings,
            self.telegram,
            self.gateway,
            {"id": 1, "username": "semen_bot"},
            self.path,
        )
        self.bot.last["-123"] = 0
        self.gateway.classify.side_effect = AssertionError("Неожиданная повторная классификация")
        self.bot.music.generate = AsyncMock(
            side_effect=BotError("Аудиогенератор временно недоступен")
        )

        with patch("semen_banan.conversation.service.time.time", return_value=due + 1):
            await self.bot.process_pending()

        options = self.bot.music.generate.await_args.kwargs["options"]
        self.assertTrue(options.use_nano)
        self.assertFalse(options.speech)
        self.assertEqual(self.gateway.classify.await_count, 1)
        self.assertIsNotNone(self.bot.memory.next_reply_due())

    async def test_classification_failure_is_retried_then_stored_as_a_resolved_job(self) -> None:
        """Проверяет повтор классификации и сохранение готового решения.

        :return: Не возвращает значение.
        """
        self.gateway.classify.side_effect = BotError("Сервис недоступен")
        await self.bot.handle(message())
        due = self.bot.memory.next_reply_due()
        self.telegram.call.assert_not_awaited()
        self.gateway.classify.side_effect = None
        self.gateway.classify.return_value = route_json()
        self.gateway.reply.side_effect = BotError("Сервис недоступен")

        with patch("semen_banan.conversation.service.time.time", return_value=due + 1):
            await self.bot.process_pending()

        pending, kind = self.bot.memory.due_reply(time.time() + 1000)
        self.assertEqual(kind, "text")
        self.assertEqual(pending["_routing"]["mode"], "text")
        self.gateway.classify.side_effect = AssertionError("Неожиданная повторная классификация")
        self.gateway.reply.side_effect = None

        with patch("semen_banan.conversation.service.time.time", return_value=due + 32):
            await self.bot.process_pending()

        self.telegram.call.assert_awaited_once()

    async def test_legacy_pending_message_is_classified_with_extended_age_limit(self) -> None:
        """Проверяет обработку задания от прежней версии очереди.

        :return: Не возвращает значение.
        """
        old = message("Семён, продолжи")
        old["date"] -= 300
        self.bot.memory.queue_reply(old, "direct", time.time() - 1)
        await self.bot.process_pending()
        self.gateway.classify.assert_awaited_once()
        self.telegram.call.assert_awaited_once()

    async def test_style_change_is_not_reapplied_on_retry(self) -> None:
        """Проверяет однократное сохранение изменения характера.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json(style="Будь добрее")
        self.gateway.reply.side_effect = BotError("Сервис недоступен")
        await self.bot.handle(message("Смягчи тон"))
        due = self.bot.memory.next_reply_due()
        self.gateway.reply.side_effect = None

        with patch("semen_banan.conversation.service.time.time", return_value=due + 1):
            await self.bot.process_pending()

        self.assertEqual(self.bot.memory.style_requests(-123), ["Будь добрее"])
        self.assertEqual(self.gateway.classify.await_count, 1)

    async def test_context_and_reply_metadata_reach_model(self) -> None:
        """Проверяет передачу контекста и признаков цепочки в LLM.

        :return: Не возвращает значение.
        """
        first = message("Семён, привет")
        first["message_id"] = 9
        self.bot.memory.record_incoming(first, 1, True)
        current_message = message("Теперь сделай наоборот")
        current_message["reply_to_message"] = {
            "message_id": 9,
            "from": {"id": 7},
            "text": first["text"],
        }
        self.gateway.classify.return_value = route_json("ignore")
        await self.bot.handle(current_message)
        conversation_context, request, metadata = self.gateway.classify.await_args.args
        self.assertEqual(conversation_context[0]["text"], first["text"])
        self.assertEqual(request["text"], current_message["text"])
        self.assertTrue(metadata["in_chain"])
        self.telegram.call.assert_not_awaited()

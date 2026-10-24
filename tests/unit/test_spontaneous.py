from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from semen_banan.audio.jobs import AudioError
from semen_banan.audio.models import AudioResult
from semen_banan.config import Settings
from semen_banan.conversation.routing import MessageRouter, ReplyMode, ReplyTrigger, RouteDecision
from semen_banan.conversation.style import is_reply_style_valid, normalize_reply_style
from semen_banan.errors import BotError
from tests.fixtures import route_json
from tests.unit.test_bot import create_service, message


class ReplyStyle(unittest.TestCase):
    """Проверки обязательного оформления реплик."""

    def test_quotes_dashes_and_paragraph_endings(self) -> None:
        """Исправляет оформление, сохраняя внутренние точки и авторские скобки.

        :return: Не возвращает значение.
        """
        cases = {
            "Он сказал: «Рок — это жизнь».": 'Он сказал: "Рок - это жизнь"',
            "“Раз – два”.\n\nПервое. Второе.": '"Раз - два"\n\nПервое. Второе',
            "Версия 3.13.\nСледующий абзац.": "Версия 3.13\nСледующий абзац",
            "Сказал «Да.»": 'Сказал "Да"',
            "Шутка.)": "Шутка)",
            "Ирония)": "Ирония)",
            "Без скобки.": "Без скобки",
            "Ну...": "Ну…",
            "Вопрос? Ответ!": "Вопрос? Ответ!",
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(normalize_reply_style(original), expected)
                self.assertEqual(normalize_reply_style(expected), expected)
                self.assertTrue(is_reply_style_valid(expected))


class SpontaneousReplies(unittest.IsolatedAsyncioTestCase):
    """Проверки вероятностей, голосовых ответов и отсутствия отложенного спама."""

    async def asyncSetUp(self) -> None:
        """Создаёт изолированный диалог и заглушку синтеза речи.

        :return: Не возвращает значение.
        """
        self.temporary = tempfile.TemporaryDirectory()
        self.telegram = AsyncMock()
        self.telegram.call.return_value = {"message_id": 99}
        self.telegram.send_voice.return_value = {"message_id": 99}
        self.gateway = AsyncMock()
        self.gateway.classify.return_value = route_json("ignore")
        self.gateway.reply.return_value = "«Вот это — репетиция»."
        self.bot = create_service(
            Settings("", frozenset({-123}), "http://localhost", ""),
            self.telegram,
            self.gateway,
            {"id": 1, "username": "semen_bot"},
            Path(self.temporary.name) / "state.json",
        )
        self.bot.music.audio.speak = AsyncMock(return_value=AudioResult(b"OggSspeech", 3, 123))

    async def asyncTearDown(self) -> None:
        """Закрывает временное хранилище после проверки.

        :return: Не возвращает значение.
        """
        self.bot.memory.close()
        self.temporary.cleanup()

    async def test_one_in_twenty_boundary(self) -> None:
        """Не отвечает при случайном числе на границе 0.05.

        :return: Не возвращает значение.
        """
        with patch("semen_banan.conversation.service.random.random", return_value=0.05) as random:
            await self.bot.handle(message("Сегодня отличная репетиция"))
        self.gateway.reply.assert_not_awaited()
        self.assertEqual(random.call_count, 1)
        self.assertIsNone(self.bot.memory.next_reply_due())

    async def test_text_at_four_fifths_boundary(self) -> None:
        """Выбирает текст при успешном шансе и числе не меньше 0.2.

        :return: Не возвращает значение.
        """
        with patch("semen_banan.conversation.service.random.random", side_effect=[0.049, 0.2]):
            await self.bot.handle(message("Сегодня отличная репетиция", topic=42))
        self.assertEqual(self.telegram.call.await_args.kwargs["text"], '"Вот это - репетиция"')
        self.assertEqual(self.telegram.call.await_args.kwargs["message_thread_id"], 42)
        self.bot.music.audio.speak.assert_not_awaited()
        self.assertEqual(self.bot.memory.get(-123, 99)["body"], '"Вот это - репетиция"')

    async def test_one_fifth_voice_and_no_music(self) -> None:
        """Озвучивает ту же реплику без запуска музыкального композитора.

        :return: Не возвращает значение.
        """
        with patch("semen_banan.conversation.service.random.random", side_effect=[0.01, 0.199]):
            await self.bot.handle(message("Принёс новую гитару", topic=42))
        self.bot.music.audio.speak.assert_awaited_once_with('"Вот это - репетиция"', timeout=90)
        self.telegram.send_voice.assert_awaited_once_with(-123, 10, b"OggSspeech", 3, 42)
        self.gateway.compose.assert_not_awaited()
        self.telegram.call.assert_not_awaited()

    async def test_cooldown_and_failure_do_not_queue(self) -> None:
        """Пропускает случайные ответы при интервале и ошибке синтеза.

        :return: Не возвращает значение.
        """
        with patch("semen_banan.conversation.service.random.random", side_effect=[0, 0]):
            self.bot.music.audio.speak.side_effect = AudioError("Синтез недоступен")
            await self.bot.handle(message("Репетиция"))
        self.assertIsNone(self.bot.memory.next_reply_due())
        with patch("semen_banan.conversation.service.random.random") as random:
            await self.bot.handle(message("Ещё одна репетиция"))
        random.assert_not_called()
        self.assertIsNone(self.bot.memory.next_reply_due())

    async def test_direct_reply_does_not_roll_dice(self) -> None:
        """Всегда обрабатывает прямое обращение обычным способом.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json("text")
        with patch("semen_banan.conversation.service.random.random") as random:
            await self.bot.handle(message("Семён, привет"))
        random.assert_not_called()
        self.telegram.call.assert_awaited_once()

    async def test_model_cannot_choose_spontaneous_voice(self) -> None:
        """Оставляет вероятностное решение приложению, а не LLM.

        :return: Не возвращает значение.
        """
        decision = RouteDecision(ReplyMode.VOICE, ReplyTrigger.SPONTANEOUS)
        self.gateway.classify.return_value = json.dumps(decision.to_payload())
        with self.assertRaises(BotError):
            await MessageRouter(self.gateway).route([], {"text": "Привет"}, {})

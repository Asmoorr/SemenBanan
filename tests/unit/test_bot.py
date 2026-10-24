from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from semen_banan.audio.jobs import AudioError, AudioJobRunner
from semen_banan.audio.models import AudioResult
from semen_banan.audio.validation import parse_score
from semen_banan.config import AppPaths, Settings
from semen_banan.conversation.context import ContextBuilder
from semen_banan.conversation.models import BotIdentity, TelegramMessage
from semen_banan.conversation.service import ConversationService
from semen_banan.errors import BotError
from semen_banan.generation.service import MusicGenerator
from semen_banan.integrations.openclaw import OpenClawClient as Gateway
from semen_banan.integrations.telegram import TelegramClient as Telegram
from semen_banan.storage.cooldown import CooldownStore
from semen_banan.storage.sqlite import SqliteConversationStore as ConversationStore
from tests.fixtures import route_json


def create_service(
    settings: Settings,
    telegram: AsyncMock,
    gateway: AsyncMock,
    bot_identity: BotIdentity,
    state_path: Path,
) -> ConversationService:
    """Создаёт сервис диалога с временными хранилищами для теста.

    :param settings: Проверенные настройки приложения.
    :param telegram: Клиент Telegram для получения и отправки сообщений.
    :param gateway: Клиент OpenClaw для работы с языковой моделью.
    :param bot_identity: Идентификатор и имя Telegram-бота.
    :param state_path: Путь к тестовому файлу интервалов.
    :return: Сервис с переданными заглушками внешних зависимостей.
    """
    memory = ConversationStore(state_path.with_name("memory.sqlite3"))
    music = MusicGenerator(gateway, AudioJobRunner(AppPaths.load()), settings.audio_timeout)
    bot = ConversationService(
        settings, telegram, gateway, bot_identity, memory, CooldownStore(state_path), music
    )

    return bot


def message(text: str = "Семён", chat: int = -123, topic: int = 0) -> TelegramMessage:
    """Создаёт тестовое сообщение Telegram.

    :param text: Текст сообщения или речевой фразы.
    :param chat: Идентификатор тестовой группы.
    :param topic: Идентификатор темы группы, 0 для общего чата.
    :return: Данные сообщения с заданной группой и темой.
    """
    return {
        "text": text,
        "chat": {"id": chat, "type": "supergroup"},
        "from": {"id": 7, "first_name": "Друг", "is_bot": False},
        "date": time.time(),
        "message_id": 10,
        "message_thread_id": topic,
    }


class Behavior(unittest.IsolatedAsyncioTestCase):
    """Проверки обработки сообщений и очереди ответов."""

    async def asyncSetUp(self) -> None:
        """Подготавливает временные ресурсы и зависимости теста.

        :return: Не возвращает значение.
        """
        random_patch = patch("semen_banan.conversation.service.random.random", return_value=0.99)
        random_patch.start()
        self.addCleanup(random_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings("unused", frozenset({-123}), "http://localhost", "unused")
        self.telegram = AsyncMock()
        self.gateway = AsyncMock()
        self.gateway.classify.return_value = route_json()
        self.gateway.reply.return_value = "Банановый комитет одобряет"
        self.arrangement = {
            "drums": [{"midi": 36, "beat": 0, "velocity": 70}],
            "speech": [{"beat": 0, "text": "С вами Семён."}],
        }
        self.gateway.arrange.return_value = json.dumps(self.arrangement)
        self.audio = AudioResult(b"OggSvoice", 11, 12345)
        self.bot = create_service(
            self.settings,
            self.telegram,
            self.gateway,
            {"username": "semen_bot", "id": 1},
            Path(self.temp.name) / "state.json",
        )

    async def asyncTearDown(self) -> None:
        """Освобождает временные ресурсы после теста.

        :return: Не возвращает значение.
        """
        self.bot.memory.close()
        self.temp.cleanup()

    async def test_only_allowed_triggered_messages(self) -> None:
        """Проверяет фильтрацию недопустимых сообщений и решение промолчать.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json("ignore")
        await self.bot.handle(message("Привет"))
        await self.bot.handle(message(chat=-999))
        m = message()
        m["from"]["is_bot"] = True
        await self.bot.handle(m)
        m = message()
        m["date"] -= 180
        await self.bot.handle(m)
        self.telegram.call.assert_not_awaited()
        self.gateway.reply.assert_not_awaited()

    async def test_direct_ignores_probability_and_waits_for_cooldown(self) -> None:
        """Проверяет очередь прямого обращения во время интервала.

        :return: Не возвращает значение.
        """
        first = message()
        first["message_id"] = 10
        second = message("@semen_bot снова вопрос")
        second["message_id"] = 11

        with patch("semen_banan.conversation.service.random.random", return_value=0.99):
            await self.bot.handle(first)
            await self.bot.handle(second)

        self.telegram.call.assert_awaited_once()
        self.assertIn("-123", json.loads(self.bot.cooldown.path.read_text()))
        due = self.bot.memory.next_reply_due()
        self.assertIsNotNone(due)

        with patch("semen_banan.conversation.service.time.time", return_value=due + 1):
            await self.bot.process_pending()

        self.assertEqual(self.telegram.call.await_count, 2)
        self.assertIsNone(self.bot.memory.next_reply_due())

    async def test_pending_reply_survives_restart(self) -> None:
        """Проверяет восстановление отложенного ответа после перезапуска.

        :return: Не возвращает значение.
        """
        first = message()
        first["message_id"] = 10
        second = message("Семён, ещё вопрос")
        second["message_id"] = 11
        await self.bot.handle(first)
        await self.bot.handle(second)
        due = self.bot.memory.next_reply_due()
        self.bot.memory.close()
        self.bot = create_service(
            self.settings,
            self.telegram,
            self.gateway,
            {"username": "semen_bot", "id": 1},
            Path(self.temp.name) / "state.json",
        )

        with patch("semen_banan.conversation.service.time.time", return_value=due + 1):
            await self.bot.process_pending()

        self.assertEqual(self.telegram.call.await_count, 2)
        self.assertIsNone(self.bot.memory.next_reply_due())

    async def test_banana_probability_and_no_fifteen_minute_pause(self) -> None:
        """Проверяет вероятность бананового ответа и общий интервал.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json(trigger="banana")

        with patch("semen_banan.conversation.service.random.random", return_value=0.25):
            await self.bot.handle(message("бананы"))

        self.gateway.reply.assert_not_awaited()

        with patch(
            "semen_banan.conversation.service.random.random", side_effect=[0.04, 0.2, 0.04, 0.2]
        ):
            await self.bot.handle(message("бананы"))
            self.bot.last["-123"] -= 11
            await self.bot.handle(message("бананы"))

        self.assertEqual(self.telegram.call.await_count, 2)

    async def test_gateway_failure_stays_silent(self) -> None:
        """Проверяет отсутствие публикации при ошибке Gateway.

        :return: Не возвращает значение.
        """
        self.gateway.reply.side_effect = BotError("Сервис недоступен")
        await self.bot.handle(message())
        self.telegram.call.assert_not_awaited()

    async def test_reply_to_bot_passes_quoted_text_to_gateway(self) -> None:
        """Проверяет передачу цитаты ответа в контекст модели.

        :return: Не возвращает значение.
        """
        m = message("ну ты даёшь")
        m["reply_to_message"] = {"from": {"id": 1}, "text": "Шутка Семёна"}
        await self.bot.handle(m)
        self.assertEqual(self.gateway.reply.call_args.args[1]["in_reply_to_semyon"], "Шутка Семёна")
        self.telegram.call.assert_awaited_once()

    async def test_topic_context_isolation(self) -> None:
        """Проверяет изоляцию контекста разных тем.

        :return: Не возвращает значение.
        """
        self.gateway.classify.side_effect = [route_json("ignore"), route_json()]
        await self.bot.handle(message("секрет из другой темы", topic=3))
        await self.bot.handle(message(topic=4))
        self.assertEqual(self.gateway.reply.call_args.args[0], [])
        self.assertEqual(self.telegram.call.call_args.kwargs["message_thread_id"], 4)

    async def test_gateway_contract(self) -> None:
        """Проверяет формат запроса к OpenClaw Gateway.

        :return: Не возвращает значение.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Имитирует ответ внешнего HTTP-сервиса.

            :param request: Исходная просьба или задание генерации.
            :return: Подготовленный HTTP-ответ для проверяемого запроса.
            """
            body = json.loads(request.content)
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(body["model"], "openclaw/semyon")
            self.assertEqual(body["tool_choice"], "none")
            self.assertNotIn("user", body)

            return httpx.Response(200, json={"choices": [{"message": {"content": "банан"}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await Gateway(client, self.settings).reply([], {"text": "Семён"})
            self.assertEqual(result, "банан")

    async def test_reply_chain_continues_through_other_people(self) -> None:
        """Проверяет продолжение цепочки через сообщения участников.

        :return: Не возвращает значение.
        """
        self.telegram.call.return_value = {"message_id": 1000}
        first = message("Семён, начни шутку")
        first["message_id"] = 10
        await self.bot.handle(first)
        self.bot.last["-123"] -= 11
        second = message("Ну ты даёшь")
        second["message_id"] = 11
        second["reply_to_message"] = {
            "message_id": 1000,
            "from": {"id": 1},
            "text": "Банановый комитет одобряет",
        }
        self.telegram.call.return_value = {"message_id": 1001}
        await self.bot.handle(second)
        self.bot.last["-123"] -= 11
        third = message("А я согласен")
        third["message_id"] = 12
        third["reply_to_message"] = {"message_id": 11, "from": {"id": 7}, "text": "Ну ты даёшь"}
        await self.bot.handle(third)
        self.assertEqual(self.telegram.call.await_count, 3)
        chain = self.gateway.reply.call_args.args[0]
        self.assertEqual(
            [x["text"] for x in chain],
            ["Семён, начни шутку", "Банановый комитет одобряет", "Ну ты даёшь"],
        )

    async def test_character_request_persists_across_restart(self) -> None:
        """Проверяет сохранение пожеланий к характеру после перезапуска.

        :return: Не возвращает значение.
        """
        first = message("Семён, поменяй характер: будь добрее")
        self.gateway.classify.return_value = route_json(style=first["text"])
        first["message_id"] = 10
        await self.bot.handle(first)
        self.assertEqual(self.gateway.reply.call_args.args[2], [first["text"]])
        self.bot.memory.close()
        self.bot = create_service(
            self.settings,
            self.telegram,
            self.gateway,
            {"username": "semen_bot", "id": 1},
            Path(self.temp.name) / "state.json",
        )
        self.bot.last["-123"] -= 11
        self.gateway.classify.return_value = route_json()
        second = message("Семён, как дела?")
        second["message_id"] = 11
        await self.bot.handle(second)
        self.assertEqual(self.gateway.reply.call_args.args[2], [first["text"]])

    async def test_style_request_without_name_is_actionable(self) -> None:
        """Проверяет применение распознанного изменения характера без имени.

        :return: Не возвращает значение.
        """
        m = message("нужно поменять характер: стань более веселым")
        self.gateway.classify.return_value = route_json(trigger="request", style=m["text"])
        m["message_id"] = 42
        await self.bot.handle(m)
        self.telegram.call.assert_awaited_once()
        self.assertEqual(self.gateway.reply.call_args.args[2], [m["text"]])

    async def test_music_request_routes_to_voice_without_name(self) -> None:
        """Проверяет музыкальный ответ без явного обращения по имени.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json("music", parameters=None)
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.gateway.compose.return_value = json.dumps(score)
        self.telegram.send_voice.return_value = {"message_id": 1000}

        with patch(
            "semen_banan.audio.jobs.AudioJobRunner.render", new=AsyncMock(return_value=self.audio)
        ):
            await self.bot.handle(message("сыграй на пианино что-нибудь"))

        self.gateway.reply.assert_not_awaited()
        self.gateway.compose.assert_awaited_once()
        self.telegram.send_voice.assert_awaited_once_with(-123, 10, b"OggSvoice", 11, 0)
        self.assertIsNotNone(self.bot.memory.get(-123, 1000))

    async def test_track_request_routes_to_voice_instead_of_text(self) -> None:
        """Проверяет отправку музыки при выбранном музыкальном режиме.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json("music", parameters=None)
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.gateway.compose.return_value = json.dumps(score)
        self.telegram.send_voice.return_value = {"message_id": 1000}
        text = (
            "@semen_banani_bot сделай трек про бананы и как им классно жить на 20 секунд с карданом"
        )

        with patch(
            "semen_banan.audio.jobs.AudioJobRunner.render", new=AsyncMock(return_value=self.audio)
        ) as renderer:
            await self.bot.handle(message(text))

        self.gateway.reply.assert_not_awaited()
        self.gateway.compose.assert_awaited_once()
        renderer.assert_awaited_once_with(score, False, self.arrangement, timeout=90)
        self.telegram.send_voice.assert_awaited_once_with(-123, 10, b"OggSvoice", 11, 0)

    async def test_voice_upload_is_multipart_and_replies_to_request(self) -> None:
        """Проверяет загрузку голосового ответом на исходное сообщение.

        :return: Не возвращает значение.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Имитирует ответ внешнего HTTP-сервиса.

            :param request: Исходная просьба или задание генерации.
            :return: Подготовленный HTTP-ответ для проверяемого запроса.
            """
            self.assertEqual(request.url.path, "/botunused/sendVoice")
            self.assertIn("multipart/form-data", request.headers["content-type"])
            self.assertIn(b"semyon-piano.ogg", request.content)
            self.assertIn(b"OggSvoice", request.content)
            self.assertIn(b'"message_id": 10', request.content)

            return httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await Telegram(client, "unused").send_voice(-123, 10, b"OggSvoice", 11)

        self.assertEqual(result["message_id"], 11)

    async def test_invalid_arrangement_retry_explains_the_failed_constraint(self) -> None:
        """Проверяет передачу причины ошибки при повторе аранжировки.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json("music", parameters=None)
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.gateway.compose.return_value = json.dumps(score)
        invalid = json.loads(json.dumps(self.arrangement))
        invalid["drums"][0]["beat"] = 16
        self.gateway.arrange.side_effect = [json.dumps(invalid), json.dumps(self.arrangement)]

        with patch(
            "semen_banan.audio.jobs.AudioJobRunner.render", new=AsyncMock(return_value=self.audio)
        ):
            await self.bot.handle(message("Напиши трек на 40 секунд про бананы"))

        correction = self.gateway.arrange.await_args_list[1].kwargs["correction"]
        self.assertIn("drums.beat", correction["error"])
        self.assertEqual(json.loads(correction["previous_json"]), invalid)
        self.telegram.send_voice.assert_awaited_once()
        self.assertIsNone(self.bot.memory.next_reply_due())

    async def test_arrangement_gateway_keeps_chat_persona_out_of_format_instructions(self) -> None:
        """Проверяет разделение характера и инструкции JSON-формата.

        :return: Не возвращает значение.
        """
        gateway = Gateway(AsyncMock(), self.settings)
        gateway._complete = AsyncMock(return_value=json.dumps(self.arrangement))
        correction = {"error": "drums.beat", "previous_json": "{}"}
        await gateway.arrange([], {"text": "Напиши трек"}, correction=correction)
        system, user, _ = gateway._complete.await_args.args
        self.assertNotIn("Выдай только одну свою реплику", system)
        self.assertEqual(json.loads(user)["speech_style"], gateway.persona)
        self.assertEqual(json.loads(user)["correction"], correction)

    async def test_explicit_nano_request_selects_local_composer(self) -> None:
        """Проверяет передачу выбора NanoMaestro генератору.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json(
            "music", parameters={"composer": "nanomaestro", "drums": True, "speech": True}
        )
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.gateway.compose.return_value = json.dumps(score)

        with patch(
            "semen_banan.audio.jobs.AudioJobRunner.render", new=AsyncMock(return_value=self.audio)
        ) as renderer:
            await self.bot.handle(message("Семён, сыграй через NanoMaestro"))

        renderer.assert_awaited_once_with(score, True, self.arrangement, timeout=90)
        self.telegram.send_voice.assert_awaited_once()

    async def test_piano_only_skips_arranging_and_tts(self) -> None:
        """Проверяет отключение аранжировки в режиме одного пианино.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json(
            "music", parameters={"composer": "score", "drums": False, "speech": False}
        )
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.gateway.compose.return_value = json.dumps(score)

        with patch(
            "semen_banan.audio.jobs.AudioJobRunner.render", new=AsyncMock(return_value=self.audio)
        ) as renderer:
            await self.bot.handle(message("Семён, сыграй только пианино"))

        renderer.assert_awaited_once_with(score, False, None, timeout=90)
        self.gateway.arrange.assert_not_awaited()
        self.telegram.send_voice.assert_awaited_once()

    async def test_speech_can_be_disabled_in_request(self) -> None:
        """Проверяет отключение речевой дорожки по решению модели.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json(
            "music", parameters={"composer": "score", "drums": True, "speech": False}
        )
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.gateway.compose.return_value = json.dumps(score)

        with patch(
            "semen_banan.audio.jobs.AudioJobRunner.render", new=AsyncMock(return_value=self.audio)
        ) as renderer:
            await self.bot.handle(message("Семён, сыграй без речи"))

        self.assertEqual(renderer.call_args.args[2]["speech"], [])

    async def test_failed_audio_job_is_queued_without_sending(self) -> None:
        """Проверяет повтор аудиозадания без отправки при ошибке.

        :return: Не возвращает значение.
        """
        self.gateway.classify.return_value = route_json("music", parameters=None)
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.gateway.compose.return_value = json.dumps(score)

        with patch(
            "semen_banan.audio.jobs.AudioJobRunner.render",
            new=AsyncMock(side_effect=AudioError("Генератор остановлен")),
        ):
            await self.bot.handle(message("Семён, сыграй"))

        self.telegram.send_voice.assert_not_awaited()
        self.assertIsNotNone(self.bot.memory.next_reply_due())


class LongChain(unittest.TestCase):
    """Проверки сохранения длинных цепочек диалога."""

    def test_more_than_twelve_messages_survive_restart(self) -> None:
        """Проверяет сохранение длинной цепочки диалога.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as path:
            db_path = Path(path) / "memory.sqlite3"
            store = ConversationStore(db_path)

            try:
                for number in range(1, 52):
                    m = message(f"Реплика {number}")
                    m["message_id"] = number

                    if number > 1:
                        m["reply_to_message"] = {
                            "message_id": number - 1,
                            "from": {"id": 7},
                            "text": f"Реплика {number - 1}",
                        }

                    active = store.record_incoming(m, bot_id=1, direct=number == 1)
                    self.assertTrue(active)
            finally:
                store.close()

            store = ConversationStore(db_path)

            try:
                chain = ContextBuilder(store).build(-123, 0, 50, 51)
                self.assertEqual(len(chain), 50)
                self.assertEqual(chain[0]["text"], "Реплика 1")
                self.assertEqual(chain[-1]["text"], "Реплика 50")
            finally:
                store.close()


class Music(unittest.TestCase):
    """Проверки проверки музыкальных данных."""

    def test_score_validation(self) -> None:
        """Проверяет допустимые и некорректные музыкальные партитуры.

        :return: Не возвращает значение.
        """
        score = {
            "tempo": 100,
            "melody": [{"midi": 64, "beats": 1}] * 16,
            "chords": [[48, 52, 55]] * 4,
        }
        self.assertEqual(parse_score(json.dumps(score)), score)
        score["melody"][0]["beats"] = 1000

        with self.assertRaises(ValueError):
            parse_score(json.dumps(score))


if __name__ == "__main__":
    unittest.main()

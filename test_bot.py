import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from bot import BotError, Gateway, Settings, Semyon, Telegram, trigger
from memory import ConversationStore, STYLE_CHANGE
from music import encode_voice, music_requested, parse_score, render_wav


def message(text="Семён", chat=-123, topic=0):
    return {"text": text, "chat": {"id": chat, "type": "supergroup"},
            "from": {"id": 7, "first_name": "Друг", "is_bot": False},
            "date": time.time(), "message_id": 10, "message_thread_id": topic}


class Triggers(unittest.TestCase):
    def test_names_and_bananas(self):
        for text in ["Семён!", "семен, ау", "Сеня", "🍌 @semen_bot"]:
            self.assertEqual(trigger(message(text), "semen_bot", 1), "direct")
        for text in ["бананы", "шучу бананы", "банановый", "🍌", "banana"]:
            self.assertEqual(trigger(message(text), "semen_bot", 1), "banana")
        for text in ["привет", "семена", "@semen_bot_fake", "кабанан"]:
            self.assertIsNone(trigger(message(text), "semen_bot", 1))

    def test_reply_to_bot_is_direct_without_name(self):
        m = message("ну ты даёшь")
        m["reply_to_message"] = {"from": {"id": 1, "is_bot": True}, "text": "Шутка Семёна"}
        self.assertEqual(trigger(m, "semen_bot", 1), "direct")
        m["reply_to_message"]["from"]["id"] = 2
        self.assertIsNone(trigger(m, "semen_bot", 1))


class Behavior(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings("unused", frozenset({-123}), "http://localhost", "unused")
        self.telegram = AsyncMock()
        self.gateway = AsyncMock()
        self.gateway.reply.return_value = "Банановый комитет одобряет."
        self.arrangement = {"drums": [{"midi": 36, "beat": 0, "velocity": 70}],
                            "speech": [{"beat": 0, "text": "С вами Семён."}]}
        self.gateway.arrange.return_value = json.dumps(self.arrangement)
        self.bot = Semyon(self.settings, self.telegram, self.gateway,
                          {"username": "semen_bot", "id": 1}, Path(self.temp.name) / "state.json")

    async def asyncTearDown(self):
        self.bot.memory.close()
        self.temp.cleanup()

    async def test_only_allowed_triggered_messages(self):
        await self.bot.handle(message("Привет"))
        await self.bot.handle(message(chat=-999))
        m = message(); m["from"]["is_bot"] = True
        await self.bot.handle(m)
        m = message(); m["date"] -= 180
        await self.bot.handle(m)
        self.telegram.call.assert_not_awaited()
        self.gateway.reply.assert_not_awaited()

    async def test_direct_ignores_probability_and_waits_for_cooldown(self):
        first = message()
        first["message_id"] = 10
        second = message("@semen_bot снова вопрос")
        second["message_id"] = 11
        with patch("bot.random.random", return_value=0.99):
            await self.bot.handle(first)
            await self.bot.handle(second)
        self.telegram.call.assert_awaited_once()
        self.assertIn("-123", json.loads(self.bot.state_path.read_text()))
        due = self.bot.memory.next_reply_due()
        self.assertIsNotNone(due)
        with patch("bot.time.time", return_value=due + 1):
            await self.bot.process_pending()
        self.assertEqual(self.telegram.call.await_count, 2)
        self.assertIsNone(self.bot.memory.next_reply_due())

    async def test_pending_reply_survives_restart(self):
        first = message()
        first["message_id"] = 10
        second = message("Семён, ещё вопрос")
        second["message_id"] = 11
        await self.bot.handle(first)
        await self.bot.handle(second)
        due = self.bot.memory.next_reply_due()
        self.bot.memory.close()
        self.bot = Semyon(self.settings, self.telegram, self.gateway,
                          {"username": "semen_bot", "id": 1}, Path(self.temp.name) / "state.json")
        with patch("bot.time.time", return_value=due + 1):
            await self.bot.process_pending()
        self.assertEqual(self.telegram.call.await_count, 2)
        self.assertIsNone(self.bot.memory.next_reply_due())

    async def test_banana_probability_and_no_fifteen_minute_pause(self):
        with patch("bot.random.random", return_value=0.25):
            await self.bot.handle(message("бананы"))
        self.gateway.reply.assert_not_awaited()
        with patch("bot.random.random", return_value=0.24):
            await self.bot.handle(message("бананы"))
            self.bot.last["-123"] -= 11
            await self.bot.handle(message("бананы"))
        self.assertEqual(self.telegram.call.await_count, 2)

    async def test_gateway_failure_stays_silent(self):
        self.gateway.reply.side_effect = BotError("Offline")
        await self.bot.handle(message())
        self.telegram.call.assert_not_awaited()

    async def test_reply_to_bot_passes_quoted_text_to_gateway(self):
        m = message("ну ты даёшь")
        m["reply_to_message"] = {"from": {"id": 1}, "text": "Шутка Семёна"}
        await self.bot.handle(m)
        self.assertEqual(self.gateway.reply.call_args.args[1]["in_reply_to_semyon"], "Шутка Семёна")
        self.telegram.call.assert_awaited_once()

    async def test_topic_context_isolation(self):
        await self.bot.handle(message("секрет из другой темы", topic=3))
        await self.bot.handle(message(topic=4))
        self.assertEqual(self.gateway.reply.call_args.args[0], [])
        self.assertEqual(self.telegram.call.call_args.kwargs["message_thread_id"], 4)

    async def test_gateway_contract(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(body["model"], "openclaw/semyon")
            self.assertEqual(body["tool_choice"], "none")
            self.assertNotIn("user", body)
            return httpx.Response(200, json={"choices": [{"message": {"content": "банан"}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await Gateway(client, self.settings).reply([], {"text": "Семён"})
            self.assertEqual(result, "банан")

    async def test_reply_chain_continues_through_other_people(self):
        self.telegram.call.return_value = {"message_id": 1000}
        first = message("Семён, начни шутку")
        first["message_id"] = 10
        await self.bot.handle(first)
        self.bot.last["-123"] -= 11
        second = message("Ну ты даёшь")
        second["message_id"] = 11
        second["reply_to_message"] = {"message_id": 1000, "from": {"id": 1}, "text": "Банановый комитет одобряет."}
        self.telegram.call.return_value = {"message_id": 1001}
        await self.bot.handle(second)
        self.bot.last["-123"] -= 11
        third = message("А я согласен")
        third["message_id"] = 12
        third["reply_to_message"] = {"message_id": 11, "from": {"id": 7}, "text": "Ну ты даёшь"}
        await self.bot.handle(third)
        self.assertEqual(self.telegram.call.await_count, 3)
        chain = self.gateway.reply.call_args.args[0]
        self.assertEqual([x["text"] for x in chain], [
            "Семён, начни шутку", "Банановый комитет одобряет.", "Ну ты даёшь"])

    async def test_character_request_persists_across_restart(self):
        first = message("Семён, поменяй характер: будь добрее")
        first["message_id"] = 10
        await self.bot.handle(first)
        self.assertTrue(STYLE_CHANGE.search(first["text"]))
        self.assertEqual(self.gateway.reply.call_args.args[2], [first["text"]])
        self.bot.memory.close()
        self.bot = Semyon(self.settings, self.telegram, self.gateway,
                          {"username": "semen_bot", "id": 1}, Path(self.temp.name) / "state.json")
        self.bot.last["-123"] -= 11
        second = message("Семён, как дела?")
        second["message_id"] = 11
        await self.bot.handle(second)
        self.assertEqual(self.gateway.reply.call_args.args[2], [first["text"]])

    async def test_style_request_without_name_is_actionable(self):
        m = message("нужно поменять характер: стань более веселым")
        m["message_id"] = 42
        await self.bot.handle(m)
        self.telegram.call.assert_awaited_once()
        self.assertEqual(self.gateway.reply.call_args.args[2], [m["text"]])

    async def test_music_request_routes_to_voice_without_name(self):
        score = {"tempo": 100, "melody": [{"midi": 64, "beats": 1}] * 16,
                 "chords": [[48, 52, 55]] * 4}
        self.gateway.compose.return_value = json.dumps(score)
        self.telegram.send_voice.return_value = {"message_id": 1000}
        with patch("bot.make_song", return_value=(b"RIFF", 11)), \
             patch("bot.encode_voice", return_value=b"OggSvoice"):
            await self.bot.handle(message("сыграй на пианино что-нибудь"))
        self.gateway.reply.assert_not_awaited()
        self.gateway.compose.assert_awaited_once()
        self.telegram.send_voice.assert_awaited_once_with(-123, 10, b"OggSvoice", 11, 0)
        self.assertIsNotNone(self.bot.memory.get(-123, 1000))

    async def test_voice_upload_is_multipart_and_replies_to_request(self):
        def handler(request):
            self.assertEqual(request.url.path, "/botunused/sendVoice")
            self.assertIn("multipart/form-data", request.headers["content-type"])
            self.assertIn(b"semyon-piano.ogg", request.content)
            self.assertIn(b"OggSvoice", request.content)
            self.assertIn(b'"message_id": 10', request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await Telegram(client, "unused").send_voice(-123, 10, b"OggSvoice", 11)
        self.assertEqual(result["message_id"], 11)

    async def test_explicit_nano_request_selects_local_composer(self):
        score = {"tempo": 100, "melody": [{"midi": 64, "beats": 1}] * 16,
                 "chords": [[48, 52, 55]] * 4}
        self.gateway.compose.return_value = json.dumps(score)
        with patch("bot.make_song", return_value=(b"RIFF", 11)) as renderer, \
             patch("bot.encode_voice", return_value=b"OggSvoice"):
            await self.bot.handle(message("Семён, сыграй через NanoMaestro"))
        renderer.assert_called_once_with(score, True, self.arrangement)
        self.telegram.send_voice.assert_awaited_once()

    async def test_piano_only_skips_arranging_and_tts(self):
        score = {"tempo": 100, "melody": [{"midi": 64, "beats": 1}] * 16,
                 "chords": [[48, 52, 55]] * 4}
        self.gateway.compose.return_value = json.dumps(score)
        with patch("bot.make_piano", return_value=(b"RIFF", 11)), \
             patch("bot.encode_voice", return_value=b"OggSvoice"):
            await self.bot.handle(message("Семён, сыграй только пианино"))
        self.gateway.arrange.assert_not_awaited()
        self.telegram.send_voice.assert_awaited_once()

    async def test_speech_can_be_disabled_in_request(self):
        score = {"tempo": 100, "melody": [{"midi": 64, "beats": 1}] * 16,
                 "chords": [[48, 52, 55]] * 4}
        self.gateway.compose.return_value = json.dumps(score)
        with patch("bot.make_song", return_value=(b"RIFF", 11)) as renderer, \
             patch("bot.encode_voice", return_value=b"OggSvoice"):
            await self.bot.handle(message("Семён, сыграй без речи"))
        self.assertEqual(renderer.call_args.args[2]["speech"], [])


class LongChain(unittest.TestCase):
    def test_more_than_twelve_messages_survive_restart(self):
        with tempfile.TemporaryDirectory() as path:
            db_path = Path(path) / "memory.sqlite3"
            store = ConversationStore(db_path)
            try:
                for number in range(1, 52):
                    m = message(f"Реплика {number}")
                    m["message_id"] = number
                    if number > 1:
                        m["reply_to_message"] = {
                            "message_id": number - 1, "from": {"id": 7}, "text": f"Реплика {number - 1}"}
                    active = store.record_incoming(m, bot_id=1, direct=number == 1)
                    self.assertTrue(active)
            finally:
                store.close()
            store = ConversationStore(db_path)
            try:
                chain = store.context(-123, 0, 50, 51)
                self.assertEqual(len(chain), 50)
                self.assertEqual(chain[0]["text"], "Реплика 1")
                self.assertEqual(chain[-1]["text"], "Реплика 50")
            finally:
                store.close()


class Music(unittest.TestCase):
    def test_music_intent_and_validation(self):
        self.assertTrue(music_requested("Семён, сыграй что-нибудь"))
        self.assertTrue(music_requested("сочини мелодию про бананы"))
        self.assertFalse(music_requested("Семён, сочини письмо на английском"))
        self.assertFalse(music_requested("не сыграй, пожалуйста"))
        score = {"tempo": 100, "melody": [{"midi": 64, "beats": 1}] * 16,
                 "chords": [[48, 52, 55]] * 4}
        self.assertEqual(parse_score(json.dumps(score)), score)
        score["melody"][0]["beats"] = 1000
        with self.assertRaises(ValueError):
            parse_score(json.dumps(score))

    def test_render_and_encode_voice(self):
        score = {"tempo": 100, "melody": [{"midi": 64, "beats": 1}] * 16,
                 "chords": [[48, 52, 55]] * 4}
        wav, duration = render_wav(score)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertEqual(duration, 10)
        self.assertTrue(encode_voice(wav).startswith(b"OggS"))


if __name__ == "__main__":
    unittest.main()

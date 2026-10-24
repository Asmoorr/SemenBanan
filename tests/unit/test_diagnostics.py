from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from semen_banan.audio.jobs import AudioError
from semen_banan.audio.models import AudioResult
from semen_banan.bootstrap import run
from semen_banan.config import AppPaths, Settings
from semen_banan.errors import BotError


class Diagnostics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch("semen_banan.bootstrap.AppPaths.load", return_value=AppPaths(self.home))
        )
        self.stack.enter_context(
            patch(
                "semen_banan.bootstrap.Settings.load",
                return_value=Settings("", frozenset(), "http://localhost", ""),
            )
        )
        self.stack.enter_context(
            patch("semen_banan.bootstrap.httpx.AsyncClient", return_value=AsyncMock())
        )
        self.gateway = self.stack.enter_context(
            patch("semen_banan.bootstrap.OpenClawClient", return_value=AsyncMock())
        ).return_value
        self.gateway.compose.return_value = json.dumps(
            {
                "tempo": 100,
                "melody": [{"midi": 64, "beats": 1}] * 16,
                "chords": [[48, 52, 55]] * 4,
            }
        )
        self.gateway.arrange.return_value = '{"drums":[{"midi":36,"beat":0,"velocity":70}],"speech":[{"beat":0,"text":"Бананы в студию."}]}'
        self.audio = self.stack.enter_context(
            patch("semen_banan.audio.jobs.AudioJobRunner.render", new_callable=AsyncMock)
        )
        self.audio.return_value = AudioResult(b"OggSpreview", 12, 123)
        self.telegram = self.stack.enter_context(patch("semen_banan.bootstrap.TelegramClient"))
        self.storage = self.stack.enter_context(
            patch("semen_banan.bootstrap.SqliteConversationStore")
        )
        self.stack.enter_context(patch("sys.stdout", new=io.StringIO()))

    async def test_music_check_generates_full_mix_without_telegram_or_state(self):
        await run("check-music")
        self.assertEqual((self.home / ".runtime/checks/music.ogg").read_bytes(), b"OggSpreview")
        score, use_nano, arrangement = self.audio.await_args.args
        self.assertEqual(score["tempo"], 100)
        self.assertFalse(use_nano)
        self.assertTrue(arrangement["drums"])
        self.assertTrue(arrangement["speech"])
        self.telegram.assert_not_called()
        self.storage.assert_not_called()
        self.assertFalse((self.home / "state.json").exists())

    async def test_music_check_can_select_nano_and_custom_output(self):
        destination = self.home / "preview/nano.ogg"
        await run("check-music", destination, "Сыграй через NanoMaestro без речи")
        self.assertTrue(destination.exists())
        self.assertTrue(self.audio.await_args.args[1])
        self.assertEqual(self.audio.await_args.args[2]["speech"], [])
        self.telegram.assert_not_called()

    async def test_failed_music_check_does_not_write_preview(self):
        self.audio.side_effect = AudioError("Timeout")
        with self.assertRaises(BotError):
            await run("check-music")
        self.assertFalse((self.home / ".runtime/checks/music.ogg").exists())
        self.telegram.assert_not_called()

    async def test_gateway_check_does_not_render_music_or_open_telegram(self):
        self.gateway.reply.return_value = "Банан"
        await run("check-gateway")
        self.gateway.reply.assert_awaited_once()
        self.audio.assert_not_awaited()
        self.telegram.assert_not_called()

    async def test_invalid_notes_stop_before_worker_after_two_attempts(self):
        self.gateway.compose.return_value = "not a score"
        with self.assertRaises(BotError):
            await run("check-music")
        self.assertEqual(self.gateway.compose.await_count, 2)
        self.gateway.arrange.assert_not_awaited()
        self.audio.assert_not_awaited()

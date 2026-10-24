from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from semen_banan.audio.jobs import AudioJobRunner
from semen_banan.audio.mixing import _decode
from semen_banan.config import AppPaths


@unittest.skipUnless(
    Path("assets/speech/silero-v5_6-ru.pt").exists() and importlib.util.find_spec("torch"),
    "Нет локальной модели речи",
)
class SpokenReply(unittest.IsolatedAsyncioTestCase):
    """Проверка настоящего голосового без музыки в отдельном процессе."""

    async def test_local_speech_reply(self) -> None:
        """Возвращает готовый OGG/Opus с правильной длительностью.

        :return: Не возвращает значение.
        """
        result = await AudioJobRunner(AppPaths.load()).speak(
            "Семён записывает короткую реплику без музыки"
        )
        self.assertTrue(result.voice.startswith(b"OggS"))
        samples = _decode(result.voice)
        self.assertGreater(float(abs(samples).max()), 0.01)
        self.assertLessEqual(abs(len(samples) / 48000 - result.duration), 1)

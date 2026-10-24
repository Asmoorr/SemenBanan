from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np

from semen_banan.audio.mixing import _decode
from semen_banan.audio.speech import synthesize_speech
from semen_banan.audio.voice_settings import VoiceSettings


@unittest.skipUnless(
    Path("assets/speech/silero-v5_6-ru.pt").exists() and importlib.util.find_spec("torch"),
    "Нет модели Silero или PyTorch",
)
class SileroSpeech(unittest.TestCase):
    """Проверка локального синтеза и обработки новых голосов."""

    def test_voice_catalog_and_speed(self) -> None:
        """Проверяет все голоса, длительность и работу скорости с высотой.

        :return: Не возвращает значение.
        """
        text = "Семён выходит на сцену."
        for speaker in ("eugene", "aidar", "baya", "kseniya", "xenia"):
            with self.subTest(speaker=speaker):
                audio = _decode(synthesize_speech(text, VoiceSettings(voice=speaker)))
                self.assertTrue(np.isfinite(audio).all())
                self.assertGreater(float(np.abs(audio).max()), 0.01)
        slow = _decode(synthesize_speech(text, VoiceSettings(speed=0.75, pitch_semitones=-3)))
        fast = _decode(synthesize_speech(text, VoiceSettings(speed=1.5, pitch_semitones=-3)))
        self.assertGreater(len(slow), len(fast) * 1.5)

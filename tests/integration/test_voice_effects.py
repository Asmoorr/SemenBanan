from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from semen_banan.audio.mixing import RATE, _decode, _wav
from semen_banan.audio.speech import apply_voice_effects, synthesize_speech
from semen_banan.audio.voice_settings import VoiceEffect, VoiceSettings


class VoiceEffects(unittest.TestCase):
    """Проверка реальной локальной обработки речи и эффектов."""

    def test_all_effects_and_pitch(self) -> None:
        """Проверяет доступность фильтров, изменение сигнала и сохранение длины высоты.

        :return: Не возвращает значение.
        """
        timeline = np.arange(RATE, dtype=np.float32) / RATE
        samples = 0.2 * np.sin(2 * np.pi * 220 * timeline)
        original = _wav(np.column_stack((samples, samples)))
        self.assertEqual(apply_voice_effects(original, VoiceSettings()), original)
        self.assertEqual(
            apply_voice_effects(original, VoiceSettings(effect=VoiceEffect.ECHO, effect_amount=0)),
            original,
        )
        for effect in VoiceEffect:
            with self.subTest(effect=effect):
                result = _decode(
                    apply_voice_effects(original, VoiceSettings(pitch_semitones=3, effect=effect))
                )
                self.assertTrue(np.isfinite(result).all())
                self.assertGreater(float(abs(result).max()), 0.01)
                self.assertGreater(len(result), RATE * 0.9)
                self.assertLess(len(result), RATE * 2)
                self.assertFalse(
                    np.allclose(result[: RATE // 2, 0], samples[: RATE // 2], atol=0.001)
                )

    @unittest.skipUnless(Path("assets/speech/denis.onnx").exists(), "Нет локального голоса")
    def test_piper_speed_and_effect(self) -> None:
        """Проверяет скорость синтеза и обработку настоящей русской речи.

        :return: Не возвращает значение.
        """
        text = "Семён проверяет голос."
        slow = _decode(synthesize_speech(text, VoiceSettings(voice="denis", speed=0.75)))
        fast = _decode(synthesize_speech(text, VoiceSettings(voice="denis", speed=1.5)))
        processed = _decode(
            synthesize_speech(text, VoiceSettings(voice="denis", effect=VoiceEffect.ROBOT))
        )
        self.assertGreater(len(slow), len(fast) * 1.2)
        self.assertGreater(float(abs(processed).max()), 0.01)

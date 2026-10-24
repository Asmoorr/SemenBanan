from __future__ import annotations

import unittest

import numpy as np

from semen_banan.audio.customization import AudioCustomization, Instrument
from semen_banan.audio.mixing import (
    RATE,
    _decode,
    _wav,
    mix_custom_tracks,
    mix_tracks,
    speech_ducking_envelope,
)


class MixingBalance(unittest.TestCase):
    """Контроль сохранения инструментала при появлении речи."""

    def test_instrument_and_drum_attenuation(self) -> None:
        """Проверяет фактическое приглушение в обоих вариантах сведения.

        :return: Не возвращает значение.
        """
        samples = np.zeros((RATE * 2, 2), dtype=np.float32)
        samples[:, 0] = 0.1
        voice = np.zeros_like(samples)
        voice[:, 1] = 0.08
        instrument = _wav(samples)
        speech = _wav(voice)
        silence = _wav(np.zeros_like(samples))
        for custom in (False, True):
            for drums_only, expected_ratio in ((False, 0.8), (True, 0.9)):
                with self.subTest(custom=custom, drums=drums_only):
                    if custom:
                        instruments = {Instrument.PIANO: silence if drums_only else instrument}
                        drums = instrument if drums_only else silence
                        baseline = mix_custom_tracks(
                            instruments, drums, None, AudioCustomization()
                        )[0]
                        mixed = mix_custom_tracks(instruments, drums, speech, AudioCustomization())[
                            0
                        ]
                    else:
                        piano = silence if drums_only else instrument
                        drums = instrument if drums_only else silence
                        baseline = mix_tracks(piano, drums, silence)[0]
                        mixed = mix_tracks(piano, drums, speech)[0]
                    baseline_level = float(np.mean(_decode(baseline)[RATE // 2 : RATE, 0]))
                    mixed_level = float(np.mean(_decode(mixed)[RATE // 2 : RATE, 0]))
                    self.assertAlmostEqual(
                        mixed_level / baseline_level, expected_ratio, delta=0.002
                    )

    def test_silence_short_audio_and_quiet_voice(self) -> None:
        """Проверяет отсутствие приглушения в тишине и мягкую реакцию на тихую речь.

        :return: Не возвращает значение.
        """
        silence = np.zeros((64, 2), dtype=np.float32)
        envelope = speech_ducking_envelope(silence)
        self.assertEqual(envelope.shape, (64, 1))
        self.assertEqual(float(envelope.max()), 0)
        quiet = speech_ducking_envelope(np.full((RATE, 2), 0.012, dtype=np.float32))
        loud = speech_ducking_envelope(np.full((RATE, 2), 0.08, dtype=np.float32))
        self.assertLess(float(quiet.max()), float(loud.max()) / 2)

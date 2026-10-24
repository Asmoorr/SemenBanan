from __future__ import annotations

import importlib.util
import unittest

from semen_banan.audio.customization import AudioCustomization, Instrument
from semen_banan.audio.jobs import AudioJobRunner
from semen_banan.config import AppPaths
from tests.integration.test_piano import score


class CustomAudio(unittest.IsolatedAsyncioTestCase):
    """Сквозные проверки длительности, инструментов и громкости через отдельный процесс."""

    @unittest.skipUnless(
        (AppPaths.load().assets / "GeneralUser-GS.sf2").exists()
        and importlib.util.find_spec("numpy"),
        "Нужны музыкальные ресурсы",
    )
    async def test_sixty_second_four_instrument_recording(self) -> None:
        """Проверяет верхнюю границу длительности, четыре тембра и длинную аранжировку.

        :return: Не возвращает значение.
        """
        from semen_banan.audio.mixing import RATE, _decode

        settings = AudioCustomization(
            60,
            180,
            (Instrument.GUITAR, Instrument.BASS, Instrument.STRINGS, Instrument.SYNTH),
            {"guitar": 80, "bass": 50, "strings": 30, "synth": 20, "drums": 40},
        )
        arrangement = {"drums": [{"midi": 36, "beat": 0, "velocity": 70}], "speech": []}
        result = await AudioJobRunner(AppPaths.load(), seed=42).render(
            score(), arrangement=arrangement, customization=settings
        )
        samples = _decode(result.voice)
        self.assertEqual(result.duration, 60)
        self.assertEqual(len(samples), 60 * RATE)
        self.assertGreater(float(abs(samples[-RATE:]).max()), 0.001)

    @unittest.skipUnless(
        (AppPaths.load().assets / "GeneralUser-GS.sf2").exists(), "Нужны музыкальные ресурсы"
    )
    async def test_master_mute_and_exact_short_duration(self) -> None:
        """Проверяет минимальную длительность и сохранение общей нулевой громкости после кодирования.

        :return: Не возвращает значение.
        """
        from semen_banan.audio.mixing import RATE, _decode

        result = await AudioJobRunner(AppPaths.load()).render(
            score(),
            customization=AudioCustomization(5, 60, (Instrument.ELECTRIC_PIANO,), {"master": 0}),
        )
        samples = _decode(result.voice)
        self.assertEqual(len(samples), 5 * RATE)
        self.assertEqual(result.duration, 5)
        self.assertLess(float(abs(samples).max()), 0.0001)

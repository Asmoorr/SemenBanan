from __future__ import annotations

import io
import unittest
import wave

from semen_banan.audio.composers import local_composer, score_notes
from semen_banan.audio.models import Score
from semen_banan.audio.rendering import render_piano
from semen_banan.config import AppPaths

ASSETS = AppPaths.load().assets


def score() -> Score:
    """Создаёт воспроизводимую партитуру для аудиопроверок.

    :return: Партитура из четырёх тактов.
    """
    return {
        "tempo": 100,
        "melody": [
            {"midi": n, "beats": 1}
            for n in [64, 67, 69, 67, 65, 69, 72, 69, 64, 67, 71, 67, 62, 65, 67, 60]
        ],
        "chords": [[48, 52, 55], [53, 57, 60], [48, 52, 55], [43, 47, 50]],
    }


class Piano(unittest.TestCase):
    """Проверки композитора и озвучивания пианино."""

    @unittest.skipUnless(
        (ASSETS / "GeneralUser-GS.sf2").exists(),
        "Run tools/setup_assets.py for audio integration tests",
    )
    def test_soundfont_renders_non_silent_audio(self) -> None:
        """Проверяет озвучивание нот установленным звуковым банком.

        :return: Не возвращает значение.
        """
        audio, duration = render_piano(score_notes(score()), 100)

        with wave.open(io.BytesIO(audio)) as wav:
            self.assertEqual(wav.getframerate(), 48000)
            self.assertEqual(wav.getnchannels(), 2)
            self.assertGreater(len(set(wav.readframes(wav.getnframes()))), 100)

        self.assertGreaterEqual(duration, 9)
        self.assertLess(duration, 20)

    @unittest.skipUnless(
        (ASSETS / "nanomaestro/model.onnx").exists(),
        "Run tools/setup_assets.py for model integration tests",
    )
    def test_local_model_generates_beyond_primer_with_bounded_notes(self) -> None:
        """Проверяет продолжение начального такта и границы нот.

        :return: Не возвращает значение.
        """
        notes = local_composer().compose(score(), seed=42)
        self.assertTrue(any(n["start"] >= 12 for n in notes))
        self.assertTrue(all(21 <= n["midi"] <= 108 for n in notes))
        self.assertTrue(all(0 <= n["start"] < 16 and 0 < n["beats"] <= 4 for n in notes))

    @unittest.skipUnless(
        (ASSETS / "nanomaestro/model.onnx").exists(),
        "Run tools/setup_assets.py for model integration tests",
    )
    def test_sixteen_bars_are_generated_and_rendered(self) -> None:
        """Проверяет генерацию и озвучивание шестнадцати тактов.

        :return: Не возвращает значение.
        """
        notes = local_composer().compose(score(), seed=42, bars=16)
        self.assertTrue(any(n["start"] >= 60 for n in notes))
        self.assertTrue(all(0 <= n["start"] < 64 and n["start"] + n["beats"] <= 64 for n in notes))
        audio, duration = render_piano(notes, 110)
        self.assertGreaterEqual(duration, 34)
        self.assertLess(duration, 45)


if __name__ == "__main__":
    unittest.main()

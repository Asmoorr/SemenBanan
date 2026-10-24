from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from semen_banan.audio.types import AudioSamples

import io
import json
import unittest
import wave

from semen_banan.audio.mixing import mix_tracks
from semen_banan.audio.speech import synthesize_speech
from semen_banan.audio.validation import parse_arrangement
from semen_banan.config import AppPaths

ASSETS = AppPaths.load().assets


class Arrangement(unittest.TestCase):
    """Проверки аранжировки и сведения дорожек."""

    def test_music_is_lower_during_speech(self) -> None:
        """Проверяет мягкое приглушение музыки без провала на участках речи.

        :return: Не возвращает значение.
        """
        import numpy as np

        rate = 48000
        t = np.arange(rate * 4) / rate
        piano = 0.08 * np.sin(2 * np.pi * 440 * t)
        speech = 0.15 * np.sin(2 * np.pi * 880 * t) * ((t >= 1) & (t < 3))

        def wav_bytes(samples: AudioSamples) -> bytes:
            """Создаёт WAV из тестового массива сэмплов.

            :param samples: Массив сэмплов аудиодорожки.
            :return: Байты тестовой WAV-дорожки.
            """
            out = io.BytesIO()

            with wave.open(out, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes((samples * 32767).astype("<i2").tobytes())

            return out.getvalue()

        mixed, _ = mix_tracks(wav_bytes(piano), wav_bytes(np.zeros_like(t)), wav_bytes(speech))

        with wave.open(io.BytesIO(mixed)) as wav:
            samples = (
                np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2)[:, 0]
                / 32767
            )

        def piano_amplitude(start: float, end: float) -> float:
            """Измеряет среднюю амплитуду инструментов на участке записи.

            :param start: Начало участка записи в секундах.
            :param end: Конец участка записи в секундах.
            :return: Оценка громкости выбранного участка.
            """
            sl = slice(round(start * rate), round(end * rate))

            return abs(2 * np.mean(samples[sl] * np.sin(2 * np.pi * 440 * t[sl])))

        instrumental_ratio = piano_amplitude(1.5, 2.5) / piano_amplitude(0.2, 0.7)
        self.assertGreater(instrumental_ratio, 0.75)
        self.assertLess(instrumental_ratio, 0.95)

    def test_rejects_unbounded_patterns_and_speech(self) -> None:
        """Проверяет ограничения барабанного рисунка и речи.

        :return: Не возвращает значение.
        """
        data = {
            "drums": [{"midi": 36, "beat": 0, "velocity": 70}],
            "speech": [{"beat": 0, "text": "Привет, бананы!"}],
        }
        self.assertEqual(parse_arrangement(json.dumps(data)), data)
        data["drums"][0]["beat"] = 4

        with self.assertRaises(RuntimeError):
            parse_arrangement(json.dumps(data))

        data["drums"][0]["beat"] = 0
        data["speech"][0]["text"] = "x" * 1000

        with self.assertRaises(RuntimeError):
            parse_arrangement(json.dumps(data))

    @unittest.skipUnless(
        (ASSETS / "speech/silero-v5_6-ru.pt").exists(),
        "Run tools/setup_assets.py for TTS integration tests",
    )
    def test_russian_tts_and_mix_render_without_clipping(self) -> None:
        """Проверяет синтез русской речи и сведение без перегрузки.

        :return: Не возвращает значение.
        """
        import numpy as np

        speech = synthesize_speech("С вами Семён. Бананы на месте.")

        with wave.open(io.BytesIO(speech)) as wav:
            self.assertEqual(wav.getframerate(), 48000)
            self.assertGreater(wav.getnframes(), wav.getframerate())

        mixed, duration = mix_tracks(speech, speech, speech)

        with wave.open(io.BytesIO(mixed)) as wav:
            self.assertEqual(wav.getnchannels(), 2)
            self.assertEqual(wav.getframerate(), 48000)
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")

        self.assertGreater(duration, 1)
        self.assertGreater(float(np.std(samples)), 100)
        self.assertLess(int(np.abs(samples.astype(np.int32)).max()), 32767)

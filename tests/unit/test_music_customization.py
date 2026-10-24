from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from semen_banan.audio.customization import AudioCustomization, Instrument
from semen_banan.audio.models import AudioResult
from semen_banan.audio.pipeline import bass_notes, extend_notes
from semen_banan.config import Settings
from semen_banan.conversation.routing import RouteDecision
from semen_banan.generation.service import MusicGenerator, MusicReply
from tests.fixtures import route_json
from tests.integration.test_piano import score
from tests.unit.test_bot import create_service, message


class MusicParameterValidation(unittest.TestCase):
    """Проверки точных музыкальных параметров и совместимости очереди."""

    def test_rejects_unsafe_values(self) -> None:
        """Проверяет диапазоны, типы, неизвестные инструменты и дорожки.

        :return: Не возвращает значение.
        """
        for payload in (
            {"duration_seconds": True},
            {"duration_seconds": 61},
            {"duration_seconds": 4},
            {"tempo_bpm": 59},
            {"tempo_bpm": 181},
            {"tempo_bpm": float("nan")},
            {"instruments": []},
            {"instruments": ["piano", "piano"]},
            {"instruments": ["unknown"]},
            {"volumes": {"piano": -1}},
            {"volumes": {"master": 101}},
            {"volumes": {"speech": False}},
            {"volumes": {"shell": 10}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                AudioCustomization.parse(payload)

    def test_legacy_and_new_decisions_roundtrip(self) -> None:
        """Проверяет старый формат и сохранение полного набора параметров.

        :return: Не возвращает значение.
        """
        self.assertTrue(RouteDecision.parse(route_json("music")).music.customization.is_default)
        parameters = {
            "composer": "nanomaestro",
            "drums": True,
            "speech": False,
            "duration_seconds": 30,
            "tempo_bpm": 80,
            "instruments": ["guitar", "bass"],
            "volumes": {"bass": 40, "master": 70},
        }
        decision = RouteDecision.parse(route_json("music", parameters=parameters))
        self.assertEqual(RouteDecision.parse(json.dumps(decision.to_payload())), decision)
        self.assertEqual(decision.music.customization.duration_seconds, 30)

    def test_expansion_covers_long_recording_without_out_of_bounds_notes(self) -> None:
        """Проверяет разворачивание фразы и низкую партию баса.

        :return: Не возвращает значение.
        """
        from semen_banan.audio.composers import score_notes

        notes = extend_notes(score_notes(score()), 180)
        self.assertTrue(any(note["start"] >= 176 for note in notes))
        self.assertTrue(all(note["start"] + note["beats"] <= 180 for note in notes))
        bass = bass_notes(notes)
        self.assertTrue(all(note["midi"] <= 48 for note in bass))
        self.assertEqual(len({note["start"] for note in bass}), len(bass))

    def test_track_volumes_survive_mixing_without_automatic_makeup_gain(self) -> None:
        """Проверяет заданную длину и пропорциональное уменьшение громкости дорожки.

        :return: Не возвращает значение.
        """
        import numpy as np

        from semen_banan.audio.mixing import RATE, _decode, _wav, mix_custom_tracks

        samples = np.full((RATE * 2, 2), 0.1, dtype=np.float32)
        audio = _wav(samples)
        loud, duration = mix_custom_tracks(
            {Instrument.GUITAR: audio},
            None,
            None,
            AudioCustomization(5, instruments=(Instrument.GUITAR,)),
        )
        quiet, _ = mix_custom_tracks(
            {Instrument.GUITAR: audio},
            None,
            None,
            AudioCustomization(5, instruments=(Instrument.GUITAR,), volumes={"guitar": 50}),
        )
        loud_samples, quiet_samples = _decode(loud), _decode(quiet)
        self.assertEqual(len(loud_samples), 5 * RATE)
        self.assertEqual(duration, 5)
        ratio = np.abs(quiet_samples[:RATE]).mean() / np.abs(loud_samples[:RATE]).mean()
        self.assertAlmostEqual(float(ratio), 0.5, delta=0.01)


class MusicParameterFlow(unittest.IsolatedAsyncioTestCase):
    """Проверки применения параметров и их сохранения после перезапуска."""

    async def test_tempo_overrides_model_score_and_duration_reaches_worker(self) -> None:
        """Проверяет фактический темп и длину аранжировки независимо от ответа композитора.

        :return: Не возвращает значение.
        """
        gateway = AsyncMock()
        gateway.compose.return_value = json.dumps(score())
        gateway.arrange.return_value = '{"drums":[{"midi":36,"beat":0,"velocity":70}],"speech":[{"beat":40,"text":"Проверка"}]}'
        audio = AsyncMock()
        audio.render.return_value = AudioResult(b"OggS", 30, 1)
        decision = RouteDecision.parse(
            route_json(
                "music",
                parameters={
                    "composer": "score",
                    "drums": True,
                    "speech": True,
                    "tempo_bpm": 180,
                    "duration_seconds": 30,
                    "instruments": ["guitar"],
                    "volumes": {"speech": 50},
                },
            )
        )
        await MusicGenerator(gateway, audio, 90).generate(
            [], {"name": "Тест", "text": "Музыка"}, options=decision.music
        )
        self.assertEqual(audio.render.await_args.args[0]["tempo"], 180)
        self.assertEqual(audio.render.await_args.kwargs["customization"].duration_seconds, 30)
        self.assertEqual(gateway.arrange.await_args.kwargs["beats"], 92)

    async def test_custom_parameters_survive_restart_without_reclassification(self) -> None:
        """Проверяет восстановление всех точных параметров из SQLite-очереди.

        :return: Не возвращает значение.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            settings = Settings("unused", frozenset({-123}), "http://localhost", "unused")
            gateway, telegram = AsyncMock(), AsyncMock()
            gateway.classify.return_value = route_json(
                "music",
                parameters={
                    "composer": "score",
                    "drums": False,
                    "speech": False,
                    "duration_seconds": 30,
                    "tempo_bpm": 80,
                    "instruments": ["guitar", "bass"],
                    "volumes": {"bass": 40},
                },
            )
            bot = create_service(
                settings, telegram, gateway, {"id": 1, "username": "semen_bot"}, path
            )
            bot.last["-123"] = time.time()
            await bot.handle(message())
            due = bot.memory.next_reply_due()
            bot.memory.close()
            bot = create_service(
                settings, telegram, gateway, {"id": 1, "username": "semen_bot"}, path
            )
            try:
                gateway.classify.side_effect = AssertionError("Повторная классификация")
                bot.music.generate = AsyncMock(
                    return_value=MusicReply(AudioResult(b"OggS", 30, 1), "Музыка")
                )
                with patch("semen_banan.conversation.service.time.time", return_value=due + 1):
                    await bot.process_pending()
                parameters = bot.music.generate.await_args.kwargs["options"].customization
                self.assertEqual(parameters.instruments, (Instrument.GUITAR, Instrument.BASS))
                self.assertEqual(parameters.tempo_bpm, 80)
                self.assertEqual(parameters.volumes, {"bass": 40})
                self.assertEqual(gateway.classify.await_count, 1)
            finally:
                bot.memory.close()


class DisabledArrangement(unittest.IsolatedAsyncioTestCase):
    """Проверки пустых массивов для явно отключённых дорожек."""

    async def test_disabled_speech_accepts_empty_speech_without_retry(self) -> None:
        """Проверяет музыкальную просьбу без речи при непустых барабанах.

        :return: Не возвращает значение.
        """
        gateway, audio = AsyncMock(), AsyncMock()
        gateway.compose.return_value = json.dumps(score())
        gateway.arrange.return_value = '{"drums":[{"midi":36,"beat":0,"velocity":70}],"speech":[]}'
        audio.render.return_value = AudioResult(b"OggS", 30, 1)
        decision = RouteDecision.parse(
            route_json(
                "music",
                parameters={
                    "composer": "score",
                    "drums": True,
                    "speech": False,
                    "duration_seconds": 30,
                },
            )
        )
        await MusicGenerator(gateway, audio, 90).generate(
            [], {"name": "Тест", "text": "Без речи"}, options=decision.music
        )
        gateway.arrange.assert_awaited_once()
        self.assertEqual(audio.render.await_args.args[2]["speech"], [])

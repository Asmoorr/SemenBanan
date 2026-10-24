from __future__ import annotations

import json
import unittest

from semen_banan.audio.customization import AudioCustomization
from semen_banan.audio.voice_settings import VoiceEffect, VoiceSettings
from semen_banan.conversation.routing import RouteDecision
from tests.fixtures import route_json


class VoiceSettingsValidation(unittest.TestCase):
    """Проверка границ параметров голоса и сохранения настроек."""

    def test_invalid_parameters(self) -> None:
        """Отклоняет небезопасные и неподдерживаемые значения.

        :return: Не возвращает значение.
        """
        for payload in (
            {"voice": "unknown"},
            {"speed": True},
            {"speed": 0.1},
            {"speed": float("nan")},
            {"pitch_semitones": 7},
            {"effect": "unknown"},
            {"effect_amount": 101},
            {"effect_amount": False},
            {"path": "voice.onnx"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                VoiceSettings.parse(payload)

    def test_route_and_worker_roundtrip(self) -> None:
        """Сохраняет настройки через формат очереди и отдельного процесса.

        :return: Не возвращает значение.
        """
        parameters = {
            "composer": "score",
            "drums": True,
            "speech": True,
            "voice_settings": {
                "voice": "denis",
                "speed": 0.8,
                "pitch_semitones": -3,
                "effect": "echo",
                "effect_amount": 25,
            },
        }
        decision = RouteDecision.parse(route_json("music", parameters=parameters))
        restored = RouteDecision.parse(json.dumps(decision.to_payload()))
        self.assertEqual(decision, restored)
        self.assertEqual(restored.music.customization.voice_settings.effect, VoiceEffect.ECHO)
        customization = restored.music.customization
        self.assertEqual(AudioCustomization.parse(customization.to_payload()), customization)
        self.assertTrue(AudioCustomization.parse({}).is_default)

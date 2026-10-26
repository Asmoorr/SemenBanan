from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from unittest.mock import AsyncMock

from semen_banan.config import Settings
from semen_banan.errors import BotError
from semen_banan.generation.prompts import PromptCatalog, load_prompts
from semen_banan.integrations.openclaw import OpenClawClient


class PromptConfiguration(unittest.TestCase):
    """Проверки настройки и подстановок промптов."""

    def test_arrangement_substitutes_duration_without_corrupting_json(self) -> None:
        """Проверяет подстановку длительности без повреждения JSON-примера.

        :return: Не возвращает значение.
        """
        prompts = load_prompts()
        short_prompt = prompts.arrangement(16)
        long_prompt = prompts.arrangement(64)
        self.assertIn("beat от 0 до 12", short_prompt)
        self.assertIn("beat от 0 до 60", long_prompt)
        self.assertIn(prompts.short_speech, short_prompt)
        self.assertIn(prompts.long_speech, long_prompt)
        self.assertIn('{"drums":[', short_prompt)
        self.assertNotIn("${", long_prompt)

    def test_invalid_placeholder_is_reported_before_any_model_request(self) -> None:
        """Проверяет раннее отклонение неверного шаблона промпта.

        :return: Не возвращает значение.
        """
        source = files("semen_banan.resources").joinpath("prompts.toml").read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "prompts.toml"
            path.write_text(
                source.replace("${last_speech_beat}", "${unknown_parameter}"), encoding="utf-8"
            )

            with self.assertRaisesRegex(BotError, "prompts.toml"):
                PromptCatalog.load(path)

    def test_user_text_is_not_recursively_interpreted_as_a_template(self) -> None:
        """Проверяет сохранение пользовательских подстановок как обычного текста.

        :return: Не возвращает значение.
        """
        request = 'Музыка про ${tempo} и {"пример": 1}'
        result = load_prompts().comparison_section(request, 110, 0, 16)
        self.assertIn(request, result)
        self.assertIn("Темп 110", result)


class PromptInjection(unittest.IsolatedAsyncioTestCase):
    """Проверки передачи общего каталога промптов."""

    async def test_gateway_uses_supplied_catalog_for_all_modes(self) -> None:
        """Проверяет единый каталог промптов для всех режимов Gateway.

        :return: Не возвращает значение.
        """
        prompts = replace(
            load_prompts(), persona="Новый персонаж", routing="Маршрутизируй", composition="Сочини"
        )
        settings = Settings("unused", frozenset(), "http://localhost", "unused")
        gateway = OpenClawClient(AsyncMock(), settings, prompts)
        gateway._complete = AsyncMock(return_value="{}")
        current_message = {"name": "Тест", "text": "Пример"}

        await gateway.reply([], current_message)
        self.assertEqual(gateway._complete.await_args.args[0], prompts.persona)
        await gateway.classify([], current_message, {})
        self.assertEqual(
            gateway._complete.await_args.args[0], prompts.routing + "\n" + prompts.reactions
        )
        await gateway.compose([], current_message)
        self.assertEqual(gateway._complete.await_args.args[0], prompts.composition)
        await gateway.arrange([], current_message, beats=64)
        system_prompt, payload, _ = gateway._complete.await_args.args
        self.assertEqual(system_prompt, prompts.arrangement(64))
        self.assertEqual(json.loads(payload)["speech_style"], prompts.persona)

from __future__ import annotations

import unittest
from typing import Never
from unittest.mock import Mock, patch

from semen_banan.audio.composers import IncompleteCompositionError, NanoMaestro


class CompositionRecovery(unittest.TestCase):
    """Проверки повтора неполной локальной генерации."""

    def test_incomplete_model_output_can_recover(self) -> None:
        """Проверяет восстановление после слишком короткой генерации.

        :return: Не возвращает значение.
        """
        composer = object.__new__(NanoMaestro)
        notes = [{"start": 12, "midi": 64, "beats": 1, "velocity": 80}]
        composer._compose = Mock(
            side_effect=[IncompleteCompositionError("Слишком короткая пьеса"), notes]
        )
        self.assertEqual(composer.compose({}, seed=42), notes)

    def test_retry_does_not_extend_twenty_second_budget(self) -> None:
        """Проверяет общий лимит времени повторной генерации.

        :return: Не возвращает значение.
        """
        composer = object.__new__(NanoMaestro)
        now = [100.0]

        def incomplete(*args: object) -> Never:
            """Имитирует слишком короткую генерацию с исчерпанием времени.

            :param args: Дополнительные позиционные параметры вызова.
            :return: Не возвращает значение: всегда вызывает исключение.
            """
            now[0] += 21

            raise IncompleteCompositionError("Слишком короткая пьеса")

        composer._compose = Mock(side_effect=incomplete)

        with patch("semen_banan.audio.composers.time.monotonic", side_effect=lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, "20 секунд"):
                composer.compose({})

        self.assertEqual(composer._compose.call_count, 1)

    def test_repeated_incomplete_output_is_reported_as_failure(self) -> None:
        """Проверяет ошибку после повторной неполной генерации.

        :return: Не возвращает значение.
        """
        composer = object.__new__(NanoMaestro)
        composer._compose = Mock(side_effect=IncompleteCompositionError("Слишком короткая пьеса"))

        with self.assertRaises(IncompleteCompositionError):
            composer.compose({})

        self.assertEqual(composer._compose.call_count, 2)

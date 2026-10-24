from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from semen_banan.audio.customization import AudioCustomization
from semen_banan.audio.models import Arrangement, AudioRequest, AudioResult, Score
from semen_banan.config import AppPaths
from semen_banan.processes import stop_worker

LOGGER = logging.getLogger(__name__)


class AudioError(RuntimeError):
    """Ошибка запуска, ожидания или результата аудиозадания."""


class AudioJobRunner:
    """Управление отдельным процессом генерации голосового сообщения."""

    def __init__(
        self,
        paths: AppPaths,
        worker_command: tuple[str, ...] | None = None,
        seed: int | None = None,
    ) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param paths: Пути к рабочим данным приложения.
        :param worker_command: Команда запуска генератора; None выбирает стандартный модуль.
        :param seed: Начальное значение генератора случайных чисел.
        :return: Не возвращает значение.
        """
        self.seed = seed
        self.paths = paths
        self.worker_command = worker_command or (
            sys.executable,
            "-X",
            "utf8",
            "-u",
            "-m",
            "semen_banan.audio.worker",
        )

    async def render(
        self,
        score: Score,
        use_nano: bool = False,
        arrangement: Arrangement | None = None,
        timeout: float = 90,
        *,
        customization: AudioCustomization | None = None,
    ) -> AudioResult:
        """Запускает изолированную генерацию и проверяет готовое аудио.

        :param score: Партитура с темпом, мелодией и аккордами.
        :param use_nano: Признак использования локальной модели NanoMaestro.
        :param arrangement: Параметры барабанов и речевых фраз.
        :param timeout: Максимальное время ожидания в секундах.
        :param customization: Проверенные длительность, темп, инструменты и уровни.
        :return: Голосовое сообщение, его длительность и PID генератора.
        """
        payload = AudioRequest(
            score, use_nano, arrangement, self.seed, customization or AudioCustomization()
        ).to_payload()
        return await self._run_request(payload, timeout)

    async def speak(self, text: str, timeout: float = 90) -> AudioResult:
        """Озвучивает обычную реплику без музыкального сопровождения.

        :param text: Текст реплики длиной до 1200 символов.
        :param timeout: Максимальное время ожидания аудиогенератора.
        :return: Голосовое OGG/Opus с длительностью и PID процесса.
        """
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1200:
            raise AudioError("Реплика для озвучивания должна содержать от 1 до 1200 символов.")
        return await self._run_request({"kind": "speech", "text": text}, timeout)

    async def _run_request(self, payload: dict[str, Any], timeout: float) -> AudioResult:
        """Выполняет музыкальное или речевое задание в изолированном процессе.

        :param payload: Проверенное задание генерации аудио.
        :param timeout: Максимальное время ожидания в секундах.
        :return: Готовое голосовое сообщение.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            raise AudioError("Время ожидания генерации должно быть положительным.")
        paths = self.paths
        request = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # Локальному генератору не нужны секреты Telegram и Gateway.
        worker_environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("TELEGRAM_", "OPENCLAW_"))
        }
        worker_environment["SEMEN_BANAN_HOME"] = str(paths.home)
        process_options = (
            {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            if sys.platform == "win32"
            else {"start_new_session": True}
        )

        with tempfile.TemporaryDirectory(prefix="semenbanan-audio-") as temporary_directory:
            output = Path(temporary_directory) / "voice.ogg"

            try:
                process = await asyncio.create_subprocess_exec(
                    *self.worker_command,
                    "--output",
                    str(output),
                    cwd=paths.home,
                    env=worker_environment,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **process_options,
                )
            except OSError:
                raise AudioError("Не удалось запустить генератор аудио.") from None

            try:
                await asyncio.wait_for(process.communicate(request), timeout=timeout)
            except TimeoutError:
                await stop_worker(process)

                raise AudioError(
                    "Генерация аудио не завершилась вовремя; процесс остановлен."
                ) from None
            except asyncio.CancelledError:
                await asyncio.shield(stop_worker(process))

                raise
            finally:
                if process.returncode is None:
                    await stop_worker(process)

            try:
                worker_result = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))

                if worker_result.get("error"):
                    raise AudioError(str(worker_result["error"])[:300])

                if process.returncode != 0:
                    raise ValueError

                duration, worker_pid = worker_result["duration"], worker_result["worker_pid"]

                if (
                    type(duration) is not int
                    or not 0 < duration <= 90
                    or type(worker_pid) is not int
                    or worker_pid <= 0
                ):
                    raise ValueError

                if output.stat().st_size > 20 * 1024 * 1024:
                    raise ValueError

                voice = output.read_bytes()

                if not voice.startswith(b"OggS"):
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                raise AudioError("Генератор не вернул готовое голосовое сообщение.") from None

            LOGGER.info("Генератор аудио завершён: pid=%s, duration=%ss", worker_pid, duration)

            return AudioResult(voice=voice, duration=duration, worker_pid=worker_pid)

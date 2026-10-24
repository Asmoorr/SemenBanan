from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from semen_banan.audio.models import Arrangement, AudioRequest, AudioResult, Score
from semen_banan.config import AppPaths

LOG = logging.getLogger(__name__)


class AudioError(RuntimeError):
    """A failed or timed-out audio job."""


async def stop_worker(process: asyncio.subprocess.Process) -> None:
    """Stop descendants too: Windows venv launchers have a child Python process."""
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/taskkill.exe"),
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        await asyncio.wait_for(killer.wait(), timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await asyncio.wait_for(process.communicate(), timeout=10)


class AudioJobRunner:
    def __init__(
        self,
        paths: AppPaths,
        worker_command: tuple[str, ...] | None = None,
        seed: int | None = None,
    ) -> None:
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
    ) -> AudioResult:
        if not math.isfinite(timeout) or timeout <= 0:
            raise AudioError("Время ожидания генерации должно быть положительным.")
        paths = self.paths
        request = json.dumps(
            AudioRequest(score, use_nano, arrangement, self.seed).to_payload(), ensure_ascii=False
        ).encode("utf-8")
        # Audio generation has no need for Telegram or Gateway credentials.
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("TELEGRAM_", "OPENCLAW_"))
        }
        environment["SEMEN_BANAN_HOME"] = str(paths.home)
        options = (
            {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            if sys.platform == "win32"
            else {"start_new_session": True}
        )
        with tempfile.TemporaryDirectory(prefix="semenbanan-audio-") as directory:
            output = Path(directory) / "voice.ogg"
            try:
                process = await asyncio.create_subprocess_exec(
                    *self.worker_command,
                    "--output",
                    str(output),
                    cwd=paths.home,
                    env=environment,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **options,
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
                result = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
                if result.get("error"):
                    raise AudioError(str(result["error"])[:300])
                if process.returncode != 0:
                    raise ValueError
                duration, worker_pid = result["duration"], result["worker_pid"]
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
            LOG.info("Генератор аудио завершён: pid=%s, duration=%ss", worker_pid, duration)
            return AudioResult(voice=voice, duration=duration, worker_pid=worker_pid)

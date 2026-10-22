"""Run one audio job in a disposable process, then release its model memory."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parent
WORKER_SCRIPT = ROOT / "audio_worker.py"
LOG = logging.getLogger("semyon")


class AudioError(RuntimeError):
    """A failed or timed-out audio job."""


@dataclass(frozen=True)
class AudioResult:
    voice: bytes
    duration: int
    worker_pid: int


async def stop_worker(process: asyncio.subprocess.Process) -> None:
    """Stop descendants too: Windows venv launchers have a child Python process."""
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/taskkill.exe"),
            "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        await asyncio.wait_for(killer.wait(), timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await asyncio.wait_for(process.communicate(), timeout=10)


async def render_audio(score: dict[str, Any], use_nano: bool = False,
                       arrangement: dict[str, Any] | None = None,
                       timeout: float = 90) -> AudioResult:
    if not math.isfinite(timeout) or timeout <= 0:
        raise AudioError("Время ожидания генерации должно быть положительным.")
    request = json.dumps({"score": score, "use_nano": use_nano,
                          "arrangement": arrangement}, ensure_ascii=False).encode("utf-8")
    # Audio generation has no need for Telegram or Gateway credentials.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("TELEGRAM_", "OPENCLAW_"))}
    options = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
               else {"start_new_session": True})
    with tempfile.TemporaryDirectory(prefix="semenbanan-audio-") as directory:
        output = Path(directory) / "voice.ogg"
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-X", "utf8", "-u", str(WORKER_SCRIPT), "--output", str(output),
                cwd=ROOT, env=environment, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options)
        except OSError:
            raise AudioError("Не удалось запустить генератор аудио.") from None
        try:
            await asyncio.wait_for(process.communicate(request), timeout=timeout)
        except asyncio.TimeoutError:
            await stop_worker(process)
            raise AudioError("Генерация аудио не завершилась вовремя; процесс остановлен.") from None
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
            if type(duration) is not int or not 0 < duration <= 90 or type(worker_pid) is not int or worker_pid <= 0:
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

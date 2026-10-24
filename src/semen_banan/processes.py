from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path


async def stop_worker(process: asyncio.subprocess.Process) -> None:
    """Останавливает генератор вместе с дочерними процессами.

    :param process: Процесс генератора аудио.
    :return: Не возвращает значение.
    """
    if process.returncode is not None:
        return

    if sys.platform == "win32":
        termination_process = await asyncio.create_subprocess_exec(
            str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32/taskkill.exe"),
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        await asyncio.wait_for(termination_process.wait(), timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    await asyncio.wait_for(process.communicate(), timeout=10)

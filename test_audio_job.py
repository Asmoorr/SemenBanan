import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from audio_job import AudioError, ROOT, render_audio


def process_is_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class AudioJob(unittest.IsolatedAsyncioTestCase):
    def sleeping_worker(self, directory: Path) -> tuple[Path, Path]:
        marker, worker = directory / "pids.json", directory / "sleep_worker.py"
        worker.write_text(
            "import json,os,subprocess,sys,time\nfrom pathlib import Path\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
            f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
            "time.sleep(60)\n", encoding="utf-8")
        return worker, marker

    async def test_timeout_stops_worker_and_its_child(self):
        with tempfile.TemporaryDirectory() as directory:
            worker, marker = self.sleeping_worker(Path(directory))
            with patch("audio_job.WORKER_SCRIPT", worker):
                with self.assertRaisesRegex(AudioError, "вовремя"):
                    await render_audio({}, timeout=1)
            self.assertTrue(marker.exists())
            for pid in json.loads(marker.read_text()):
                self.assertFalse(process_is_alive(pid), f"Process {pid} survived timeout")

    async def test_cancel_stops_worker_and_its_child(self):
        with tempfile.TemporaryDirectory() as directory:
            worker, marker = self.sleeping_worker(Path(directory))
            with patch("audio_job.WORKER_SCRIPT", worker):
                task = asyncio.create_task(render_audio({}, timeout=60))
                try:
                    for _ in range(250):
                        if marker.exists():
                            break
                        await asyncio.sleep(0.02)
                    self.assertTrue(marker.exists())
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
            for pid in json.loads(marker.read_text()):
                self.assertFalse(process_is_alive(pid), f"Process {pid} survived cancellation")

    async def test_bot_import_does_not_load_model_runtimes(self):
        result = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import bot,json,sys; print(json.dumps([m for m in ['numpy','onnxruntime','piper'] if m in sys.modules]))",
            cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, errors = await result.communicate()
        self.assertEqual(result.returncode, 0, errors.decode())
        self.assertEqual(json.loads(output), [])

    @unittest.skipUnless((ROOT / "assets/speech/denis.onnx").exists() and
                         importlib.util.find_spec("piper"), "Install music assets for worker integration test")
    async def test_real_job_returns_audio_after_model_process_exits(self):
        score = {"tempo": 100, "melody": [{"midi": n, "beats": 1} for n in
                 [64, 67, 69, 67, 65, 69, 72, 69, 64, 67, 71, 67, 62, 65, 67, 60]],
                 "chords": [[48, 52, 55], [53, 57, 60], [48, 52, 55], [43, 47, 50]]}
        arrangement = {"drums": [{"midi": 36, "beat": 0, "velocity": 70}],
                       "speech": [{"beat": 0, "text": "С вами Семён. Бананы в студию."}]}
        audio = await render_audio(score, True, arrangement)
        self.assertTrue(audio.voice.startswith(b"OggS"))
        self.assertGreaterEqual(audio.duration, 9)
        self.assertLessEqual(audio.duration, 20)
        self.assertFalse(process_is_alive(audio.worker_pid))

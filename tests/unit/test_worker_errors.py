from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class WorkerErrors(unittest.TestCase):
    """Проверки русских диагностических сообщений аудиогенератора."""

    def test_invalid_input_produces_a_russian_error_without_audio(self) -> None:
        """Проверяет понятную ошибку для неверного JSON и отсутствующих полей.

        :return: Не возвращает значение.
        """
        for request_bytes in (b"invalid JSON", b"{}"):
            with self.subTest(request=request_bytes), tempfile.TemporaryDirectory() as directory:
                output_path = Path(directory) / "voice.ogg"
                process_result = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-m",
                        "semen_banan.audio.worker",
                        "--output",
                        str(output_path),
                    ],
                    input=request_bytes,
                    capture_output=True,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.assertEqual(process_result.returncode, 1)
                self.assertFalse(output_path.exists())
                metadata = json.loads(output_path.with_suffix(".json").read_text(encoding="utf-8"))
                self.assertIn("Некорректное задание", metadata["error"])

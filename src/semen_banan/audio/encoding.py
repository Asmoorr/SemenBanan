from __future__ import annotations

import shutil
import subprocess


def ffmpeg_executable() -> str:
    """Находит системный или установленный с пакетом FFmpeg.

    :return: Путь к исполняемому файлу FFmpeg.
    """
    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            raise RuntimeError(
                "Установи FFmpeg или пакет imageio-ffmpeg для голосовых сообщений."
            ) from None

    return ffmpeg


def encode_voice(wav_bytes: bytes, *, master_gain: float = 1.0, normalize: bool = True) -> bytes:
    """Кодирует WAV в голосовое сообщение OGG/Opus.

    :param wav_bytes: Исходное аудио в формате WAV.
    :param master_gain: Общая громкость от 0 до 1 после нормализации.
    :param normalize: Нормализация громкости; отключается для точного баланса дорожек.
    :return: Байты готового голосового сообщения.
    """
    if not 0 <= master_gain <= 1:
        raise ValueError("Общая громкость должна быть от нуля до единицы.")

    ffmpeg = ffmpeg_executable()
    normalization_filter = "loudnorm=I=-18:TP=-1.5:LRA=9," if normalize else ""

    try:
        encoding_result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "wav",
                "-i",
                "pipe:0",
                "-af",
                f"{normalization_filter}volume={master_gain}",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-b:a",
                "96k",
                "-f",
                "ogg",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            check=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("Не удалось закодировать голосовое сообщение через FFmpeg.") from None

    if not encoding_result.stdout.startswith(b"OggS"):
        raise RuntimeError("FFmpeg не вернул OGG/Opus.")

    return encoding_result.stdout

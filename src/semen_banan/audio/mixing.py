from __future__ import annotations

import io
import math
import subprocess
import wave
from typing import TYPE_CHECKING

from semen_banan.audio.encoding import ffmpeg_executable
from semen_banan.audio.models import Arrangement, NoteSequence
from semen_banan.audio.rendering import render_piano
from semen_banan.audio.speech import synthesize_speech

if TYPE_CHECKING:
    from semen_banan.audio.types import AudioSamples

RATE = 48000


def _decode(wav: bytes) -> AudioSamples:
    """Преобразует аудиодорожку в стереосэмплы для сведения.

    :param wav: Аудиодорожка для декодирования.
    :return: Матрица сэмплов двух каналов с частотой 48 кГц.
    """
    import numpy as np

    try:
        conversion_result = subprocess.run(
            [
                ffmpeg_executable(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-ar",
                str(RATE),
                "-ac",
                "2",
                "-f",
                "f32le",
                "pipe:1",
            ],
            input=wav,
            capture_output=True,
            check=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        samples = np.frombuffer(conversion_result.stdout, dtype="<f4").reshape(-1, 2).copy()
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("Не удалось подготовить аудиодорожку для сведения.") from None

    if not len(samples) or len(samples) > RATE * 90 or not np.isfinite(samples).all():
        raise RuntimeError("Аудиодорожка пуста или слишком длинная.")

    return samples


def _wav(samples: AudioSamples) -> bytes:
    """Записывает стереосэмплы в WAV с шестнадцатибитным PCM.

    :param samples: Массив сэмплов аудиодорожки.
    :return: Байты WAV-файла.
    """
    import numpy as np

    output = io.BytesIO()
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")

    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm.tobytes())

    return output.getvalue()


def _level(samples: AudioSamples, target_level: float) -> AudioSamples:
    """Нормализует уровень активной части аудиодорожки.

    :param samples: Массив сэмплов аудиодорожки.
    :param target_level: Целевой уровень активной части дорожки.
    :return: Сэмплы с выровненной громкостью.
    """
    import numpy as np

    active_samples = np.abs(samples).max(axis=1) > 0.002

    if active_samples.any():
        root_mean_square = float(np.sqrt(np.mean(samples[active_samples] ** 2)))
        peak_amplitude = float(np.abs(samples).max())
        samples = samples * min(
            12, target_level / max(root_mean_square, 0.0001), 0.9 / max(peak_amplitude, 0.0001)
        )

    return samples


def backing_tracks(tempo: int, beats: int, arrangement: Arrangement) -> tuple[bytes, bytes]:
    """Создаёт дорожки барабанов и речи по аранжировке.

    :param tempo: Темп пьесы в ударах в минуту.
    :param beats: Длительность пьесы в музыкальных долях.
    :param arrangement: Параметры барабанов и речевых фраз.
    :return: Пара WAV-дорожек: барабаны и речь.
    """
    import numpy as np

    drum_notes: NoteSequence = [
        dict(
            start=bar + hit["beat"],
            beats=0.12,
            midi=hit["midi"],
            velocity=hit["velocity"],
            channel=9,
        )
        for bar in range(0, beats, 4)
        for hit in arrangement["drums"]
    ]
    duration = beats * 60 / tempo + 2.5
    silent_samples = np.zeros((math.ceil(duration * RATE), 2), dtype=np.float32)
    drums = render_piano(drum_notes, tempo)[0] if drum_notes else _wav(silent_samples)
    phrases = []
    phrase_end_sample = 0

    for speech_line in arrangement["speech"]:
        samples = _level(_decode(synthesize_speech(speech_line["text"])), 0.16)
        # Сдвигаем пересекающиеся фразы, сохраняя их полное звучание.
        start_sample = max(round(speech_line["beat"] * 60 / tempo * RATE), phrase_end_sample)
        phrases.append((start_sample, samples))
        phrase_end_sample = start_sample + len(samples) + round(0.2 * RATE)

    if phrase_end_sample > RATE * 90:
        raise RuntimeError("Речевая партия слишком длинная.")

    speech_samples = np.zeros((max(len(silent_samples), phrase_end_sample), 2), dtype=np.float32)

    for start_sample, samples in phrases:
        speech_samples[start_sample : start_sample + len(samples)] += samples

    return drums, _wav(speech_samples)


def mix_tracks(piano: bytes, drums: bytes, speech: bytes) -> tuple[bytes, int]:
    """Сводит дорожки и приглушает инструменты во время речи.

    :param piano: WAV-дорожка пианино.
    :param drums: WAV-дорожка барабанов.
    :param speech: WAV-дорожка речи.
    :return: Сведённый WAV и его длительность в секундах.
    """
    import numpy as np

    tracks = [_level(_decode(piano), 0.11), _level(_decode(drums), 0.07), _decode(speech)]
    sample_count = max(len(track) for track in tracks)
    tracks = [np.pad(track, ((0, sample_count - len(track)), (0, 0))) for track in tracks]
    block_size = 480
    padded_speech = np.pad(tracks[2], ((0, (-sample_count) % block_size), (0, 0)))
    speech_energy = np.sqrt(np.mean(padded_speech.reshape(-1, block_size, 2) ** 2, axis=(1, 2)))
    active_samples = (speech_energy > 0.008).astype(np.float32)
    expanded_speech_activity = np.convolve(active_samples, np.ones(25), mode="same") > 0
    envelope = np.convolve(expanded_speech_activity.astype(np.float32), np.ones(7) / 7, mode="same")
    envelope = np.interp(np.arange(sample_count), np.arange(len(envelope)) * block_size, envelope)[
        :, None
    ]
    mixed_samples = tracks[0] * (1 - 0.68 * envelope) + tracks[1] * (1 - 0.5 * envelope) + tracks[2]
    peak_amplitude = float(np.abs(mixed_samples).max())

    if peak_amplitude > 0.92:
        mixed_samples *= 0.92 / peak_amplitude

    return _wav(mixed_samples), math.ceil(sample_count / RATE)

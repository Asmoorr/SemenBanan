from __future__ import annotations

import io
import math
import subprocess
import wave
from typing import TYPE_CHECKING

from semen_banan.audio.customization import AudioCustomization, Instrument
from semen_banan.audio.encoding import ffmpeg_executable
from semen_banan.audio.models import Arrangement, NoteSequence
from semen_banan.audio.rendering import render_piano
from semen_banan.audio.speech import synthesize_speech
from semen_banan.audio.voice_settings import VoiceSettings

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


def backing_tracks(
    tempo: int, beats: int, arrangement: Arrangement, *, voice_settings: VoiceSettings | None = None
) -> tuple[bytes, bytes]:
    """Создаёт дорожки барабанов и речи по аранжировке.

    :param tempo: Темп пьесы в ударах в минуту.
    :param beats: Длительность пьесы в музыкальных долях.
    :param arrangement: Параметры барабанов и речевых фраз.
    :param voice_settings: Параметры локального голоса и эффектов.
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
        samples = _level(
            _decode(synthesize_speech(speech_line["text"], voice_settings or VoiceSettings())), 0.13
        )
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
    envelope = speech_ducking_envelope(tracks[2])
    mixed_samples = tracks[0] * (1 - 0.2 * envelope) + tracks[1] * (1 - 0.1 * envelope) + tracks[2]
    peak_amplitude = float(np.abs(mixed_samples).max())

    if peak_amplitude > 0.92:
        mixed_samples *= 0.92 / peak_amplitude

    return _wav(mixed_samples), math.ceil(sample_count / RATE)


def mix_custom_tracks(
    instruments: dict[Instrument, bytes],
    drums: bytes | None,
    speech: bytes | None,
    customization: AudioCustomization,
) -> tuple[bytes, int]:
    """Сводит выбранные инструменты с точной длительностью и уровнями дорожек.

    :param instruments: Озвученные инструментальные дорожки.
    :param drums: Барабаны либо None.
    :param speech: Речь либо None.
    :param customization: Проверенные параметры звучания.
    :return: WAV заданной длины и длительность в секундах.
    """
    import numpy as np

    instrument_tracks = {
        instrument: _level(_decode(audio), 0.11) for instrument, audio in instruments.items()
    }
    drum_samples = _level(_decode(drums), 0.07) if drums is not None else None
    speech_samples = _decode(speech) if speech is not None else None
    lengths = [len(samples) for samples in instrument_tracks.values()]
    lengths += [len(samples) for samples in (drum_samples, speech_samples) if samples is not None]
    sample_count = (
        customization.duration_seconds * RATE
        if customization.duration_seconds is not None
        else max(lengths)
    )

    def fit(samples: AudioSamples) -> AudioSamples:
        """Обрезает или дополняет дорожку до общей длины микса.

        :param samples: Исходные стереосэмплы.
        :return: Дорожка с заданным количеством сэмплов.
        """
        return np.pad(samples[:sample_count], ((0, max(0, sample_count - len(samples))), (0, 0)))

    voice = (
        fit(speech_samples) * customization.gain("speech")
        if speech_samples is not None
        else np.zeros((sample_count, 2), dtype=np.float32)
    )
    envelope = speech_ducking_envelope(voice)
    mixed = voice.copy()
    audible_count = max(
        1, sum(customization.gain(instrument.value) > 0 for instrument in instrument_tracks)
    )

    for instrument, samples in instrument_tracks.items():
        mixed += (
            fit(samples)
            * customization.gain(instrument.value)
            / math.sqrt(audible_count)
            * (1 - 0.2 * envelope)
        )
    if drum_samples is not None:
        mixed += fit(drum_samples) * customization.gain("drums") * (1 - 0.1 * envelope)

    peak = float(np.abs(mixed).max())
    if peak > 0.92:
        mixed *= 0.92 / peak
    if customization.duration_seconds is not None:
        fade_samples = min(round(RATE * 0.04), sample_count)
        mixed[-fade_samples:] *= np.linspace(1, 0, fade_samples, dtype=np.float32)[:, None]

    return _wav(mixed), math.ceil(sample_count / RATE)


def speech_ducking_envelope(speech: AudioSamples) -> AudioSamples:
    """Плавно определяет активную речь для мягкого приглушения аккомпанемента.

    :param speech: Речевая дорожка после пользовательской настройки громкости.
    :return: Огибающая от нуля до единицы с одним каналом и исходной длиной.
    """
    import numpy as np

    sample_count = len(speech)
    if not sample_count:
        return np.zeros((0, 1), dtype=np.float32)

    block_size = 480
    padded = np.pad(speech, ((0, (-sample_count) % block_size), (0, 0)))
    energy = np.sqrt(np.mean(padded.reshape(-1, block_size, 2) ** 2, axis=(1, 2)))
    activity = np.clip((energy - 0.008) / 0.032, 0, 1)
    smoothing_blocks = min(15, len(activity))
    envelope = np.convolve(activity, np.ones(smoothing_blocks) / smoothing_blocks, mode="same")
    return np.interp(
        np.arange(sample_count), np.arange(len(envelope)) * block_size, envelope
    ).astype(np.float32)[:, None]

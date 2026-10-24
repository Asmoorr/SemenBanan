from __future__ import annotations

import io
import math
import subprocess
import wave

from semen_banan.audio.encoding import ffmpeg_executable
from semen_banan.audio.models import Arrangement
from semen_banan.audio.rendering import render_piano
from semen_banan.audio.speech import synthesize_speech

RATE = 48000


def _decode(wav: bytes):
    import numpy as np

    try:
        result = subprocess.run(
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
        samples = np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2).copy()
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("Не удалось подготовить аудиодорожку для сведения.") from None
    if not len(samples) or len(samples) > RATE * 90 or not np.isfinite(samples).all():
        raise RuntimeError("Аудиодорожка пуста или слишком длинная.")
    return samples


def _wav(samples) -> bytes:
    import numpy as np

    output = io.BytesIO()
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


def _level(samples, target: float):
    import numpy as np

    active = np.abs(samples).max(axis=1) > 0.002
    if active.any():
        rms = float(np.sqrt(np.mean(samples[active] ** 2)))
        peak = float(np.abs(samples).max())
        samples = samples * min(12, target / max(rms, 0.0001), 0.9 / max(peak, 0.0001))
    return samples


def backing_tracks(tempo: int, beats: int, arrangement: Arrangement) -> tuple[bytes, bytes]:
    import numpy as np

    drum_notes = [
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
    silent = np.zeros((math.ceil(duration * RATE), 2), dtype=np.float32)
    drums = render_piano(drum_notes, tempo)[0] if drum_notes else _wav(silent)
    phrases = []
    end = 0
    for line in arrangement["speech"]:
        samples = _level(_decode(synthesize_speech(line["text"])), 0.16)
        # Preserve full phrases; shift a collision slightly rather than truncating speech.
        start = max(round(line["beat"] * 60 / tempo * RATE), end)
        phrases.append((start, samples))
        end = start + len(samples) + round(0.2 * RATE)
    if end > RATE * 90:
        raise RuntimeError("Речевая партия слишком длинная.")
    voice = np.zeros((max(len(silent), end), 2), dtype=np.float32)
    for start, samples in phrases:
        voice[start : start + len(samples)] += samples
    return drums, _wav(voice)


def mix_tracks(piano: bytes, drums: bytes, speech: bytes) -> tuple[bytes, int]:
    import numpy as np

    tracks = [_level(_decode(piano), 0.11), _level(_decode(drums), 0.07), _decode(speech)]
    size = max(len(track) for track in tracks)
    tracks = [np.pad(track, ((0, size - len(track)), (0, 0))) for track in tracks]
    block = 480
    padded = np.pad(tracks[2], ((0, (-size) % block), (0, 0)))
    energy = np.sqrt(np.mean(padded.reshape(-1, block, 2) ** 2, axis=(1, 2)))
    active = (energy > 0.008).astype(np.float32)
    dilated = np.convolve(active, np.ones(25), mode="same") > 0
    envelope = np.convolve(dilated.astype(np.float32), np.ones(7) / 7, mode="same")
    envelope = np.interp(np.arange(size), np.arange(len(envelope)) * block, envelope)[:, None]
    mixed = tracks[0] * (1 - 0.68 * envelope) + tracks[1] * (1 - 0.5 * envelope) + tracks[2]
    peak = float(np.abs(mixed).max())
    if peak > 0.92:
        mixed *= 0.92 / peak
    return _wav(mixed), math.ceil(size / RATE)

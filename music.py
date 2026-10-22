"""Compose a bounded piano score and render it as an OGG/Opus voice note."""
from __future__ import annotations

from array import array
import io
import json
import math
import re
import shutil
import subprocess
import sys
import wave

SAMPLE_RATE = 24000
BEATS = 16
PLAY_REQUEST = re.compile(r"\b(?:сыграй|наиграй|поиграй|исполни)\b", re.I)
COMPOSE_REQUEST = re.compile(r"\b(?:сочини|придумай|напиши|сделай|создай)\b", re.I)
MUSIC_NOUN = re.compile(r"\b(?:пианино|роял[ьяе]?|клавиш[а-яё]*|мелоди[а-яё]*|музык[а-яё]*|мотив[а-яё]*|песн[а-яё]*)\b", re.I)


def music_requested(text: str) -> bool:
    """An imperative to play/compose is enough; conversation alone is not."""
    if re.search(r"\bне\s+(?:сыграй|наиграй|поиграй|исполни|сочини|придумай)\b", text, re.I):
        return False
    return bool(PLAY_REQUEST.search(text) or
                (COMPOSE_REQUEST.search(text) and MUSIC_NOUN.search(text)))


def parse_score(content: str) -> dict:
    """Accept only a small, deterministic musical schema from the model."""
    try:
        start, end = content.index("{"), content.rindex("}") + 1
        raw = json.loads(content[start:end])
        tempo = raw["tempo"]
        melody = raw["melody"]
        chords = raw["chords"]
        if type(tempo) is not int or not 70 <= tempo <= 140:
            raise ValueError
        if not isinstance(melody, list) or not 8 <= len(melody) <= 40:
            raise ValueError
        if not isinstance(chords, list) or len(chords) != 4:
            raise ValueError
        total = 0.0
        for note in melody:
            pitch, beats = note["midi"], note["beats"]
            if type(pitch) is not int or not 48 <= pitch <= 84:
                raise ValueError
            if type(beats) not in (int, float) or not 0.25 <= beats <= 4 or beats * 4 % 1:
                raise ValueError
            total += beats
        if not 12 <= total <= BEATS:
            raise ValueError
        for chord in chords:
            if not isinstance(chord, list) or len(chord) != 3:
                raise ValueError
            if any(type(pitch) is not int or not 40 <= pitch <= 72 for pitch in chord):
                raise ValueError
        return {"tempo": tempo, "melody": melody, "chords": chords}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise ValueError("Модель вернула неверные ноты для пианино.") from None


def _add_note(samples: array, midi: int, start: float, duration: float, volume: float) -> None:
    """Four decaying harmonics and a short struck-key attack."""
    frequency = 440 * 2 ** ((midi - 69) / 12)
    first = round(start * SAMPLE_RATE)
    count = min(round((duration + 0.18) * SAMPLE_RATE), len(samples) - first)
    if count <= 0:
        return
    phase_step = 2 * math.pi * frequency / SAMPLE_RATE
    for i in range(count):
        t = i / SAMPLE_RATE
        attack = min(1.0, t / 0.008)
        release = min(1.0, max(0.0, (duration + 0.18 - t) / 0.18))
        envelope = attack * release * math.exp(-2.2 * t / max(duration, 0.3))
        phase = i * phase_step
        tone = (math.sin(phase) + 0.32 * math.sin(2 * phase) +
                0.13 * math.sin(3 * phase) + 0.05 * math.sin(4 * phase))
        samples[first + i] += volume * envelope * tone


def render_wav(score: dict) -> tuple[bytes, int]:
    seconds_per_beat = 60 / score["tempo"]
    duration = BEATS * seconds_per_beat + 0.4
    samples = array("f", [0.0]) * round(duration * SAMPLE_RATE)
    for bar, chord in enumerate(score["chords"]):
        for beat in (0, 2):
            for pitch in chord:
                _add_note(samples, pitch, (bar * 4 + beat) * seconds_per_beat,
                          1.7 * seconds_per_beat, 0.08)
    offset = 0.0
    for note in score["melody"]:
        length = note["beats"] * seconds_per_beat
        _add_note(samples, note["midi"], offset, length * 0.9, 0.24)
        offset += length
    peak = max(abs(sample) for sample in samples) or 1
    scale = min(1.0, 0.88 / peak)
    pcm = array("h", (round(max(-1, min(1, sample * scale)) * 32767) for sample in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return output.getvalue(), math.ceil(duration)


def encode_voice(wav_bytes: bytes) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            raise RuntimeError("Установи FFmpeg или пакет imageio-ffmpeg для голосовых сообщений.") from None
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
             "-ac", "1", "-c:a", "libopus", "-b:a", "48k", "-f", "ogg", "pipe:1"],
            input=wav_bytes, capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("Не удалось закодировать голосовое сообщение через FFmpeg.") from None
    if not result.stdout.startswith(b"OggS"):
        raise RuntimeError("FFmpeg не вернул OGG/Opus.")
    return result.stdout

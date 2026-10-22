"""Three independent audio tracks: piano, sampled drums, and small local TTS."""
from __future__ import annotations

from functools import lru_cache
import io
import json
import math
import subprocess
import wave

from music import ffmpeg_executable
from piano import ASSETS, local_composer, render_piano, score_notes

RATE = 48000
DRUM_NOTES = {35, 36, 38, 39, 42, 44, 46, 49, 51}


def parse_arrangement(content: str, beats: int = 16, allow_empty: bool = False) -> dict:
    try:
        data = json.loads(content[content.index("{"):content.rindex("}") + 1])
        drums, speech = data["drums"], data["speech"]
        minimum = 0 if allow_empty else 1
        if not isinstance(drums, list) or not minimum <= len(drums) <= 32:
            raise ValueError
        if not isinstance(speech, list) or not minimum <= len(speech) <= 4:
            raise ValueError
        for hit in drums:
            if type(hit["midi"]) is not int or hit["midi"] not in DRUM_NOTES:
                raise ValueError
            if type(hit["beat"]) not in (int, float) or not 0 <= hit["beat"] < 4 or hit["beat"] * 4 % 1:
                raise ValueError
            if type(hit["velocity"]) is not int or not 25 <= hit["velocity"] <= 105:
                raise ValueError
        for line in speech:
            if type(line["beat"]) not in (int, float) or not 0 <= line["beat"] <= beats - 4:
                raise ValueError
            if not isinstance(line["text"], str) or not 1 <= len(line["text"].strip()) <= 80:
                raise ValueError
        return {"drums": drums, "speech": sorted(speech, key=lambda line: line["beat"])}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise RuntimeError("Модель вернула неверные барабаны или речевую партию.") from None


@lru_cache(maxsize=1)
def speech_voice():
    try:
        from piper import PiperVoice
        from piper.config import PiperConfig
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        config = json.loads((ASSETS / "speech/denis.onnx.json").read_text(encoding="utf-8"))
        session = ort.InferenceSession(str(ASSETS / "speech/denis.onnx"), sess_options=options,
                                       providers=["CPUExecutionProvider"])
        return PiperVoice(session=session, config=PiperConfig.from_dict(config), download_dir=ASSETS / "speech")
    except Exception as exc:
        raise RuntimeError("Piper недоступен: установи requirements-music.txt и запусти setup_music.py.") from exc


@lru_cache(maxsize=16)
def synthesize_speech(text: str) -> bytes:
    if not text.strip() or len(text) > 80:
        raise RuntimeError("Речевая фраза должна содержать от 1 до 80 символов.")
    output = io.BytesIO()
    try:
        from piper import SynthesisConfig
        with wave.open(output, "wb") as wav:
            speech_voice().synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1.05))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Не удалось синтезировать речевую фразу.") from exc
    return output.getvalue()


def _decode(wav: bytes):
    import numpy as np
    try:
        result = subprocess.run(
            [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-ar", str(RATE), "-ac", "2", "-f", "f32le", "pipe:1"],
            input=wav, capture_output=True, check=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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


def backing_tracks(tempo: int, beats: int, arrangement: dict) -> tuple[bytes, bytes]:
    import numpy as np
    drum_notes = [dict(start=bar + hit["beat"], beats=0.12, midi=hit["midi"],
                       velocity=hit["velocity"], channel=9)
                  for bar in range(0, beats, 4) for hit in arrangement["drums"]]
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
        voice[start:start + len(samples)] += samples
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
    active = np.convolve(active, np.ones(25), mode="same") > 0
    envelope = np.convolve(active.astype(np.float32), np.ones(7) / 7, mode="same")
    envelope = np.interp(np.arange(size), np.arange(len(envelope)) * block, envelope)[:, None]
    mixed = tracks[0] * (1 - 0.68 * envelope) + tracks[1] * (1 - 0.5 * envelope) + tracks[2]
    peak = float(np.abs(mixed).max())
    if peak > 0.92:
        mixed *= 0.92 / peak
    return _wav(mixed), math.ceil(size / RATE)


def make_song(score: dict, use_nano: bool, arrangement: dict) -> tuple[bytes, int]:
    try:
        notes = local_composer().compose(score) if use_nano else score_notes(score)
        piano, _ = render_piano(notes, score["tempo"])
        drums, speech = backing_tracks(score["tempo"], len(score["chords"]) * 4, arrangement)
        return mix_tracks(piano, drums, speech)
    except ImportError:
        raise RuntimeError("Для трёх дорожек установи requirements-music.txt.") from None

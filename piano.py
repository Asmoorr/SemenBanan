"""Sample-based piano playback and the optional tiny local composer."""
from __future__ import annotations

from functools import lru_cache
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"


def score_notes(score: dict) -> list[dict]:
    notes = []
    offset = 0.0
    for index, note in enumerate(score["melody"]):
        notes.append(dict(start=offset, beats=note["beats"] * 0.9,
                          midi=note["midi"], velocity=82 + (index % 3 - 1) * 5, channel=0))
        offset += note["beats"]
    for bar, chord in enumerate(score["chords"]):
        for beat in (0, 2):
            for pitch in chord:
                notes.append(dict(start=bar * 4 + beat, beats=1.7,
                                  midi=pitch, velocity=48, channel=1))
    return notes


def render_piano(notes: list[dict], tempo: int) -> tuple[bytes, int]:
    """Render offline: no audio device or visible program window is opened."""
    import mido

    portable = ASSETS / "fluidsynth/bin/fluidsynth.exe"
    executable = str(portable) if portable.exists() else shutil.which("fluidsynth")
    soundfont = ASSETS / "TimGM6mb.sf2"
    if not executable or not soundfont.exists():
        raise RuntimeError("Пианино не установлено: запусти python setup_music.py.")
    if not notes or len(notes) > 1000 or not 35 <= tempo <= 240:
        raise RuntimeError("Неверная или слишком большая партитура.")
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo)))
    for channel in (0, 1):
        track.append(mido.Message("program_change", program=0, channel=channel))
    events = []
    for note in notes:
        start, length, pitch = note["start"], note["beats"], note["midi"]
        if not (0 <= start < 32 and 0 < length <= 16 and 21 <= pitch <= 108):
            raise RuntimeError("Нота выходит за допустимые границы.")
        channel = note.get("channel", 0)
        velocity = max(25, min(110, int(note["velocity"])))
        events.extend([(round(start * 480), 1, pitch, velocity, channel),
                       (round((start + length) * 480), 0, pitch, 0, channel)])
    previous = 0
    for tick, on, pitch, velocity, channel in sorted(events):
        track.append(mido.Message("note_on" if on else "note_off", note=pitch,
                                  velocity=velocity, channel=channel, time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track"))
    with tempfile.TemporaryDirectory(prefix="semyon-piano-") as folder:
        midi_path, wav_path = Path(folder) / "score.mid", Path(folder) / "piano.wav"
        midi.save(midi_path)
        try:
            subprocess.run(
                [executable, "-ni", "-g", "0.6", "-r", "24000", "-T", "wav",
                 "-o", "synth.chorus.active=0", "-F", str(wav_path), str(soundfont), str(midi_path)],
                capture_output=True, check=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            audio = wav_path.read_bytes()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("FluidSynth не смог сыграть партитуру.") from None
    with wave.open(io.BytesIO(audio)) as wav:
        duration = math.ceil(wav.getnframes() / wav.getframerate())
    return audio, duration


class NanoMaestro:
    def __init__(self) -> None:
        import numpy as np
        import onnxruntime as ort

        self.np = np
        vocab = json.loads((ASSETS / "nanomaestro/vocab.json").read_text(encoding="utf-8"))
        self.stoi = vocab["stoi"]
        self.itos = {int(k): v for k, v in vocab["itos"].items()}
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(ASSETS / "nanomaestro/model.onnx"),
                                           sess_options=options, providers=["CPUExecutionProvider"])

    def compose(self, score: dict, seed: int | None = None) -> list[dict]:
        """Continue one bar supplied by OpenClaw; generate three bars locally."""
        np = self.np
        rng = np.random.default_rng(seed)
        prompt = ["BOS", f"BPM_{score['tempo']}", "GRID_64", "BAR"]
        primer = [n for n in score_notes(score) if n["start"] < 4]
        position = None
        for note in sorted(primer, key=lambda n: (n["start"], n["midi"])):
            pos = round(note["start"] * 16)
            if pos != position:
                prompt.append(f"POS_{pos}")
                position = pos
            prompt.extend([f"NOTE_{note['midi']}",
                           f"DUR_{min(64, max(1, round(note['beats'] * 16)))}",
                           f"VEL_{min(8, max(1, round(note['velocity'] / 16)))}"])
        prompt.extend(["BAR", "POS_0"])
        h = np.zeros((2, 1, 1024), dtype=np.float32)
        c = np.zeros_like(h)
        logits = None
        def step(token: str):
            nonlocal h, c, logits
            logits, h, c = self.session.run(None, {
                "input": np.array([[self.stoi[token]]], dtype=np.int64), "h": h, "c": c})
        for token in prompt:
            step(token)
        notes = list(primer)
        bar, pos, chord_size = 1, 0, 0
        pending_pitch, pending_duration = None, None
        previous = "POS_0"
        deadline = time.monotonic() + 20
        for _ in range(1600):
            if time.monotonic() > deadline:
                raise RuntimeError("NanoMaestro не закончила пьесу за 20 секунд.")
            if previous.startswith("NOTE_"):
                allowed = [i for t, i in self.stoi.items() if t.startswith("DUR_")]
            elif previous.startswith("DUR_"):
                allowed = [i for t, i in self.stoi.items() if t.startswith("VEL_")]
            else:
                allowed = [i for t, i in self.stoi.items()
                           if (t.startswith("NOTE_") and chord_size < 8) or t == "BAR" or
                           (t.startswith("POS_") and int(t[4:]) > pos)]
            values = np.asarray(logits).reshape(-1)[allowed].astype(np.float64) / 0.85
            top = np.argsort(values)[-min(24, len(values)):]
            weights = np.exp(values[top] - values[top].max())
            selected = int(rng.choice(top, p=weights / weights.sum()))
            token = self.itos[allowed[selected]]
            if token == "BAR":
                bar += 1
                pos, chord_size = 0, 0
                if bar >= 4:
                    break
            elif token.startswith("POS_"):
                pos, chord_size = int(token[4:]), 0
            elif token.startswith("NOTE_"):
                pending_pitch = int(token[5:])
            elif token.startswith("DUR_"):
                pending_duration = min(4.0, int(token[4:]) / 16)
            elif token.startswith("VEL_") and pending_pitch is not None and pending_duration:
                start = bar * 4 + pos / 16
                notes.append(dict(start=start, beats=min(pending_duration, 16 - start),
                                  midi=pending_pitch, velocity=int(token[4:]) * 13))
                pending_pitch, pending_duration = None, None
                chord_size += 1
            step(token)
            previous = token
        if bar < 4 or len(notes) < len(primer) + 8:
            raise RuntimeError("NanoMaestro вернула слишком короткую пьесу.")
        return notes


@lru_cache(maxsize=1)
def local_composer() -> NanoMaestro:
    try:
        return NanoMaestro()
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError("NanoMaestro недоступна: установи requirements-music.txt и запусти setup_music.py.") from exc


def make_piano(score: dict, use_nano: bool = False) -> tuple[bytes, int]:
    notes = local_composer().compose(score) if use_nano else score_notes(score)
    return render_piano(notes, score["tempo"])

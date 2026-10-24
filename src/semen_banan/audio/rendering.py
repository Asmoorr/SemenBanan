from __future__ import annotations

import io
import math
import random
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from semen_banan.config import AppPaths


def render_piano(notes: list[dict], tempo: int, assets: Path | None = None) -> tuple[bytes, int]:
    """Render offline: no audio device or visible program window is opened."""
    import mido

    assets = assets or AppPaths.load().assets
    portable = assets / "fluidsynth/bin/fluidsynth.exe"
    executable = str(portable) if portable.exists() else shutil.which("fluidsynth")
    soundfont = assets / "GeneralUser-GS.sf2"
    if not executable or not soundfont.exists():
        raise RuntimeError("Пианино не установлено: запусти python tools/setup_assets.py.")
    if not notes or len(notes) > 3000 or not 35 <= tempo <= 240:
        raise RuntimeError("Неверная или слишком большая партитура.")
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo)))
    for channel in (0, 1):
        track.append(mido.Message("program_change", program=0, channel=channel))
    events = []
    rng = random.Random(42)
    for note in notes:
        start, length, pitch = note["start"], note["beats"], note["midi"]
        if not (0 <= start < 64 and 0 < length <= 16 and 21 <= pitch <= 108):
            raise RuntimeError("Нота выходит за допустимые границы.")
        channel = note.get("channel", 0)
        velocity = max(25, min(105, int(note["velocity"]) + rng.randint(-4, 4)))
        # At most 8 ms of timing variation; musical positions stay intact.
        start = max(0.0, start + rng.uniform(-0.008, 0.008) * tempo / 60)
        events.extend(
            [
                (
                    round(start * 480),
                    3,
                    mido.Message("note_on", note=pitch, velocity=velocity, channel=channel),
                ),
                (
                    round((start + length) * 480),
                    0,
                    mido.Message("note_off", note=pitch, channel=channel),
                ),
            ]
        )
    end = max(n["start"] + n["beats"] for n in notes)
    for channel in (0, 1):
        for bar_start in range(0, math.ceil(end / 4) * 4, 4):
            # Brief pedal lift at each bar prevents an accumulating blur.
            events.append(
                (
                    bar_start * 480,
                    2,
                    mido.Message("control_change", control=64, value=80, channel=channel),
                )
            )
            lift = min(bar_start + 3.92, end + 0.1)
            events.append(
                (
                    round(lift * 480),
                    1,
                    mido.Message("control_change", control=64, value=0, channel=channel),
                )
            )
    previous = 0
    for tick, _, event in sorted(events, key=lambda event: event[:2]):
        track.append(event.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track"))
    with tempfile.TemporaryDirectory(prefix="semyon-piano-") as folder:
        midi_path, wav_path = Path(folder) / "score.mid", Path(folder) / "piano.wav"
        midi.save(midi_path)
        try:
            subprocess.run(
                [
                    executable,
                    "-ni",
                    "-g",
                    "0.5",
                    "-r",
                    "48000",
                    "-T",
                    "wav",
                    "-o",
                    "synth.chorus.active=0",
                    "-o",
                    "synth.reverb.level=0.22",
                    "-o",
                    "synth.reverb.room-size=0.45",
                    "-o",
                    "synth.reverb.width=60",
                    "-F",
                    str(wav_path),
                    str(soundfont),
                    str(midi_path),
                ],
                capture_output=True,
                check=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            audio = wav_path.read_bytes()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("FluidSynth не смог сыграть партитуру.") from None
    with wave.open(io.BytesIO(audio)) as wav:
        duration = math.ceil(wav.getnframes() / wav.getframerate())
    return audio, duration

from __future__ import annotations

import io
import math
import random
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from semen_banan.audio.models import NoteSequence
from semen_banan.config import AppPaths


def render_piano(
    notes: NoteSequence, tempo: int, assets: Path | None = None, *, program: int = 0
) -> tuple[bytes, int]:
    """Озвучивает ноты через FluidSynth без открытия аудиоустройства.

    :param notes: Ноты с позициями, длительностями и силой нажатия.
    :param tempo: Темп пьесы в ударах в минуту.
    :param assets: Каталог музыкальных моделей и звуковых банков.
    :param program: Номер тембра General MIDI от 0 до 127.
    :return: WAV-дорожка и её длительность в секундах.
    """
    import mido

    assets = assets or AppPaths.load().assets
    portable_synthesizer = assets / "fluidsynth/bin/fluidsynth.exe"
    executable = (
        str(portable_synthesizer) if portable_synthesizer.exists() else shutil.which("fluidsynth")
    )
    soundfont_path = assets / "GeneralUser-GS.sf2"

    if not executable or not soundfont_path.exists():
        raise RuntimeError("Пианино не установлено: запусти python tools/setup_assets.py.")

    if not notes or len(notes) > 12000 or not 35 <= tempo <= 240:
        raise RuntimeError("Неверная или слишком большая партитура.")

    if type(program) is not int or not 0 <= program <= 127:
        raise RuntimeError("Неверный номер музыкального тембра.")

    midi_file = mido.MidiFile(ticks_per_beat=480)
    midi_track = mido.MidiTrack()
    midi_file.tracks.append(midi_track)
    midi_track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo)))

    for channel in (0, 1):
        midi_track.append(mido.Message("program_change", program=program, channel=channel))

    events = []
    random_generator = random.Random(42)

    for note in notes:
        start_beat, duration_beats, midi_pitch = note["start"], note["beats"], note["midi"]

        if not (0 <= start_beat < 256 and 0 < duration_beats <= 16 and 21 <= midi_pitch <= 108):
            raise RuntimeError("Нота выходит за допустимые границы.")

        channel = note.get("channel", 0)
        velocity = max(25, min(105, int(note["velocity"]) + random_generator.randint(-4, 4)))
        # Вариация времени до 8 мс сохраняет музыкальные позиции.
        start_beat = max(0.0, start_beat + random_generator.uniform(-0.008, 0.008) * tempo / 60)
        events.extend(
            [
                (
                    round(start_beat * 480),
                    3,
                    mido.Message("note_on", note=midi_pitch, velocity=velocity, channel=channel),
                ),
                (
                    round((start_beat + duration_beats) * 480),
                    0,
                    mido.Message("note_off", note=midi_pitch, channel=channel),
                ),
            ]
        )

    last_note_beat = max(note["start"] + note["beats"] for note in notes)

    for channel in (0, 1):
        for bar_start in range(0, math.ceil(last_note_beat / 4) * 4, 4):
            # Отпускание педали в каждом такте предотвращает накопление звучания.
            events.append(
                (
                    bar_start * 480,
                    2,
                    mido.Message("control_change", control=64, value=80, channel=channel),
                )
            )
            pedal_release_beat = min(bar_start + 3.92, last_note_beat + 0.1)
            events.append(
                (
                    round(pedal_release_beat * 480),
                    1,
                    mido.Message("control_change", control=64, value=0, channel=channel),
                )
            )

    previous_tick = 0

    for tick, _, event in sorted(events, key=lambda event: event[:2]):
        midi_track.append(event.copy(time=tick - previous_tick))
        previous_tick = tick

    midi_track.append(mido.MetaMessage("end_of_track"))

    with tempfile.TemporaryDirectory(prefix="semyon-piano-") as temporary_directory:
        midi_path, wav_path = (
            Path(temporary_directory) / "score.mid",
            Path(temporary_directory) / "piano.wav",
        )
        midi_file.save(midi_path)

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
                    str(soundfont_path),
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

    with wave.open(io.BytesIO(audio)) as wave_reader:
        duration = math.ceil(wave_reader.getnframes() / wave_reader.getframerate())

    return audio, duration

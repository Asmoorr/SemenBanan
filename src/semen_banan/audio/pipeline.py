from __future__ import annotations

import math

from semen_banan.audio.composers import score_notes, select_composer
from semen_banan.audio.customization import Instrument
from semen_banan.audio.encoding import encode_voice
from semen_banan.audio.mixing import backing_tracks, mix_custom_tracks, mix_tracks
from semen_banan.audio.models import AudioRequest, ComposerKind, NoteSequence
from semen_banan.audio.rendering import render_piano


class AudioPipeline:
    """Последовательность создания аудио внутри отдельного генератора."""

    def generate(self, request: AudioRequest) -> tuple[bytes, int]:
        """Озвучивает ноты, сводит дорожки и кодирует голосовое.

        :param request: Исходная просьба или задание генерации.
        :return: Байты OGG/Opus и длительность записи в секундах.
        """
        customization = request.customization
        score = request.score.copy()
        if customization.tempo_bpm is not None:
            score["tempo"] = customization.tempo_bpm
        kind = ComposerKind.NANOMAESTRO if request.use_nano else ComposerKind.SCORE
        notes = select_composer(kind).compose(score, seed=request.seed)

        if customization.is_default:
            piano, duration = render_piano(notes, score["tempo"])
            if request.arrangement is not None:
                default_drums, default_speech = backing_tracks(
                    score["tempo"], len(score["chords"]) * 4, request.arrangement
                )
                piano, duration = mix_tracks(piano, default_drums, default_speech)
            return encode_voice(piano), duration

        total_beats = len(score["chords"]) * 4
        if customization.duration_seconds is not None:
            total_beats = math.ceil(customization.duration_seconds * score["tempo"] / 240) * 4
        expanded_notes = extend_notes(notes, total_beats)
        instrument_audio = {}
        for instrument in customization.instruments:
            instrument_notes = (
                bass_notes(extend_notes(score_notes(score), total_beats))
                if instrument in (Instrument.BASS, Instrument.ELECTRIC_BASS)
                else expanded_notes
            )
            instrument_audio[instrument] = render_piano(
                instrument_notes, score["tempo"], program=instrument.program
            )[0]

        drums = speech = None
        if request.arrangement is not None:
            drums, speech = backing_tracks(
                score["tempo"],
                total_beats,
                request.arrangement,
                voice_settings=customization.voice_settings,
            )
        wave_audio, duration = mix_custom_tracks(instrument_audio, drums, speech, customization)
        return encode_voice(
            wave_audio, master_gain=customization.gain("master"), normalize=False
        ), duration


def extend_notes(notes: NoteSequence, total_beats: int) -> NoteSequence:
    """Повторяет четырёхтактовую фразу до требуемой музыкальной длины.

    :param notes: Исходная фраза на шестнадцать долей.
    :param total_beats: Длина развёрнутой записи в долях.
    :return: Ноты, ограниченные длиной записи.
    """
    return [
        {
            **note,
            "start": note["start"] + offset,
            "beats": min(note["beats"], total_beats - note["start"] - offset),
        }
        for offset in range(0, total_beats, 16)
        for note in notes
        if note["start"] + offset < total_beats
    ]


def bass_notes(notes: NoteSequence) -> NoteSequence:
    """Строит басовую линию из нижних нот аккомпанемента.

    :param notes: Развёрнутые ноты мелодии и аккордов.
    :return: Одна басовая нота на каждую позицию аккомпанемента.
    """
    roots: dict[float, int] = {}
    for note in notes:
        if note.get("channel", 0) == 1:
            roots[note["start"]] = min(roots.get(note["start"], 127), note["midi"])
    if not roots:
        roots = {
            float(beat): 48
            for beat in range(0, math.ceil(max(note["start"] + note["beats"] for note in notes)), 2)
        }
    return [
        {"start": position, "beats": 1.5, "midi": max(28, pitch - 12), "velocity": 65, "channel": 0}
        for position, pitch in sorted(roots.items())
    ]

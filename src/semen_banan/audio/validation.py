from __future__ import annotations

import json

from semen_banan.audio.models import Arrangement, Score

BEATS = 16
DRUM_NOTES = {35, 36, 38, 39, 42, 44, 46, 49, 51}


def parse_score(content: str) -> Score:
    """Проверяет музыкальный JSON и извлекает ограниченную партитуру.

    :param content: Текст JSON, полученный от модели.
    :return: Проверенная мелодия, аккорды и темп.
    """
    try:
        start, end = content.index("{"), content.rindex("}") + 1
        score_data = json.loads(content[start:end])
        tempo = score_data["tempo"]
        melody = score_data["melody"]
        chords = score_data["chords"]

        if type(tempo) is not int or not 70 <= tempo <= 140:
            raise ValueError

        if not isinstance(melody, list) or not 8 <= len(melody) <= 40:
            raise ValueError

        if not isinstance(chords, list) or len(chords) != 4:
            raise ValueError

        total_beats = 0.0

        for note in melody:
            midi_pitch, beats = note["midi"], note["beats"]

            if type(midi_pitch) is not int or not 48 <= midi_pitch <= 84:
                raise ValueError

            if type(beats) not in (int, float) or not 0.25 <= beats <= 4 or beats * 4 % 1:
                raise ValueError

            total_beats += beats

        if not 12 <= total_beats <= BEATS:
            raise ValueError

        for chord in chords:
            if not isinstance(chord, list) or len(chord) != 3:
                raise ValueError

            if any(
                type(midi_pitch) is not int or not 40 <= midi_pitch <= 72 for midi_pitch in chord
            ):
                raise ValueError

        return {"tempo": tempo, "melody": melody, "chords": chords}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise ValueError("Модель вернула неверные ноты для пианино.") from None


def parse_arrangement(content: str, beats: int = 16, allow_empty: bool = False) -> Arrangement:
    """Проверяет JSON барабанов и речевых фраз.

    :param content: Текст JSON, полученный от модели.
    :param beats: Длительность пьесы в музыкальных долях.
    :param allow_empty: Разрешение пустых барабанов и речи.
    :return: Проверенная аранжировка с упорядоченной речью.
    """
    expected_field = "JSON с массивами drums и speech"

    try:
        arrangement_data = json.loads(content[content.index("{") : content.rindex("}") + 1])
        drums, speech = arrangement_data["drums"], arrangement_data["speech"]
        minimum = 0 if allow_empty else 1
        expected_field = f"drums: требуется от {minimum} до 32 ударов"

        if not isinstance(drums, list) or not minimum <= len(drums) <= 32:
            raise ValueError

        expected_field = f"speech: требуется от {minimum} до 4 фраз"

        if not isinstance(speech, list) or not minimum <= len(speech) <= 4:
            raise ValueError

        for drum_hit in drums:
            expected_field = "drums.midi: целое из 35,36,38,39,42,44,46,49,51"

            if type(drum_hit["midi"]) is not int or drum_hit["midi"] not in DRUM_NOTES:
                raise ValueError

            expected_field = "drums.beat: число от 0 до 3.75 с шагом 0.25, внутри одного такта"

            if (
                type(drum_hit["beat"]) not in (int, float)
                or not 0 <= drum_hit["beat"] < 4
                or drum_hit["beat"] * 4 % 1
            ):
                raise ValueError

            expected_field = "drums.velocity: целое от 25 до 105"

            if type(drum_hit["velocity"]) is not int or not 25 <= drum_hit["velocity"] <= 105:
                raise ValueError

        for speech_line in speech:
            expected_field = f"speech.beat: число от 0 до {beats - 4}"

            if (
                type(speech_line["beat"]) not in (int, float)
                or not 0 <= speech_line["beat"] <= beats - 4
            ):
                raise ValueError

            expected_field = "speech.text: строка от 1 до 80 символов"

            if (
                not isinstance(speech_line["text"], str)
                or not 1 <= len(speech_line["text"].strip()) <= 80
            ):
                raise ValueError

        return {
            "drums": drums,
            "speech": sorted(speech, key=lambda speech_line: speech_line["beat"]),
        }
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise RuntimeError(f"Неверная аранжировка: {expected_field}.") from None

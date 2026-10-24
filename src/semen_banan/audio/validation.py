from __future__ import annotations

import json

from semen_banan.audio.models import Arrangement, Score

BEATS = 16
DRUM_NOTES = {35, 36, 38, 39, 42, 44, 46, 49, 51}


def parse_score(content: str) -> Score:
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


def parse_arrangement(content: str, beats: int = 16, allow_empty: bool = False) -> Arrangement:
    field = "JSON с массивами drums и speech"
    try:
        data = json.loads(content[content.index("{") : content.rindex("}") + 1])
        drums, speech = data["drums"], data["speech"]
        minimum = 0 if allow_empty else 1
        field = f"drums: требуется от {minimum} до 32 ударов"
        if not isinstance(drums, list) or not minimum <= len(drums) <= 32:
            raise ValueError
        field = f"speech: требуется от {minimum} до 4 фраз"
        if not isinstance(speech, list) or not minimum <= len(speech) <= 4:
            raise ValueError
        for hit in drums:
            field = "drums.midi: целое из 35,36,38,39,42,44,46,49,51"
            if type(hit["midi"]) is not int or hit["midi"] not in DRUM_NOTES:
                raise ValueError
            field = "drums.beat: число от 0 до 3.75 с шагом 0.25, внутри одного такта"
            if (
                type(hit["beat"]) not in (int, float)
                or not 0 <= hit["beat"] < 4
                or hit["beat"] * 4 % 1
            ):
                raise ValueError
            field = "drums.velocity: целое от 25 до 105"
            if type(hit["velocity"]) is not int or not 25 <= hit["velocity"] <= 105:
                raise ValueError
        for line in speech:
            field = f"speech.beat: число от 0 до {beats - 4}"
            if type(line["beat"]) not in (int, float) or not 0 <= line["beat"] <= beats - 4:
                raise ValueError
            field = "speech.text: строка от 1 до 80 символов"
            if not isinstance(line["text"], str) or not 1 <= len(line["text"].strip()) <= 80:
                raise ValueError
        return {"drums": drums, "speech": sorted(speech, key=lambda line: line["beat"])}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise RuntimeError(f"Неверная аранжировка: {field}.") from None

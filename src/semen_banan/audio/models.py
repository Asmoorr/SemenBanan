from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, NotRequired, TypedDict

from semen_banan.audio.customization import AudioCustomization


class MelodyNote(TypedDict):
    """Нота мелодии с MIDI-высотой и длительностью в долях."""

    midi: int
    beats: float


class Score(TypedDict):
    """Темп, мелодия и аккорды ограниченной музыкальной партитуры."""

    tempo: int
    melody: list[MelodyNote]
    chords: list[list[int]]


class DrumHit(TypedDict):
    """Удар барабана с позицией и силой нажатия."""

    midi: int
    beat: float
    velocity: int


class SpeechLine(TypedDict):
    """Речевая фраза и её положение в музыкальных долях."""

    beat: float
    text: str


class Arrangement(TypedDict):
    """Партии барабанов и речи для музыкального ответа."""

    drums: list[DrumHit]
    speech: list[SpeechLine]


class ComposerKind(StrEnum):
    """Поддерживаемые способы получения музыкальных нот."""

    SCORE = "score"
    NANOMAESTRO = "nanomaestro"


@dataclass(frozen=True, slots=True)
class AudioRequest:
    """Задание генератору аудио с выбором модели и аранжировкой."""

    score: Score
    use_nano: bool = False
    arrangement: Arrangement | None = None
    seed: int | None = None
    customization: AudioCustomization = field(default_factory=AudioCustomization)

    def to_payload(self) -> dict[str, Any]:
        """Преобразует объект в данные для передачи через JSON.

        :return: Словарь с параметрами объекта.
        """
        payload = asdict(self)
        payload["customization"] = self.customization.to_payload()

        return payload


@dataclass(frozen=True, slots=True)
class AudioResult:
    """Готовая запись, длительность и идентификатор завершённого генератора."""

    voice: bytes
    duration: int
    worker_pid: int


class RenderedNote(TypedDict):
    """Нота для озвучивания с позицией, длительностью, силой и MIDI-каналом."""

    midi: int
    start: float
    beats: float
    velocity: int
    channel: NotRequired[int]


type NoteSequence = list[RenderedNote]

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TypedDict


class MelodyNote(TypedDict):
    midi: int
    beats: float


class Score(TypedDict):
    tempo: int
    melody: list[MelodyNote]
    chords: list[list[int]]


class DrumHit(TypedDict):
    midi: int
    beat: float
    velocity: int


class SpeechLine(TypedDict):
    beat: float
    text: str


class Arrangement(TypedDict):
    drums: list[DrumHit]
    speech: list[SpeechLine]


class ComposerKind(StrEnum):
    SCORE = "score"
    NANOMAESTRO = "nanomaestro"


@dataclass(frozen=True, slots=True)
class AudioRequest:
    score: Score
    use_nano: bool = False
    arrangement: Arrangement | None = None
    seed: int | None = None

    def to_payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AudioResult:
    voice: bytes
    duration: int
    worker_pid: int

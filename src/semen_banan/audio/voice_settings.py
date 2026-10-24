from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class VoiceEffect(StrEnum):
    """Локальные эффекты обработки речевой дорожки."""

    NONE = "none"
    ROBOT = "robot"
    TELEPHONE = "telephone"
    ECHO = "echo"
    REVERB = "reverb"
    CHORUS = "chorus"


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    """Проверенные настройки локальных русских голосов."""

    voice: str = "eugene"
    speed: float = 1.0
    pitch_semitones: float = 0.0
    effect: VoiceEffect = VoiceEffect.NONE
    effect_amount: int = 50

    def __post_init__(self) -> None:
        """Проверяет значения перед синтезом и обработкой.

        :return: Не возвращает значение.
        """
        if self.voice not in {"denis", "eugene", "aidar", "baya", "kseniya", "xenia"}:
            raise ValueError("Неизвестный локальный голос.")
        for value, minimum, maximum in ((self.speed, 0.75, 1.5), (self.pitch_semitones, -6, 6)):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError(
                    "Скорость голоса должна быть 0.75–1.5, высота — от −6 до +6 полутонов."
                )
        if not isinstance(self.effect, VoiceEffect):
            raise ValueError("Неизвестный голосовой эффект.")
        if type(self.effect_amount) is not int or not 0 <= self.effect_amount <= 100:
            raise ValueError("Интенсивность эффекта должна быть целым числом от 0 до 100.")

    def to_payload(self) -> dict[str, Any]:
        """Подготавливает настройки для очереди и аудиогенератора.

        :return: Сериализуемый словарь настроек.
        """
        return {**asdict(self), "effect": self.effect.value}

    @classmethod
    def parse(cls, payload: object) -> VoiceSettings:
        """Проверяет настройки, полученные от модели или очереди.

        :param payload: JSON-объект настроек голоса.
        :return: Проверенные настройки.
        """
        if not isinstance(payload, dict) or set(payload) - {
            "voice",
            "speed",
            "pitch_semitones",
            "effect",
            "effect_amount",
        }:
            raise ValueError("Неверные настройки голоса.")
        try:
            effect = VoiceEffect(payload.get("effect", "none"))
        except (ValueError, TypeError):
            raise ValueError("Неизвестный голосовой эффект.") from None

        return cls(
            voice=payload.get("voice", "eugene"),
            speed=payload.get("speed", 1.0),
            pitch_semitones=payload.get("pitch_semitones", 0.0),
            effect=effect,
            effect_amount=payload.get("effect_amount", 50),
        )

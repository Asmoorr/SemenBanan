from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from semen_banan.audio.voice_settings import VoiceSettings


class Instrument(StrEnum):
    """Поддерживаемые тембры установленного звукового банка General MIDI."""

    PIANO = "piano"
    ELECTRIC_PIANO = "electric_piano"
    GUITAR = "guitar"
    ELECTRIC_GUITAR = "electric_guitar"
    MUTED_GUITAR = "muted_guitar"
    OVERDRIVEN_GUITAR = "overdriven_guitar"
    DISTORTION_GUITAR = "distortion_guitar"
    ELECTRIC_BASS = "electric_bass"
    BASS = "bass"
    STRINGS = "strings"
    SYNTH = "synth"
    FLUTE = "flute"
    ORGAN = "organ"

    @property
    def program(self) -> int:
        """Возвращает номер тембра General MIDI, начиная с нуля.

        :return: Номер программы синтезатора.
        """
        return {
            self.PIANO: 0,
            self.ELECTRIC_PIANO: 4,
            self.GUITAR: 24,
            self.ELECTRIC_GUITAR: 27,
            self.MUTED_GUITAR: 28,
            self.OVERDRIVEN_GUITAR: 29,
            self.DISTORTION_GUITAR: 30,
            self.ELECTRIC_BASS: 34,
            self.BASS: 32,
            self.STRINGS: 48,
            self.SYNTH: 80,
            self.FLUTE: 73,
            self.ORGAN: 16,
        }[self]

    @property
    def label(self) -> str:
        """Возвращает русское название инструмента.

        :return: Название для истории диалога.
        """
        return {
            self.PIANO: "пианино",
            self.ELECTRIC_PIANO: "электропианино",
            self.GUITAR: "гитара",
            self.ELECTRIC_GUITAR: "чистая электрогитара",
            self.MUTED_GUITAR: "приглушённая электрогитара",
            self.OVERDRIVEN_GUITAR: "электрогитара с овердрайвом",
            self.DISTORTION_GUITAR: "электрогитара с дисторшном",
            self.ELECTRIC_BASS: "электробас",
            self.BASS: "бас",
            self.STRINGS: "струнные",
            self.SYNTH: "синтезатор",
            self.FLUTE: "флейта",
            self.ORGAN: "орган",
        }[self]


@dataclass(frozen=True, slots=True)
class AudioCustomization:
    """Точные параметры звучания; None сохраняет исходную длину или темп."""

    duration_seconds: int | None = None
    tempo_bpm: int | None = None
    instruments: tuple[Instrument, ...] = (Instrument.PIANO,)
    volumes: dict[str, int] = field(default_factory=dict)
    voice_settings: VoiceSettings = field(default_factory=VoiceSettings)

    def __post_init__(self) -> None:
        """Проверяет параметры независимо от способа создания объекта.

        :return: Не возвращает значение.
        """
        for value, minimum, maximum, label in (
            (self.duration_seconds, 5, 60, "Длительность"),
            (self.tempo_bpm, 60, 180, "Темп"),
        ):
            if value is not None and (type(value) is not int or not minimum <= value <= maximum):
                raise ValueError(f"{label}: требуется целое от {minimum} до {maximum}.")

        if not 1 <= len(self.instruments) <= 4 or len(set(self.instruments)) != len(
            self.instruments
        ):
            raise ValueError("Выбери от одного до четырёх разных инструментов.")
        if any(not isinstance(instrument, Instrument) for instrument in self.instruments):
            raise ValueError("Неизвестный музыкальный инструмент.")

        if not isinstance(self.voice_settings, VoiceSettings):
            raise ValueError("Неверные настройки голоса.")

        allowed_tracks = {instrument.value for instrument in Instrument} | {
            "drums",
            "speech",
            "master",
        }
        if not isinstance(self.volumes, dict) or set(self.volumes) - allowed_tracks:
            raise ValueError("Неизвестная дорожка в настройках громкости.")
        if any(type(value) is not int or not 0 <= value <= 100 for value in self.volumes.values()):
            raise ValueError("Громкость должна быть целым числом от 0 до 100 процентов.")

    @property
    def is_default(self) -> bool:
        """Проверяет отсутствие новых параметров звучания.

        :return: Признак совместимого стандартного режима.
        """
        return self == AudioCustomization()

    def gain(self, track: str) -> float:
        """Преобразует громкость дорожки из процентов в коэффициент.

        :param track: Имя инструмента, drums, speech или master.
        :return: Коэффициент от нуля до единицы.
        """
        return self.volumes.get(track, 100) / 100

    def to_payload(self) -> dict[str, Any]:
        """Готовит параметры для JSON и сохранения в очереди.

        :return: Сериализуемые параметры звучания.
        """
        return {
            "duration_seconds": self.duration_seconds,
            "tempo_bpm": self.tempo_bpm,
            "instruments": [instrument.value for instrument in self.instruments],
            "volumes": dict(self.volumes),
            "voice_settings": self.voice_settings.to_payload(),
        }

    @classmethod
    def parse(cls, payload: object) -> AudioCustomization:
        """Проверяет параметры на границе LLM или отдельного процесса.

        :param payload: Объект параметров из JSON; пустой объект использует значения по умолчанию.
        :return: Проверенные параметры звучания.
        """
        if not isinstance(payload, dict) or set(payload) - {
            "duration_seconds",
            "tempo_bpm",
            "instruments",
            "volumes",
            "voice_settings",
        }:
            raise ValueError("Неверные параметры музыкальной записи.")
        instruments = payload.get("instruments", ["piano"])
        if not isinstance(instruments, list) or any(
            not isinstance(item, str) for item in instruments
        ):
            raise ValueError("Инструменты должны быть списком названий.")
        try:
            return cls(
                payload.get("duration_seconds"),
                payload.get("tempo_bpm"),
                tuple(Instrument(item) for item in instruments),
                payload.get("volumes", {}),
                VoiceSettings.parse(payload.get("voice_settings", {})),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("Неверные параметры музыкальной записи: " + str(error)) from error

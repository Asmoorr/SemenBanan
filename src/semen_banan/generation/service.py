from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from semen_banan.audio.jobs import AudioJobRunner
from semen_banan.audio.models import Arrangement, AudioResult, Score
from semen_banan.audio.validation import parse_arrangement, parse_score
from semen_banan.conversation.models import ContextMessage, ConversationContext, Correction
from semen_banan.conversation.ports import Gateway
from semen_banan.conversation.routing import MusicOptions
from semen_banan.errors import BotError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MusicReply:
    """Аудиорезультат и описание записи для истории диалога."""

    audio: AudioResult
    description: str


class MusicGenerator:
    """Получение партитуры, аранжировки и готового музыкального ответа."""

    def __init__(self, gateway: Gateway, audio: AudioJobRunner, timeout: float) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param gateway: Клиент OpenClaw для работы с языковой моделью.
        :param audio: Исполнитель изолированных аудиозаданий.
        :param timeout: Максимальное время ожидания в секундах.
        :return: Не возвращает значение.
        """
        self.gateway = gateway
        self.audio = audio
        self.timeout = timeout

    async def generate(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        style_requests: list[str] | None = None,
        *,
        options: MusicOptions,
    ) -> MusicReply:
        """Создаёт музыкальный ответ по заранее выбранным параметрам.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :param options: Проверенные параметры музыкального режима.
        :return: Готовое аудио и описание записи для истории.
        """
        current_message = {**current_message, "music_parameters": options.to_payload()}
        score = await self._compose(conversation_context, current_message)
        if options.customization.tempo_bpm is not None:
            score["tempo"] = options.customization.tempo_bpm
        total_beats = 16
        if options.customization.duration_seconds is not None:
            total_beats = (
                math.ceil(options.customization.duration_seconds * score["tempo"] / 240) * 4
            )
        arrangement = None

        if not options.solo:
            arrangement = await self._arrange(
                conversation_context,
                current_message,
                style_requests,
                beats=total_beats,
                drums_enabled=options.drums,
                speech_enabled=options.speech,
            )

            if not options.speech:
                arrangement["speech"] = []

            if not options.drums:
                arrangement["drums"] = []

        try:
            if options.customization.is_default:
                audio = await self.audio.render(
                    score, options.use_nano, arrangement, timeout=self.timeout
                )
            else:
                audio = await self.audio.render(
                    score,
                    options.use_nano,
                    arrangement,
                    timeout=self.timeout,
                    customization=options.customization,
                )
        except RuntimeError as exc:
            raise BotError(str(exc)) from exc

        parts = [instrument.label for instrument in options.customization.instruments]

        if arrangement is not None:
            if arrangement["drums"]:
                parts.append("барабаны")

            if arrangement["speech"]:
                voice_settings = options.customization.voice_settings
                parts.append(
                    f"речь: {voice_settings.voice}, скорость {voice_settings.speed:g}, "
                    f"высота {voice_settings.pitch_semitones:+g}, "
                    f"эффект {voice_settings.effect.value} {voice_settings.effect_amount}%"
                )

        if options.use_nano:
            parts.append("NanoMaestro")

        if not options.customization.is_default:
            parts.extend([f"{audio.duration} секунд", f"{score['tempo']} BPM"])
            if options.customization.volumes:
                parts.append(
                    "громкость "
                    + ", ".join(
                        f"{track} {volume}%"
                        for track, volume in options.customization.volumes.items()
                    )
                )
        return MusicReply(audio, "[Семён записал: " + ", ".join(parts) + "]")

    async def _compose(
        self, conversation_context: ConversationContext, current_message: ContextMessage
    ) -> Score:
        """Получает и проверяет партитуру с одной повторной попыткой.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :return: Проверенная партитура из четырёх тактов.
        """
        for attempt in range(2):
            content = await self.gateway.compose(conversation_context, current_message)

            try:
                return parse_score(content)
            except ValueError:
                if attempt:
                    raise BotError("Модель дважды вернула неверные ноты.") from None

        raise AssertionError("Недостижимое состояние повторного сочинения.")

    async def _arrange(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        style_requests: list[str] | None,
        *,
        beats: int = 16,
        drums_enabled: bool = True,
        speech_enabled: bool = True,
    ) -> Arrangement:
        """Получает аранжировку и повторяет запрос при неверном JSON.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :param beats: Музыкальная длина записи в долях.
        :param drums_enabled: Требуется ли непустая партия барабанов.
        :param speech_enabled: Требуется ли непустая речевая партия.
        :return: Проверенная аранжировка.
        """
        correction: Correction | None = None

        for attempt in range(2):
            content = await self.gateway.arrange(
                conversation_context,
                current_message,
                style_requests=style_requests,
                beats=beats,
                correction=correction,
            )

            try:
                arrangement = parse_arrangement(content, beats, allow_empty=True)
                if drums_enabled and not arrangement["drums"]:
                    raise RuntimeError("В аранжировке отсутствует запрошенная партия барабанов.")
                if speech_enabled and not arrangement["speech"]:
                    raise RuntimeError("В аранжировке отсутствует запрошенная речь.")
                return arrangement
            except RuntimeError as exc:
                LOGGER.warning("%s", exc)

                if attempt:
                    raise BotError(str(exc)) from exc

                correction = {"error": str(exc), "previous_json": content}

        raise AssertionError("Недостижимое состояние повторной аранжировки.")

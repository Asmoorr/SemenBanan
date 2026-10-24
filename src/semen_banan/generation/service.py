from __future__ import annotations

import logging
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
        score = await self._compose(conversation_context, current_message)
        arrangement = None

        if not options.solo:
            arrangement = await self._arrange(conversation_context, current_message, style_requests)

            if not options.speech:
                arrangement["speech"] = []

            if not options.drums:
                arrangement["drums"] = []

        try:
            audio = await self.audio.render(
                score, options.use_nano, arrangement, timeout=self.timeout
            )
        except RuntimeError as exc:
            raise BotError(str(exc)) from exc

        parts = ["пианино"]

        if arrangement is not None:
            if arrangement["drums"]:
                parts.append("барабаны")

            if arrangement["speech"]:
                parts.append("речь")

        if options.use_nano:
            parts.append("NanoMaestro")

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
    ) -> Arrangement:
        """Получает аранжировку и повторяет запрос при неверном JSON.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :return: Проверенная аранжировка.
        """
        correction: Correction | None = None

        for attempt in range(2):
            content = await self.gateway.arrange(
                conversation_context,
                current_message,
                style_requests=style_requests,
                correction=correction,
            )

            try:
                return parse_arrangement(content)
            except RuntimeError as exc:
                LOGGER.warning("%s", exc)

                if attempt:
                    raise BotError(str(exc)) from exc

                correction = {"error": str(exc), "previous_json": content}

        raise AssertionError("Недостижимое состояние повторной аранжировки.")

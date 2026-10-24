from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from semen_banan.audio.customization import AudioCustomization
from semen_banan.audio.models import ComposerKind
from semen_banan.conversation.models import (
    ContextMessage,
    ConversationContext,
    Correction,
    RoutingMetadata,
)
from semen_banan.conversation.ports import Gateway
from semen_banan.errors import BotError
from semen_banan.images.models import ImageOptions


class ReplyMode(StrEnum):
    """Поддерживаемые режимы обработки сообщения."""

    IGNORE = "ignore"
    TEXT = "text"
    MUSIC = "music"
    IMAGE = "image"
    VOICE = "voice"


class ReplyTrigger(StrEnum):
    """Смысловые причины ответа, определяемые моделью."""

    NONE = "none"
    DIRECT = "direct"
    CHAIN = "chain"
    REQUEST = "request"
    BANANA = "banana"
    SPONTANEOUS = "spontaneous"


@dataclass(frozen=True, slots=True)
class MusicOptions:
    """Проверенные параметры композитора и дополнительных дорожек."""

    composer: ComposerKind = ComposerKind.SCORE
    drums: bool = True
    speech: bool = True
    customization: AudioCustomization = field(default_factory=AudioCustomization)

    @property
    def use_nano(self) -> bool:
        """Проверяет, выбрана ли локальная музыкальная модель.

        :return: Признак выбора NanoMaestro.
        """
        return self.composer == ComposerKind.NANOMAESTRO

    @property
    def solo(self) -> bool:
        """Проверяет, отключены ли дополнительные аудиодорожки.

        :return: Признак записи только пианино.
        """
        return not self.drums and not self.speech

    def to_payload(self) -> dict[str, Any]:
        """Преобразует объект в данные для передачи через JSON.

        :return: Словарь с параметрами объекта.
        """
        return {
            "composer": self.composer.value,
            "drums": self.drums,
            "speech": self.speech,
            **self.customization.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Проверенный режим, параметры музыки или картинки и изменение характера."""

    mode: ReplyMode
    trigger: ReplyTrigger
    music: MusicOptions | None = None
    style_request: str | None = None
    image: ImageOptions | None = None
    load_participant_photos: bool = False

    def to_payload(self) -> dict[str, Any]:
        """Преобразует объект в данные для передачи через JSON.

        :return: Словарь с параметрами объекта.
        """
        parameters: dict[str, Any] | None = None
        if self.music is not None:
            parameters = self.music.to_payload()
        elif self.image is not None:
            parameters = self.image.to_payload()

        return {
            "mode": self.mode.value,
            "trigger": self.trigger.value,
            "parameters": parameters,
            "style_request": self.style_request,
            "load_participant_photos": self.load_participant_photos,
        }

    @classmethod
    def parse(cls, content: str) -> RouteDecision:
        """Проверяет JSON маршрутизации и создаёт типизированное решение.

        :param content: Текст JSON, полученный от модели.
        :return: Проверенный режим и допустимые параметры.
        """
        try:
            routing_data = json.loads(content)

            required_fields = {"mode", "trigger", "parameters", "style_request"}
            if (
                not isinstance(routing_data, dict)
                or not required_fields <= set(routing_data)
                or set(routing_data) - required_fields - {"load_participant_photos"}
            ):
                raise ValueError
            load_participant_photos = routing_data.get("load_participant_photos", False)
            if type(load_participant_photos) is not bool:
                raise ValueError

            mode = ReplyMode(routing_data["mode"])
            trigger = ReplyTrigger(routing_data["trigger"])
            style_request = routing_data["style_request"]

            if style_request is not None and (
                not isinstance(style_request, str) or not 1 <= len(style_request.strip()) <= 500
            ):
                raise ValueError

            if (mode == ReplyMode.IGNORE) != (trigger == ReplyTrigger.NONE):
                raise ValueError

            if trigger == ReplyTrigger.BANANA and (
                mode != ReplyMode.TEXT or style_request is not None
            ):
                raise ValueError

            if mode == ReplyMode.IGNORE and (style_request is not None or load_participant_photos):
                raise ValueError

            if trigger == ReplyTrigger.SPONTANEOUS and (
                mode not in {ReplyMode.TEXT, ReplyMode.VOICE}
                or style_request is not None
                or load_participant_photos
            ):
                raise ValueError
            if mode == ReplyMode.VOICE and trigger != ReplyTrigger.SPONTANEOUS:
                raise ValueError

            music = None
            image = None
            parameters = routing_data["parameters"]

            if mode == ReplyMode.MUSIC:
                if (
                    not isinstance(parameters, dict)
                    or not {"composer", "drums", "speech"} <= set(parameters)
                    or set(parameters)
                    - {
                        "composer",
                        "drums",
                        "speech",
                        "duration_seconds",
                        "tempo_bpm",
                        "instruments",
                        "volumes",
                        "voice_settings",
                    }
                ):
                    raise ValueError

                if type(parameters["drums"]) is not bool or type(parameters["speech"]) is not bool:
                    raise ValueError

                music = MusicOptions(
                    ComposerKind(parameters["composer"]),
                    parameters["drums"],
                    parameters["speech"],
                    AudioCustomization.parse(
                        {
                            key: value
                            for key, value in parameters.items()
                            if key not in {"composer", "drums", "speech"}
                        }
                    ),
                )
            elif mode == ReplyMode.IMAGE:
                image = ImageOptions.parse(parameters)
            elif parameters is not None:
                raise ValueError

            return cls(
                mode,
                trigger,
                music,
                style_request.strip() if style_request is not None else None,
                image,
                load_participant_photos,
            )
        except (ValueError, TypeError, KeyError):
            raise ValueError("Неверный режим или параметры маршрутизации.") from None


class MessageRouter:
    """Классификация сообщения через LLM с проверкой схемы ответа."""

    def __init__(self, gateway: Gateway) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param gateway: Клиент OpenClaw для работы с языковой моделью.
        :return: Не возвращает значение.
        """
        self.gateway = gateway

    async def route(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        metadata: RoutingMetadata,
        style_requests: list[str] | None = None,
    ) -> RouteDecision:
        """Определяет режим через LLM и при необходимости исправляет JSON.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param metadata: Признаки обращения, цепочки и личность бота.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :return: Проверенное решение маршрутизатора.
        """
        correction: Correction | None = None

        for attempt in range(2):
            content = await self.gateway.classify(
                conversation_context,
                current_message,
                metadata,
                style_requests=style_requests,
                correction=correction,
            )

            try:
                decision = RouteDecision.parse(content)
                if decision.trigger == ReplyTrigger.SPONTANEOUS or decision.mode == ReplyMode.VOICE:
                    raise ValueError("Случайный ответ и его формат выбирает приложение.")
                return decision
            except ValueError as exc:
                if attempt:
                    raise BotError("Модель дважды вернула неверный режим обработки.") from exc

                correction = {"error": str(exc), "previous_json": content[:4000]}

        raise AssertionError("Недостижимое состояние повторной маршрутизации.")

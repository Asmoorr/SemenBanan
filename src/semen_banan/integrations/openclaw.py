from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from semen_banan.config import Settings
from semen_banan.conversation.models import (
    ContextMessage,
    ConversationContext,
    Correction,
    RoutingMetadata,
)
from semen_banan.errors import BotError
from semen_banan.generation.prompts import PromptCatalog, load_prompts
from semen_banan.group import GroupCatalog


class OpenClawClient:
    """HTTP-адаптер запросов к языковой модели через OpenClaw Gateway."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        prompts: PromptCatalog | None = None,
        group: GroupCatalog | None = None,
    ) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param client: HTTP-клиент для внешнего сервиса.
        :param settings: Проверенные настройки приложения.
        :param prompts: Каталог промптов; None выбирает общий файл настроек.
        :param group: Постоянные сведения о группе и локальные фотографии.
        :return: Не возвращает значение.
        """
        self.client = client
        self.settings = settings
        self.prompts = prompts or load_prompts()
        self.group = group if group is not None else GroupCatalog.load()

    @property
    def persona(self) -> str:
        """Читает характер персонажа из общего каталога промптов.

        :return: Системная инструкция текстовых ответов.
        """
        return self.prompts.persona

    async def classify(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        metadata: RoutingMetadata,
        style_requests: list[str] | None = None,
        correction: Correction | None = None,
    ) -> str:
        """Запрашивает у модели режим обработки и параметры сообщения.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param metadata: Признаки обращения, цепочки и личность бота.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :param correction: Причина ошибки и предыдущий JSON для исправления.
        :return: JSON-ответ маршрутизатора модели.
        """
        return await self._complete(
            self.prompts.routing,
            json.dumps(
                {
                    "conversation_chain": conversation_context,
                    "current": current_message,
                    "metadata": metadata,
                    "character_requests": style_requests or [],
                    "correction": correction,
                },
                ensure_ascii=False,
            ),
            8000,
        )

    async def reply(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        style_requests: list[str] | None = None,
    ) -> str:
        """Получает текстовую реплику с учётом контекста и характера.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :return: Текст ответа Семёна.
        """
        return (
            await self._complete(
                self.persona,
                json.dumps(
                    {
                        "conversation_chain": conversation_context,
                        "reply_to": current_message,
                        "character_requests": style_requests or [],
                    },
                    ensure_ascii=False,
                ),
            )
        )[:1200]

    async def compose(
        self, conversation_context: ConversationContext, current_message: ContextMessage
    ) -> str:
        """Запрашивает у модели музыкальную партитуру.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :return: JSON партитуры для дальнейшей проверки.
        """
        system_prompt = self.prompts.composition

        return await self._complete(
            system_prompt,
            json.dumps(
                {"conversation_chain": conversation_context[-8:], "request": current_message},
                ensure_ascii=False,
            ),
            12000,
        )

    async def arrange(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        beats: int = 16,
        style_requests: list[str] | None = None,
        correction: Correction | None = None,
    ) -> str:
        """Запрашивает у модели барабаны и речевые фразы.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param beats: Длительность пьесы в музыкальных долях.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :param correction: Причина ошибки и предыдущий JSON для исправления.
        :return: JSON аранжировки для дальнейшей проверки.
        """
        system_prompt = self.prompts.arrangement(beats)

        return await self._complete(
            system_prompt,
            json.dumps(
                {
                    "conversation_chain": conversation_context[-4:],
                    "request": current_message,
                    "speech_style": self.persona,
                    "character_requests": style_requests or [],
                    "correction": correction,
                },
                ensure_ascii=False,
            ),
            6000,
        )

    def user_content(self, user_prompt: str) -> str | list[dict[str, Any]]:
        """Добавляет постоянные сведения о группе и запрошенные фотографии.

        :param user_prompt: JSON с контекстом конкретного запроса.
        :return: Текст JSON или мультимодальное содержимое с подписанными фото.
        """
        request_payload = json.loads(user_prompt)
        current_message = request_payload.get("reply_to", request_payload.get("request", {}))
        include_photos = (
            isinstance(current_message, dict)
            and current_message.get("load_participant_photos") is True
        )
        request_payload["group_profile"] = self.group.context()
        request_payload["participant_photos_loaded"] = include_photos
        text = json.dumps(request_payload, ensure_ascii=False)
        if not include_photos:
            return text

        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for index, photo in enumerate(self.group.photos(), 1):
            content.append(
                {
                    "type": "text",
                    "text": json.dumps(
                        {"photo_index": index, "participant_name": photo.name}, ensure_ascii=False
                    ),
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,"
                        + base64.b64encode(photo.data).decode("ascii"),
                        "detail": "high",
                    },
                }
            )
        return content

    async def _complete(
        self, system_prompt: str, user_prompt: str, character_limit: int = 1200
    ) -> str:
        """Отправляет запрос Gateway и проверяет текст ответа.

        :param system_prompt: Системная инструкция текущего режима.
        :param user_prompt: Пользовательские данные запроса в JSON.
        :param character_limit: Максимальная длина возвращаемого текста в символах.
        :return: Непустой текст ответа в пределах лимита.
        """
        headers = (
            {"Authorization": f"Bearer {self.settings.gateway_token}"}
            if self.settings.gateway_token
            else {}
        )
        # История передаётся явно, без постоянного ключа сессии модели.
        payload = {
            "model": f"openclaw/{self.settings.agent}",
            "stream": False,
            "tool_choice": "none",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt + "\n\n" + self.prompts.group_instructions,
                },
                {"role": "user", "content": self.user_content(user_prompt)},
            ],
        }
        gateway_base_url = self.settings.base_url
        endpoint = gateway_base_url + (
            "/chat/completions" if gateway_base_url.endswith("/v1") else "/v1/chat/completions"
        )

        try:
            response = await self.client.post(
                endpoint, json=payload, headers=headers, timeout=self.settings.timeout
            )
        except httpx.HTTPError:
            raise BotError("Gateway недоступен или истекло время ответа.") from None

        if response.status_code != 200:
            error_hint = {
                401: "проверь токен Gateway и авторизацию модели",
                403: "проверь доступ",
                404: "включи chatCompletions и проверь агента semyon",
            }.get(response.status_code, "проверь журнал OpenClaw")

            raise BotError(f"Gateway HTTP {response.status_code}: {error_hint}.")

        try:
            response_message = response.json()["choices"][0]["message"]
            content = response_message["content"]

            if (
                response_message.get("tool_calls")
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise BotError("Gateway вернул пустой ответ или вызов инструмента.") from None

        return content.strip()[:character_limit]

from __future__ import annotations

import json
from typing import Any

import httpx

from semen_banan.errors import BotError


class TelegramClient:
    """HTTP-адаптер получения и отправки сообщений Telegram."""

    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        """Инициализирует компонент и сохраняет его зависимости.

        :param client: HTTP-клиент для внешнего сервиса.
        :param token: Токен модели или Telegram API.
        :return: Не возвращает значение.
        """
        self.client = client
        self.url = f"https://api.telegram.org/bot{token}"

    async def call(self, method: str, **payload: Any) -> Any:
        """Выполняет запрос Telegram и проверяет ответ API.

        :param method: Имя метода Telegram API.
        :param payload: Именованные параметры запроса Telegram.
        :return: Результат метода Telegram; его структура зависит от метода.
        """
        try:
            response = await self.client.post(f"{self.url}/{method}", json=payload, timeout=40)
            response_data = response.json()
        except (httpx.HTTPError, ValueError):
            raise BotError(f"Telegram: сеть или неверный ответ ({method}).") from None

        if not response_data.get("ok"):
            error_code = response_data.get("error_code", response.status_code)
            error_hint = {
                401: "неверный токен",
                403: "бот удалён или нет прав",
                409: "другой процесс или webhook",
                429: "лимит запросов",
            }.get(error_code, "проверь настройки и права бота")

            raise BotError(f"Telegram {error_code}: {error_hint} ({method}).")

        return response_data["result"]

    async def send_voice(
        self, chat_id: int, message_id: int, voice: bytes, duration: int, topic: int = 0
    ) -> Any:
        """Отправляет голосовое ответом на исходное сообщение.

        :param chat_id: Идентификатор Telegram-группы.
        :param message_id: Идентификатор сообщения Telegram.
        :param voice: Байты голосового сообщения OGG/Opus.
        :param duration: Длительность записи в секундах.
        :param topic: Идентификатор темы группы, 0 для общего чата.
        :return: Ответ Telegram с данными отправленного сообщения.
        """
        form_fields = {
            "chat_id": str(chat_id),
            "duration": str(duration),
            "reply_parameters": json.dumps(
                {"message_id": message_id, "allow_sending_without_reply": False}
            ),
        }

        if topic:
            form_fields["message_thread_id"] = str(topic)

        try:
            response = await self.client.post(
                f"{self.url}/sendVoice",
                data=form_fields,
                files={"voice": ("semyon-piano.ogg", voice, "audio/ogg")},
                timeout=90,
            )
            response_data = response.json()
        except (httpx.HTTPError, ValueError):
            raise BotError("Telegram: не удалось отправить голосовое сообщение.") from None

        if not response_data.get("ok"):
            raise BotError(
                f"Telegram {response_data.get('error_code', response.status_code)}: ошибка отправки голосового."
            )

        return response_data["result"]

    async def send_photo(
        self, chat_id: int, message_id: int, photo: bytes, caption: str = "", topic: int = 0
    ) -> Any:
        """Отправляет подготовленную картинку ответом на исходное сообщение.

        :param chat_id: Идентификатор группы Telegram.
        :param message_id: Идентификатор сообщения, на которое отвечает бот.
        :param photo: Байты JPEG размером до десяти мегабайт.
        :param caption: Подпись картинки без разметки.
        :param topic: Тема группы, ноль для общего чата.
        :return: Данные отправленной картинки Telegram.
        """
        if not photo.startswith(b"\xff\xd8\xff") or len(photo) > 10 * 1024 * 1024:
            raise BotError("Картинка должна быть JPEG размером до 10 МБ.")
        form_fields = {
            "chat_id": str(chat_id),
            "caption": caption[:500],
            "reply_parameters": json.dumps(
                {"message_id": message_id, "allow_sending_without_reply": False}
            ),
        }
        if topic:
            form_fields["message_thread_id"] = str(topic)
        try:
            response = await self.client.post(
                f"{self.url}/sendPhoto",
                data=form_fields,
                files={"photo": ("semyon.jpg", photo, "image/jpeg")},
                timeout=90,
            )
            response_data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise BotError("Telegram: не удалось отправить картинку.") from error
        if not isinstance(response_data, dict) or not response_data.get("ok"):
            raise BotError("Telegram: ошибка отправки картинки.")
        return response_data["result"]

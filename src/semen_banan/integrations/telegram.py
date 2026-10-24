from __future__ import annotations

import json
from typing import Any

import httpx

from semen_banan.errors import BotError


class TelegramClient:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.url = f"https://api.telegram.org/bot{token}"

    async def call(self, method: str, **payload: Any) -> Any:
        try:
            response = await self.client.post(f"{self.url}/{method}", json=payload, timeout=40)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise BotError(f"Telegram: сеть или неверный ответ ({method}).") from None
        if not data.get("ok"):
            code = data.get("error_code", response.status_code)
            hint = {
                401: "неверный токен",
                403: "бот удалён или нет прав",
                409: "другой процесс или webhook",
                429: "лимит запросов",
            }.get(code, "проверь настройки и права бота")
            raise BotError(f"Telegram {code}: {hint} ({method}).")
        return data["result"]

    async def send_voice(
        self, chat_id: int, message_id: int, voice: bytes, duration: int, topic: int = 0
    ) -> Any:
        fields = {
            "chat_id": str(chat_id),
            "duration": str(duration),
            "reply_parameters": json.dumps(
                {"message_id": message_id, "allow_sending_without_reply": False}
            ),
        }
        if topic:
            fields["message_thread_id"] = str(topic)
        try:
            response = await self.client.post(
                f"{self.url}/sendVoice",
                data=fields,
                files={"voice": ("semyon-piano.ogg", voice, "audio/ogg")},
                timeout=90,
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise BotError("Telegram: не удалось отправить голосовое сообщение.") from None
        if not data.get("ok"):
            raise BotError(
                f"Telegram {data.get('error_code', response.status_code)}: ошибка отправки голосового."
            )
        return data["result"]

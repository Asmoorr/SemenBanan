from __future__ import annotations

import json
from importlib.resources import files

import httpx

from semen_banan.config import Settings
from semen_banan.errors import BotError
from semen_banan.generation.prompts import arrange_prompt, compose_prompt


class OpenClawClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.persona = (
            files("semen_banan.resources").joinpath("persona.txt").read_text(encoding="utf-8")
        )

    async def reply(
        self,
        context: list[dict[str, str]],
        current: dict[str, str],
        style_requests: list[str] | None = None,
    ) -> str:
        return (
            await self._complete(
                self.persona,
                json.dumps(
                    {
                        "conversation_chain": context,
                        "reply_to": current,
                        "character_requests": style_requests or [],
                    },
                    ensure_ascii=False,
                ),
            )
        )[:1200]

    async def compose(self, context: list[dict[str, str]], current: dict[str, str]) -> str:
        system = compose_prompt()
        return await self._complete(
            system,
            json.dumps(
                {"conversation_chain": context[-8:], "request": current}, ensure_ascii=False
            ),
            12000,
        )

    async def arrange(
        self,
        context: list[dict[str, str]],
        current: dict[str, str],
        beats: int = 16,
        style_requests: list[str] | None = None,
        correction: dict[str, str] | None = None,
    ) -> str:
        system = arrange_prompt(beats)
        return await self._complete(
            system,
            json.dumps(
                {
                    "conversation_chain": context[-4:],
                    "request": current,
                    "speech_style": self.persona,
                    "character_requests": style_requests or [],
                    "correction": correction,
                },
                ensure_ascii=False,
            ),
            6000,
        )

    async def _complete(self, system: str, user: str, limit: int = 1200) -> str:
        headers = (
            {"Authorization": f"Bearer {self.settings.gateway_token}"}
            if self.settings.gateway_token
            else {}
        )
        # No stable user/session key: persisted chain context is supplied explicitly.
        payload = {
            "model": f"openclaw/{self.settings.agent}",
            "stream": False,
            "tool_choice": "none",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        base = self.settings.base_url
        endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        try:
            response = await self.client.post(
                endpoint, json=payload, headers=headers, timeout=self.settings.timeout
            )
        except httpx.HTTPError:
            raise BotError("Gateway недоступен или истекло время ответа.") from None
        if response.status_code != 200:
            hint = {
                401: "проверь токен Gateway и авторизацию модели",
                403: "проверь доступ",
                404: "включи chatCompletions и проверь агента semyon",
            }.get(response.status_code, "проверь журнал OpenClaw")
            raise BotError(f"Gateway HTTP {response.status_code}: {hint}.")
        try:
            message = response.json()["choices"][0]["message"]
            content = message["content"]
            if message.get("tool_calls") or not isinstance(content, str) or not content.strip():
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise BotError("Gateway вернул пустой ответ или вызов инструмента.") from None
        return content.strip()[:limit]

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from semen_banan.errors import BotError


@dataclass(frozen=True, slots=True)
class AppPaths:
    home: Path

    @classmethod
    def load(cls) -> AppPaths:
        configured = os.getenv("SEMEN_BANAN_HOME")
        if configured:
            return cls(Path(configured).expanduser().resolve())
        for parent in Path(__file__).resolve().parents:
            if (parent / "pyproject.toml").is_file() and (parent / "src/semen_banan").is_dir():
                return cls(parent)
        return cls(Path.cwd().resolve())

    @property
    def assets(self) -> Path:
        return self.home / "assets"

    @property
    def state(self) -> Path:
        return self.home / "state.json"

    @property
    def database(self) -> Path:
        return self.home / "memory.sqlite3"

    @property
    def runtime(self) -> Path:
        return self.home / ".runtime"


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    chats: frozenset[int]
    base_url: str
    gateway_token: str
    agent: str = "semyon"
    cooldown: float = 10
    probability: float = 0.25
    timeout: float = 90
    audio_timeout: float = 90

    @classmethod
    def load(cls, paths: AppPaths | None = None) -> Settings:
        load_dotenv((paths or AppPaths.load()).home / ".env")
        try:
            settings = cls(
                token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
                chats=frozenset(
                    int(v.strip())
                    for v in os.getenv("ALLOWED_CHAT_IDS", "").split(",")
                    if v.strip()
                ),
                base_url=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/"),
                gateway_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip(),
                agent=os.getenv("OPENCLAW_AGENT_ID", "semyon").strip(),
                cooldown=float(os.getenv("COOLDOWN_SECONDS", "10")),
                probability=float(os.getenv("BANANA_PROBABILITY", "0.25")),
                timeout=float(os.getenv("REQUEST_TIMEOUT", "90")),
                audio_timeout=float(os.getenv("AUDIO_TIMEOUT_SECONDS", "90")),
            )
        except ValueError:
            raise BotError("Проверь числовые значения в .env.") from None
        if not all(
            math.isfinite(v)
            for v in (
                settings.cooldown,
                settings.probability,
                settings.timeout,
                settings.audio_timeout,
            )
        ):
            raise BotError("Числовые настройки должны быть конечными.")
        if (
            settings.cooldown < 0
            or not 0 <= settings.probability <= 1
            or settings.timeout <= 0
            or settings.audio_timeout <= 0
        ):
            raise BotError("Неверные интервалы или вероятность в .env.")
        parsed = urlsplit(settings.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise BotError("OPENCLAW_BASE_URL должен быть HTTP(S)-адресом без токена.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", settings.agent):
            raise BotError("Неверный OPENCLAW_AGENT_ID.")
        return settings

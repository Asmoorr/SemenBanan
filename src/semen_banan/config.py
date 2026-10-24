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
    """Пути к настройкам, данным и локальным ресурсам приложения."""

    home: Path

    @classmethod
    def load(cls) -> AppPaths:
        """Определяет рабочий каталог из окружения или расположения проекта.

        :return: Пути к данным текущего экземпляра приложения.
        """
        configured_home = os.getenv("SEMEN_BANAN_HOME")

        if configured_home:
            return cls(Path(configured_home).expanduser().resolve())

        for parent in Path(__file__).resolve().parents:
            if (parent / "pyproject.toml").is_file() and (parent / "src/semen_banan").is_dir():
                return cls(parent)

        return cls(Path.cwd().resolve())

    @property
    def assets(self) -> Path:
        """Определяет каталог локальных музыкальных ресурсов.

        :return: Путь к моделям и звуковым банкам.
        """
        return self.home / "assets"

    @property
    def state(self) -> Path:
        """Определяет файл сохранённых интервалов.

        :return: Путь к файлу state.json.
        """
        return self.home / "state.json"

    @property
    def database(self) -> Path:
        """Определяет файл истории и очереди ответов.

        :return: Путь к базе SQLite.
        """
        return self.home / "memory.sqlite3"

    @property
    def runtime(self) -> Path:
        """Определяет каталог временных рабочих результатов.

        :return: Путь к рабочему каталогу .runtime.
        """
        return self.home / ".runtime"


@dataclass(frozen=True, slots=True)
class Settings:
    """Проверенные параметры запуска и подключения внешних сервисов."""

    token: str
    chats: frozenset[int]
    base_url: str
    gateway_token: str
    agent: str = "semyon"
    cooldown: float = 10
    timeout: float = 90
    audio_timeout: float = 90
    image_timeout: float = 180
    image_model: str = "openai/gpt-image-2"
    image_executable: str = "openclaw"
    image_wsl_distro: str = ""
    spontaneous_probability: float = 0.05
    spontaneous_voice_probability: float = 0.2
    reaction_probability: float = 0.1
    addressed_reaction_probability: float = 1 / 3

    @classmethod
    def load(cls, paths: AppPaths | None = None) -> Settings:
        """Читает окружение и проверяет параметры запуска.

        :param paths: Пути к рабочим данным приложения.
        :return: Проверенные настройки приложения.
        """
        load_dotenv((paths or AppPaths.load()).home / ".env")

        try:
            settings = cls(
                token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
                chats=frozenset(
                    int(configured_value.strip())
                    for configured_value in os.getenv("ALLOWED_CHAT_IDS", "").split(",")
                    if configured_value.strip()
                ),
                base_url=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/"),
                gateway_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip(),
                agent=os.getenv("OPENCLAW_AGENT_ID", "semyon").strip(),
                cooldown=float(os.getenv("COOLDOWN_SECONDS", "10")),
                timeout=float(os.getenv("REQUEST_TIMEOUT", "90")),
                audio_timeout=float(os.getenv("AUDIO_TIMEOUT_SECONDS", "90")),
                image_timeout=float(os.getenv("IMAGE_TIMEOUT_SECONDS", "180")),
                image_model=os.getenv("OPENCLAW_IMAGE_MODEL", "openai/gpt-image-2").strip(),
                image_executable=os.getenv("OPENCLAW_IMAGE_EXECUTABLE", "openclaw").strip(),
                image_wsl_distro=os.getenv("OPENCLAW_IMAGE_WSL_DISTRO", "").strip(),
                reaction_probability=float(os.getenv("REACTION_PROBABILITY", "0.1")),
                addressed_reaction_probability=float(
                    os.getenv("ADDRESSED_REACTION_PROBABILITY", str(1 / 3))
                ),
                spontaneous_probability=float(os.getenv("SPONTANEOUS_REPLY_PROBABILITY", "0.05")),
                spontaneous_voice_probability=float(
                    os.getenv("SPONTANEOUS_VOICE_PROBABILITY", "0.2")
                ),
            )
        except ValueError:
            raise BotError("Проверь числовые значения в .env.") from None

        if not all(
            math.isfinite(configured_value)
            for configured_value in (
                settings.cooldown,
                settings.timeout,
                settings.audio_timeout,
                settings.image_timeout,
                settings.spontaneous_probability,
                settings.reaction_probability,
                settings.addressed_reaction_probability,
                settings.spontaneous_voice_probability,
            )
        ):
            raise BotError("Числовые настройки должны быть конечными.")

        if (
            settings.cooldown < 0
            or settings.timeout <= 0
            or settings.audio_timeout <= 0
            or not 10 <= settings.image_timeout <= 600
            or not 0 <= settings.spontaneous_probability <= 1
            or not 0 <= settings.spontaneous_voice_probability <= 1
            or not 0 <= settings.reaction_probability <= 1
            or not 0 <= settings.addressed_reaction_probability <= 1
        ):
            raise BotError("Неверные интервалы или вероятность в .env.")

        gateway_address = urlsplit(settings.base_url)

        if (
            gateway_address.scheme not in {"http", "https"}
            or not gateway_address.hostname
            or gateway_address.username
            or gateway_address.query
            or gateway_address.fragment
        ):
            raise BotError("OPENCLAW_BASE_URL должен быть HTTP(S)-адресом без токена.")

        if not re.fullmatch(r"[a-zA-Z0-9_-]+", settings.agent):
            raise BotError("Неверный OPENCLAW_AGENT_ID.")

        if not settings.image_model or not settings.image_executable:
            raise BotError("Укажи модель и исполняемый файл OpenClaw для картинок.")

        return settings

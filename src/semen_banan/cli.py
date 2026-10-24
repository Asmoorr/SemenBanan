from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from semen_banan.bootstrap import run
from semen_banan.errors import BotError


def main() -> None:
    """Разбирает аргументы и запускает выбранную операцию.

    :return: Не возвращает значение.
    """
    parser = argparse.ArgumentParser(
        description="Семён: Telegram-бот с OpenClaw и локальной генерацией музыки."
    )
    mode_arguments = parser.add_mutually_exclusive_group()
    mode_arguments.add_argument(
        "--discover-chats", action="store_true", help="Вывести ID групп без отправки сообщений"
    )
    mode_arguments.add_argument("--check", action="store_true", help="Проверить Telegram и Gateway")
    mode_arguments.add_argument(
        "--check-gateway", action="store_true", help="Проверить только Gateway"
    )
    mode_arguments.add_argument(
        "--check-music", action="store_true", help="Создать музыкальный OGG без отправки в Telegram"
    )
    mode_arguments.add_argument(
        "--check-image", action="store_true", help="Создать картинку без отправки в Telegram"
    )
    parser.add_argument(
        "--output", type=Path, help="Файл OGG для --check-music или JPEG для --check-image"
    )
    parser.add_argument(
        "--request",
        default=None,
        help="Просьба для --check-music или --check-image",
    )
    arguments = parser.parse_args()

    if arguments.output is not None and not (arguments.check_music or arguments.check_image):
        parser.error("--output используется только с --check-music или --check-image")

    mode = next(
        (
            name
            for name in ("discover-chats", "check-gateway", "check-music", "check-image", "check")
            if getattr(arguments, name.replace("-", "_"))
        ),
        "run",
    )
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("semen_banan").setLevel(logging.INFO)

    try:
        asyncio.run(run(mode, arguments.output, arguments.request))
    except KeyboardInterrupt:
        print("Семён спит.")
    except (BotError, OSError) as exc:
        print(f"Не удалось продолжить: {exc}")

        raise SystemExit(1) from None

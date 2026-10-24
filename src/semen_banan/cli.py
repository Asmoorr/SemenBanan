from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from semen_banan.bootstrap import run
from semen_banan.errors import BotError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Семён: Telegram-бот с OpenClaw и локальной генерацией музыки."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--discover-chats", action="store_true", help="Вывести ID групп без отправки сообщений"
    )
    modes.add_argument("--check", action="store_true", help="Проверить Telegram и Gateway")
    modes.add_argument("--check-gateway", action="store_true", help="Проверить только Gateway")
    modes.add_argument(
        "--check-music", action="store_true", help="Создать музыкальный OGG без отправки в Telegram"
    )
    parser.add_argument("--output", type=Path, help="Файл OGG для --check-music")
    parser.add_argument(
        "--request",
        default="Семён, сыграй весёлую мелодию про бананы",
        help="Музыкальная просьба для --check-music",
    )
    args = parser.parse_args()
    if args.output is not None and not args.check_music:
        parser.error("--output используется только с --check-music")
    mode = next(
        (
            name
            for name in ("discover-chats", "check-gateway", "check-music", "check")
            if getattr(args, name.replace("-", "_"))
        ),
        "run",
    )
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("semen_banan").setLevel(logging.INFO)
    try:
        asyncio.run(run(mode, args.output, args.request))
    except KeyboardInterrupt:
        print("Семён спит.")
    except (BotError, OSError) as exc:
        print(f"Не удалось продолжить: {exc}")
        raise SystemExit(1) from None

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from semen_banan.config import AppPaths, Settings
from semen_banan.errors import BotError
from semen_banan.images.models import ImageOptions, ImageReply
from semen_banan.processes import stop_worker

LOGGER = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ImageGenerationError(BotError):
    """Ошибка генерации, которую следует показать пользователю без автоповтора."""


def prepare_photo(source: Path, destination: Path) -> None:
    """Проверяет изображение и сохраняет фото в формате Telegram.

    :param source: Файл, созданный OpenClaw в каталоге задания.
    :param destination: Путь подготовленного JPEG в кеше приложения.
    :return: Не возвращает значение.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        if not source.is_file() or not 0 < source.stat().st_size <= 40 * 1024 * 1024:
            raise ValueError
        with Image.open(source) as image:
            if (
                image.format not in {"PNG", "JPEG", "WEBP"}
                or image.width * image.height > 20_000_000
            ):
                raise ValueError
            if max(image.size) / min(image.size) > 20:
                raise ValueError
            image.load()
            oriented = ImageOps.exif_transpose(image).convert("RGBA")
            background = Image.new("RGBA", oriented.size, "white")
            background.alpha_composite(oriented)
            prepared = background.convert("RGB")
            prepared.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            temporary = destination.with_suffix(".tmp")
            prepared.save(temporary, format="JPEG", quality=92, optimize=True)
            if not 0 < temporary.stat().st_size <= MAX_IMAGE_BYTES:
                temporary.unlink(missing_ok=True)
                raise ValueError
            temporary.replace(destination)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageGenerationError(
            "OpenClaw вернул повреждённую или неподдерживаемую картинку."
        ) from error


class OpenClawImageGenerator:
    """Генерация через штатную команду OpenClaw с кешем повторной отправки."""

    def __init__(self, paths: AppPaths, settings: Settings) -> None:
        """Сохраняет настройки исполнения и каталог готовых изображений.

        :param paths: Пути к данным экземпляра приложения.
        :param settings: Модель, таймаут и расположение OpenClaw.
        :return: Не возвращает значение.
        """
        self.settings = settings
        self.directory = paths.runtime / "images"
        self.directory.mkdir(parents=True, exist_ok=True)

    def output_paths(self, output: Path) -> tuple[str, Path]:
        """Сопоставляет путь OpenClaw и путь чтения файла приложением.

        :param output: Локальный путь временного файла задания.
        :return: Путь для команды и путь чтения результата в Windows или Linux.
        """
        if not self.settings.image_wsl_distro:
            return str(output.resolve()), output
        if os.name != "nt":
            raise ImageGenerationError("WSL для картинок настраивается только в Windows.")
        linux_path = f"/tmp/semen-banan-{output.parent.name}-{output.name}"
        return linux_path, Path(f"//wsl.localhost/{self.settings.image_wsl_distro}{linux_path}")

    def command(self, options: ImageOptions, output: Path) -> list[str]:
        """Строит список аргументов без оболочки и исполнения текста пользователя.

        :param options: Проверенные параметры изображения.
        :param output: Абсолютный путь файла результата.
        :return: Аргументы штатной команды OpenClaw для текущей платформы.
        """
        output_path, _ = self.output_paths(output)
        prefix: list[str] = []
        if self.settings.image_wsl_distro:
            prefix = [
                "wsl.exe",
                "-d",
                self.settings.image_wsl_distro,
                "--",
                "timeout",
                "--kill-after=5",
                str(int(self.settings.image_timeout) + 15),
            ]

        return prefix + [
            self.settings.image_executable,
            "infer",
            "image",
            "generate",
            "--agent",
            self.settings.agent,
            "--model",
            self.settings.image_model,
            "--prompt",
            options.prompt,
            "--size",
            options.size,
            "--count",
            "1",
            "--output-format",
            "png",
            "--quality",
            "medium",
            "--timeout-ms",
            str(round(self.settings.image_timeout * 1000)),
            "--output",
            output_path,
            "--json",
        ]

    def cleanup(self) -> None:
        """Удаляет только созданные приложением фото старше семи суток.

        :return: Не возвращает значение.
        """
        threshold = time.time() - 7 * 86400
        for path in self.directory.glob("*.jpg"):
            if len(path.stem) != 64 or any(
                character not in "0123456789abcdef" for character in path.stem
            ):
                continue
            if not path.is_symlink() and path.is_file() and path.stat().st_mtime < threshold:
                path.unlink()

    async def generate(self, options: ImageOptions, job_key: str) -> ImageReply:
        """Создаёт картинку или использует результат предыдущей попытки отправки.

        :param options: Описание, размер и подпись изображения.
        :param job_key: Идентификатор исходного сообщения или диагностического задания.
        :return: Проверенное фото с подписью и описанием для истории.
        """
        self.cleanup()
        digest = hashlib.sha256(
            json.dumps(
                [job_key, self.settings.image_model, options.to_payload()],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        destination = self.directory / f"{digest}.jpg"
        if not destination.exists():
            with tempfile.TemporaryDirectory(
                prefix="generation-", dir=self.directory
            ) as temporary_directory:
                source = Path(temporary_directory) / "image.png"
                _, readable_source = self.output_paths(source)
                process = None
                try:
                    process = await asyncio.create_subprocess_exec(
                        *self.command(options, source),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                        start_new_session=os.name != "nt",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    await asyncio.wait_for(process.wait(), timeout=self.settings.image_timeout + 30)
                    if process.returncode != 0:
                        LOGGER.warning(
                            "OpenClaw не создал картинку: код завершения %s", process.returncode
                        )
                        raise ImageGenerationError(
                            "Не удалось создать картинку через OpenClaw. Попробуй изменить описание; если ошибка повторяется, проверь генератор изображений."
                        )
                    prepare_photo(readable_source, destination)
                except TimeoutError as error:
                    raise ImageGenerationError(
                        "OpenClaw не успел создать картинку. Попробуй ещё раз позже."
                    ) from error
                except OSError as error:
                    raise ImageGenerationError(
                        "Не удалось запустить генератор картинок OpenClaw. Проверь его установку и настройки."
                    ) from error
                finally:
                    if process is not None and process.returncode is None:
                        await stop_worker(process)
                    if self.settings.image_wsl_distro:
                        try:
                            readable_source.unlink(missing_ok=True)
                        except OSError:
                            LOGGER.warning("Не удалось удалить временную картинку в WSL.")
        if destination.is_symlink() or not 0 < destination.stat().st_size <= MAX_IMAGE_BYTES:
            raise ImageGenerationError("Сохранённая картинка повреждена.")
        return ImageReply(
            destination, options.caption, f"[Семён нарисовал: {options.prompt[:1000]}]"
        )

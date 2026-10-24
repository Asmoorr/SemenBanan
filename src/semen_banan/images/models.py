from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ImageOptions:
    """Проверенное описание одного создаваемого изображения."""

    prompt: str
    size: str = "1024x1024"
    caption: str = ""

    def __post_init__(self) -> None:
        """Проверяет описание, размер и подпись, полученные от LLM.

        :return: Не возвращает значение.
        """
        if not isinstance(self.prompt, str) or not 1 <= len(self.prompt.strip()) <= 4000:
            raise ValueError("Описание картинки должно содержать от 1 до 4000 символов.")
        if self.size not in ("1024x1024", "1536x1024", "1024x1536"):
            raise ValueError("Неподдерживаемый размер картинки.")
        if not isinstance(self.caption, str) or len(self.caption) > 500:
            raise ValueError("Подпись картинки должна быть строкой до 500 символов.")

    def to_payload(self) -> dict[str, Any]:
        """Готовит параметры для сохранения в очереди.

        :return: Сериализуемый словарь параметров.
        """
        return asdict(self)

    @classmethod
    def parse(cls, payload: object) -> ImageOptions:
        """Создаёт параметры картинки из строгого JSON-объекта.

        :param payload: Параметры изображения от модели или очереди.
        :return: Проверенные параметры картинки.
        """
        if not isinstance(payload, dict) or set(payload) != {"prompt", "size", "caption"}:
            raise ValueError("Неверные параметры генерации картинки.")
        return cls(payload["prompt"], payload["size"], payload["caption"])


@dataclass(frozen=True, slots=True)
class ImageReply:
    """Подготовленное фото и его описание для Telegram и истории."""

    path: Path
    caption: str
    description: str

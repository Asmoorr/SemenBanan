from __future__ import annotations

import io
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semen_banan.config import AppPaths
from semen_banan.errors import BotError


class ParticipantPhotosError(BotError):
    """Недоступные фотографии, которые модель явно запросила для ответа."""


@dataclass(frozen=True, slots=True)
class Participant:
    """Сведения об участнике, сообщённые владельцем группы."""

    identifier: str
    name: str
    aliases: tuple[str, ...]
    roles: tuple[str, ...]
    facts: tuple[str, ...]
    photo: Path


@dataclass(frozen=True, slots=True)
class ParticipantPhoto:
    """Подписанная фотография для передачи модели или генератору."""

    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class GroupCatalog:
    """Редактируемый справочник группы с отдельной загрузкой фотографий."""

    name: str = ""
    description: str = ""
    members: tuple[Participant, ...] = ()

    @classmethod
    def load(cls, paths: AppPaths | None = None) -> GroupCatalog:
        """Читает сведения из group.toml, не загружая содержимое фотографий.

        :param paths: Пути экземпляра приложения; по умолчанию используются текущие.
        :return: Справочник либо пустой каталог, если группа ещё не настроена.
        """
        home = (paths or AppPaths.load()).home
        configuration_path = home / "group.toml"
        if not configuration_path.exists():
            return cls()
        try:
            configuration = tomllib.loads(configuration_path.read_text(encoding="utf-8"))
            name = configuration["name"]
            description = configuration["description"]
            if not isinstance(name, str) or not isinstance(description, str):
                raise ValueError
            photo_directory = (home / "assets/participants").resolve()
            members = []
            for item in configuration["members"]:
                if any(
                    not isinstance(item[key], str) or not item[key].strip()
                    for key in ("id", "name", "photo")
                ):
                    raise ValueError
                for key in ("aliases", "roles", "facts"):
                    if not isinstance(item[key], list) or any(
                        not isinstance(value, str) for value in item[key]
                    ):
                        raise ValueError
                photo = (photo_directory / item["photo"]).resolve()
                if not photo.is_relative_to(photo_directory):
                    raise ValueError
                members.append(
                    Participant(
                        item["id"],
                        item["name"],
                        tuple(item["aliases"]),
                        tuple(item["roles"]),
                        tuple(item["facts"]),
                        photo,
                    )
                )
            if len(members) > 5 or len({member.identifier for member in members}) != len(members):
                raise ValueError
            return cls(name, description, tuple(members))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise BotError(
                "Не удалось прочитать group.toml: проверь сведения об участниках и пути фотографий."
            ) from error

    def context(self) -> dict[str, Any]:
        """Готовит постоянный текстовый контекст без байтов фотографий.

        :return: Название группы и факты об участниках с номерами их фото.
        """
        return {
            "name": self.name,
            "description": self.description,
            "members": [
                {
                    "id": member.identifier,
                    "name": member.name,
                    "aliases": list(member.aliases),
                    "roles": list(member.roles),
                    "facts": list(member.facts),
                    "photo_index": index,
                    "photo_available": member.photo.is_file(),
                }
                for index, member in enumerate(self.members, 1)
            ],
        }

    def photos(self) -> tuple[ParticipantPhoto, ...]:
        """Загружает все фотографии только после явного решения модели.

        :return: Фотографии JPEG в том же порядке, что участники справочника.
        """
        from PIL import Image, ImageOps

        if not self.members:
            raise ParticipantPhotosError("Фотографии участников пока не настроены.")
        photos = []
        for member in self.members:
            try:
                if not 0 < member.photo.stat().st_size <= 40 * 1024 * 1024:
                    raise ValueError
                with Image.open(member.photo) as image:
                    if image.width * image.height > 20_000_000:
                        raise ValueError
                    prepared = ImageOps.exif_transpose(image).convert("RGB")
                    prepared.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    output = io.BytesIO()
                    prepared.save(output, format="JPEG", quality=85, optimize=True)
                    photos.append(ParticipantPhoto(member.name, output.getvalue()))
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                raise ParticipantPhotosError(
                    f"Не удалось загрузить фото участника: {member.name}."
                ) from error
        return tuple(photos)

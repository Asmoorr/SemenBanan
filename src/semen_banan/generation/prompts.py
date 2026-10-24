from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from string import Template

from semen_banan.errors import BotError


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    """Единый каталог инструкций модели и шаблонов проверочных запросов."""

    group_instructions: str
    participant_image_template: str
    context_notice: str
    persona: str
    routing: str
    composition: str
    arrangement_template: str
    short_speech: str
    long_speech: str
    gateway_request: str
    image_request: str
    music_request: str
    comparison_request: str
    comparison_forms: tuple[str, ...]
    comparison_section_template: str
    comparison_arrangement_template: str

    @classmethod
    def load(cls, path: Path | None = None) -> PromptCatalog:
        """Читает единый TOML-файл и проверяет обязательные промпты.

        :param path: Путь к файлу настроек или хранилища.
        :return: Проверенный каталог промптов.
        """
        try:
            prompt_source = (
                path.read_text(encoding="utf-8")
                if path is not None
                else files("semen_banan.resources")
                .joinpath("prompts.toml")
                .read_text(encoding="utf-8")
            )
            configuration = tomllib.loads(prompt_source)

            def read_text(section: str, name: str) -> str:
                """Читает обязательную непустую текстовую настройку промпта.

                :param section: Раздел конфигурации промптов.
                :param name: Имя обязательной текстовой настройки.
                :return: Строка настройки без изменения её содержания.
                """
                configured_prompt = configuration[section][name]

                if not isinstance(configured_prompt, str) or not configured_prompt.strip():
                    raise ValueError(f"Пустой или неверный промпт: {section}.{name}.")

                return configured_prompt

            section_goals = configuration["comparison"]["forms"]

            if (
                not isinstance(section_goals, list)
                or len(section_goals) != 4
                or any(not isinstance(item, str) or not item.strip() for item in section_goals)
            ):
                raise ValueError("Нужно задать четыре этапа музыкального сравнения.")

            prompt_catalog = cls(
                context_notice=read_text("context", "truncation_notice"),
                group_instructions=read_text("group", "system"),
                participant_image_template=read_text("group", "image_template"),
                persona=read_text("persona", "system"),
                routing=read_text("routing", "system"),
                composition=read_text("composition", "system"),
                arrangement_template=read_text("arrangement", "system"),
                short_speech=read_text("arrangement", "short_speech"),
                long_speech=read_text("arrangement", "long_speech"),
                gateway_request=read_text("diagnostics", "gateway_request"),
                music_request=read_text("diagnostics", "music_request"),
                image_request=read_text("diagnostics", "image_request"),
                comparison_request=read_text("comparison", "request"),
                comparison_forms=tuple(section_goals),
                comparison_section_template=read_text("comparison", "section"),
                comparison_arrangement_template=read_text("comparison", "arrangement"),
            )
            prompt_catalog.validate_templates()

            return prompt_catalog
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise BotError(
                "Не удалось загрузить prompts.toml: проверь разделы и шаблоны промптов."
            ) from error

    def validate_templates(self) -> None:
        """Проверяет набор подстановок в шаблонах промптов.

        :return: Не возвращает значение.
        """
        templates = (
            (self.participant_image_template, {"request", "group_profile", "photos_loaded"}),
            (self.arrangement_template, {"total_beats", "last_speech_beat", "speech_guidance"}),
            (
                self.comparison_section_template,
                {"request", "tempo", "first_bar", "last_bar", "total_bars", "section_goal"},
            ),
            (self.comparison_arrangement_template, {"request"}),
        )

        for prompt_source, expected_parameters in templates:
            template = Template(prompt_source)

            if not template.is_valid() or set(template.get_identifiers()) != expected_parameters:
                raise ValueError("Неверные подстановки в шаблоне промпта.")

    def arrangement(self, total_beats: int) -> str:
        """Подставляет длительность и ограничения речи в промпт аранжировки.

        :param total_beats: Общее количество долей пьесы.
        :return: Системная инструкция для указанной длины пьесы.
        """
        return Template(self.arrangement_template).substitute(
            total_beats=total_beats,
            last_speech_beat=total_beats - 4,
            speech_guidance=self.short_speech if total_beats <= 16 else self.long_speech,
        )

    def comparison_section(
        self, request: str, tempo: int, section_index: int, total_bars: int
    ) -> str:
        """Готовит запрос на очередной фрагмент музыкального сравнения.

        :param request: Исходная просьба или задание генерации.
        :param tempo: Темп пьесы в ударах в минуту.
        :param section_index: Номер фрагмента, начиная с нуля.
        :param total_bars: Общее количество тактов сравниваемой пьесы.
        :return: Текст запроса с этапом развития пьесы.
        """
        section_goal_index = (
            3 if section_index == total_bars // 4 - 1 and section_index else section_index
        )

        return Template(self.comparison_section_template).substitute(
            request=request,
            tempo=tempo,
            first_bar=section_index * 4 + 1,
            last_bar=section_index * 4 + 4,
            total_bars=total_bars,
            section_goal=self.comparison_forms[section_goal_index],
        )

    def comparison_arrangement(self, request: str) -> str:
        """Готовит запрос дополнительных дорожек для сравнения.

        :param request: Исходная просьба или задание генерации.
        :return: Текст запроса аранжировки.
        """
        return Template(self.comparison_arrangement_template).substitute(request=request)


@lru_cache(maxsize=1)
def load_prompts() -> PromptCatalog:
    """Загружает единый каталог промптов и кеширует его до перезапуска.

    :return: Проверенный каталог инструкций модели.
    """
    return PromptCatalog.load()

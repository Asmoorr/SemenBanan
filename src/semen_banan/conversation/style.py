from __future__ import annotations

import re

_TRANSLATION = str.maketrans({**dict.fromkeys("«»“”„‟❝❞〝〞", '"'), **dict.fromkeys("—–―‒", "-")})
_ENDING_PERIODS = re.compile(r"(\.+)([\"')\]]*)[ \t]*(?=\n|$)")


def is_reply_style_valid(text: str) -> bool:
    """Проверяет кавычки, длинные тире и завершающие точки без требования скобочки.

    :param text: Реплика или подпись перед отправкой.
    :return: Признак соответствия обязательным правилам оформления.
    """
    return (
        not any(ord(character) in _TRANSLATION for character in text)
        and _ENDING_PERIODS.search(text) is None
    )


def normalize_reply_style(text: str) -> str:
    """Исправляет кавычки, длинное тире и точки в конце абзацев.

    :param text: Готовая реплика, подпись или текст для озвучивания.
    :return: Текст с прямыми кавычками, дефисом и без завершающих точек.
    """
    cleaned = text.replace("\r\n", "\n").strip()
    if is_reply_style_valid(cleaned):
        return cleaned
    normalized = cleaned.translate(_TRANSLATION)

    def replace_ending(match: re.Match[str]) -> str:
        """Сохраняет смысл многоточия и закрывающие кавычки или скобки.

        :param match: Завершающие точки строки и закрывающие символы.
        :return: Закрывающие символы с многоточием при необходимости.
        """
        return ("…" if len(match[1]) >= 3 else "") + match[2]

    return _ENDING_PERIODS.sub(replace_ending, normalized)

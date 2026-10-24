from __future__ import annotations

import re
from typing import Any

NAME = re.compile(r"(?<![\w@])(?:семен|семён(?:а|у|ом|е)?|сеня|сень|сенечка)(?!\w)", re.I)
BANANA = re.compile(r"(?<!\w)(?:банан[а-яё]*|bananas?)(?!\w)|🍌", re.I)


STYLE_CHANGE = re.compile(
    r"(?:\b(?:поменя\w*|измени\w*|смен[иья]\w*|настро\w*|перестань|начни|будь|стань)\b"
    r".{0,90}\b(?:характер\w*|стил\w*|манер\w*|поведен\w*|шут\w*|мат\w*|добр\w*|злее|мягче|грубее|дерзче|агрессивн\w*|вес[её]л\w*|спокойн\w*|серь[её]зн\w*|ироничн\w*|саркастичн\w*|приветлив\w*|токсичн\w*|мрачн\w*|ж[её]стч\w*|смешн\w*)\b)"
    r"|(?:\b(?:характер\w*|стил\w*|манер\w*|поведен\w*)\b.{0,90}"
    r"\b(?:поменя\w*|измен\w*|смен\w*|друг\w*)\b)"
    r"|(?:\b(?:без мата|не матерись|меньше мата|больше мата)\b)",
    re.I | re.S,
)


PLAY_REQUEST = re.compile(r"\b(?:сыграй|наиграй|поиграй|исполни)\b", re.I)
COMPOSE_REQUEST = re.compile(r"\b(?:сочини|придумай|напиши|сделай|создай)\b", re.I)
MUSIC_NOUN = re.compile(
    r"\b(?:пианино|роял[ьяе]?|клавиш[а-яё]*|мелоди[а-яё]*|музык[а-яё]*|мотив[а-яё]*|песн[а-яё]*|трек(?:а|у|ом|е|и|ов|ам|ами|ах)?|бит(?:а|у|ом|е|ы|ов|ам|ами|ах)?)\b",
    re.I,
)


def music_requested(text: str) -> bool:
    """An imperative to play/compose is enough; conversation alone is not."""
    if re.search(
        r"\bне\s+(?:сыграй|наиграй|поиграй|исполни|сочини|придумай|напиши|сделай|создай)\b",
        text,
        re.I,
    ):
        return False
    return bool(
        PLAY_REQUEST.search(text) or (COMPOSE_REQUEST.search(text) and MUSIC_NOUN.search(text))
    )


def trigger(message: dict[str, Any], username: str, bot_id: int) -> str | None:
    text = message.get("text") or message.get("caption") or ""
    replied_to = message.get("reply_to_message") or {}
    if replied_to.get("from", {}).get("id") == bot_id:
        return "direct"
    entities = message.get("entities") or message.get("caption_entities") or []
    for entity in entities:
        if entity.get("type") == "text_mention" and entity.get("user", {}).get("id") == bot_id:
            return "direct"
    if username and re.search(r"(?<!\w)@" + re.escape(username) + r"(?!\w)", text, re.I):
        return "direct"
    if NAME.search(text):
        return "direct"
    return "banana" if BANANA.search(text) else None

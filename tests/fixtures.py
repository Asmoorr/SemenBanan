from __future__ import annotations

import json


def route_json(
    mode: str = "text",
    trigger: str = "direct",
    parameters: dict[str, str | bool] | None = None,
    style: str | None = None,
) -> str:
    """Создаёт JSON решения маршрутизатора для теста.

    :param mode: Режим запуска или тип ответа.
    :param trigger: Вид обращения к боту.
    :param parameters: Параметры музыкального режима либо None.
    :param style: Изменение характера либо None.
    :return: Строка с режимом и параметрами решения.
    """
    if mode == "ignore":
        trigger = "none"

    if mode == "music" and parameters is None:
        parameters = {"composer": "score", "drums": True, "speech": True}

    return json.dumps(
        {"mode": mode, "trigger": trigger, "parameters": parameters, "style_request": style},
        ensure_ascii=False,
    )

from __future__ import annotations

import json
import math
from pathlib import Path

from semen_banan.errors import BotError


class CooldownStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        try:
            values = {
                key: float(value)
                for key, value in json.loads(self.path.read_text(encoding="utf-8")).items()
            }
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError
            return values
        except (ValueError, TypeError, AttributeError):
            raise BotError("Повреждён state.json: переименуй его и повтори запуск.") from None

    def save(self, values: dict[str, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values), encoding="utf-8")
        temporary.replace(self.path)

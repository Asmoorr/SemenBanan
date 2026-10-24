from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def generate(request: dict[str, Any]) -> tuple[bytes, int]:
    """Создаёт готовое голосовое сообщение из музыкального задания.

    :param request: Исходная просьба или задание генерации.
    :return: Байты OGG/Opus и длительность записи в секундах.
    """
    from semen_banan.audio.models import AudioRequest
    from semen_banan.audio.pipeline import AudioPipeline
    from semen_banan.audio.validation import parse_arrangement, parse_score

    score = parse_score(json.dumps(request["score"], ensure_ascii=False))
    use_nano = request.get("use_nano", False)

    if type(use_nano) is not bool:
        raise ValueError("Неверный выбор музыкальной модели.")

    arrangement = request.get("arrangement")

    if arrangement is not None:
        arrangement = parse_arrangement(
            json.dumps(arrangement, ensure_ascii=False), allow_empty=True
        )

    seed = request.get("seed")

    if seed is not None and (type(seed) is not int or not 0 <= seed < 2**32):
        raise ValueError("Неверный seed генератора.")

    return AudioPipeline().generate(AudioRequest(score, use_nano, arrangement, seed))


def main() -> int:
    """Читает задание из stdin и сохраняет аудио с метаданными.

    :return: Код завершения: 0 при успехе, 1 при ошибке.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    metadata_path = arguments.output.with_suffix(".json")

    try:
        request_bytes = sys.stdin.buffer.read(200_001)

        if len(request_bytes) > 200_000:
            raise ValueError("Задание генератору слишком большое.")

        request = json.loads(request_bytes)
        voice, duration = generate(request)
        arguments.output.write_bytes(voice)
        metadata_path.write_text(
            json.dumps({"duration": duration, "worker_pid": os.getpid()}), encoding="utf-8"
        )

        return 0
    except ImportError:
        error_message = "Не установлены необходимые зависимости аудиогенератора."
    except (json.JSONDecodeError, KeyError, TypeError):
        error_message = "Некорректное задание аудиогенератору: проверь JSON и обязательные поля."
    except OSError:
        error_message = "Не удалось прочитать ресурсы или записать результат аудиогенератора."
    except (RuntimeError, ValueError) as error:
        error_message = str(error)[:300]

    metadata_path.write_text(
        json.dumps({"error": error_message}, ensure_ascii=False), encoding="utf-8"
    )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

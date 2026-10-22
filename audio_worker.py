"""SemenBanan: generate a single voice note and exit with all loaded models."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


def generate(request: dict[str, Any]) -> tuple[bytes, int]:
    # Only this short-lived process imports and uses the inference backends.
    from arrangement import make_song, parse_arrangement
    from music import encode_voice, parse_score
    from piano import make_piano

    score = parse_score(json.dumps(request["score"], ensure_ascii=False))
    use_nano = request.get("use_nano", False)
    if type(use_nano) is not bool:
        raise ValueError("Неверный выбор музыкальной модели.")
    arrangement = request.get("arrangement")
    if arrangement is None:
        wav, duration = make_piano(score, use_nano)
    else:
        arrangement = parse_arrangement(json.dumps(arrangement, ensure_ascii=False), allow_empty=True)
        wav, duration = make_song(score, use_nano, arrangement)
    return encode_voice(wav), duration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = args.output.with_suffix(".json")
    try:
        raw = sys.stdin.buffer.read(200_001)
        if len(raw) > 200_000:
            raise ValueError("Задание генератору слишком большое.")
        request = json.loads(raw)
        voice, duration = generate(request)
        args.output.write_bytes(voice)
        metadata.write_text(json.dumps({"duration": duration, "worker_pid": os.getpid()}), encoding="utf-8")
        return 0
    except (ImportError, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        metadata.write_text(json.dumps({"error": str(exc)[:300]}, ensure_ascii=False), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

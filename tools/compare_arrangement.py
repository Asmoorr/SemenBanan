"""Сравнение музыкальных дорожек с общей аранжировкой."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from semen_banan.audio.composers import score_notes
from semen_banan.audio.encoding import encode_voice
from semen_banan.audio.mixing import backing_tracks, mix_tracks
from semen_banan.audio.rendering import render_piano
from semen_banan.audio.validation import parse_arrangement
from semen_banan.config import Settings
from semen_banan.generation.prompts import load_prompts
from semen_banan.integrations.openclaw import OpenClawClient as Gateway


async def compare(source: Path, output_directory: Path) -> None:
    """Создаёт локальные аудиозаписи для сравнения музыкальных вариантов.

    :param source: Путь к сохранённым исходным данным сравнения.
    :param output_directory: Каталог результатов сравнения.
    :return: Не возвращает значение.
    """
    comparison_data = json.loads(source.read_text(encoding="utf-8"))
    score = comparison_data["score"]
    settings = Settings.load()
    beats = len(score["chords"]) * 4

    async with httpx.AsyncClient(trust_env=False) as client:
        gateway = Gateway(client, settings)

        for attempt in range(2):
            try:
                content = await gateway.arrange(
                    [],
                    {
                        "name": "Сравнение",
                        "text": load_prompts().comparison_arrangement(comparison_data["request"]),
                    },
                    beats,
                )
                arrangement = parse_arrangement(content, beats)
                break
            except RuntimeError:
                if attempt:
                    raise

    generation_started_at = time.perf_counter()
    drums, speech = backing_tracks(score["tempo"], beats, arrangement)
    generation_seconds = round(time.perf_counter() - generation_started_at, 3)
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "drums.ogg").write_bytes(encode_voice(drums))
    (output_directory / "speech.ogg").write_bytes(encode_voice(speech))

    for name, notes in [
        ("openclaw", score_notes(score)),
        ("nanomaestro", comparison_data["nano_notes"]),
    ]:
        piano_audio, _ = render_piano(notes, score["tempo"])
        (output_directory / f"{name}-piano.ogg").write_bytes(encode_voice(piano_audio))
        mixed_audio, duration = mix_tracks(piano_audio, drums, speech)
        (output_directory / f"{name}-mix.ogg").write_bytes(encode_voice(mixed_audio))
        print(f"{name}: piano + drums + speech, {duration}s", flush=True)

    comparison_data["arrangement"] = arrangement
    comparison_data["backing_generation_seconds"] = generation_seconds
    comparison_data["speech_model"] = "Piper ru_RU-denis-medium"
    (output_directory / "comparison.json").write_text(
        json.dumps(comparison_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Backing tracks generation: {generation_seconds}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(compare(args.source, args.output))

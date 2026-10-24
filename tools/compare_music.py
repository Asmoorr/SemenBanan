"""Локальное сравнение композиторов без отправки в Telegram."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from semen_banan.audio.composers import local_composer, score_notes
from semen_banan.audio.encoding import encode_voice
from semen_banan.audio.models import Score
from semen_banan.audio.rendering import render_piano
from semen_banan.audio.validation import parse_score
from semen_banan.config import Settings
from semen_banan.conversation.models import ConversationContext
from semen_banan.generation.prompts import load_prompts
from semen_banan.integrations.openclaw import OpenClawClient as Gateway


async def compare(output_directory: Path, request: str, bars: int = 16, tempo: int = 110) -> None:
    """Создаёт локальные аудиозаписи для сравнения музыкальных вариантов.

    :param output_directory: Каталог результатов сравнения.
    :param request: Исходная просьба или задание генерации.
    :param bars: Количество тактов пьесы.
    :param tempo: Темп пьесы в ударах в минуту.
    :return: Не возвращает значение.
    """
    if bars not in (4, 8, 12, 16) or not 70 <= tempo <= 140:
        raise ValueError("Выбери 4, 8, 12 или 16 тактов и темп 70–140.")

    settings = Settings.load()
    score: Score = {"tempo": tempo, "melody": [], "chords": []}
    conversation_context: ConversationContext = []
    prompts = load_prompts()

    async with httpx.AsyncClient(trust_env=False) as client:
        gateway = Gateway(client, settings)

        for section_index in range(bars // 4):
            instruction = prompts.comparison_section(request, tempo, section_index, bars)

            for attempt in range(2):
                try:
                    section = parse_score(
                        await gateway.compose(
                            conversation_context, {"name": "Сравнение", "text": instruction}
                        )
                    )

                    if sum(melody_note["beats"] for melody_note in section["melody"]) != 16:
                        raise ValueError("Для сравнения нужны полные такты.")

                    break
                except ValueError:
                    if attempt:
                        raise

            score["melody"].extend(section["melody"])
            score["chords"].extend(section["chords"])
            conversation_context.append(
                {"name": "Предыдущий фрагмент", "text": json.dumps(section, ensure_ascii=False)}
            )
            print(f"OpenClaw: {section_index * 4 + 4}/{bars} bars", flush=True)

    output_directory.mkdir(parents=True, exist_ok=True)
    generation_started_at = time.perf_counter()
    nano_notes = local_composer().compose(score, seed=42, bars=bars)
    generation_seconds = round(time.perf_counter() - generation_started_at, 3)

    for name, notes in [("openclaw-piano", score_notes(score)), ("nanomaestro-piano", nano_notes)]:
        wave_audio, duration = render_piano(notes, score["tempo"])
        (output_directory / f"{name}.ogg").write_bytes(encode_voice(wave_audio))
        print(f"{name}: {len(notes)} notes, {duration}s")

    (output_directory / "comparison.json").write_text(
        json.dumps(
            {
                "request": request,
                "score": score,
                "nano_notes": nano_notes,
                "nano_generation_seconds": generation_seconds,
                "seed": 42,
                "bars": bars,
                "soundfont": "GeneralUser GS 2.0.3",
                "render_sample_rate": 48000,
                "note": "Один такт от OpenClaw служит началом для NanoMaestro; звучание одинаковое.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"NanoMaestro generation: {generation_seconds}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", default=load_prompts().comparison_request)
    parser.add_argument("--bars", type=int, choices=[4, 8, 12, 16], default=16)
    parser.add_argument("--tempo", type=int, default=110)
    args = parser.parse_args()
    asyncio.run(compare(args.output, args.request, args.bars, args.tempo))

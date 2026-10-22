"""Create two local previews without posting anything to Telegram."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time

import httpx

from bot import Gateway, Settings
from music import encode_voice, parse_score
from piano import local_composer, render_piano, score_notes


async def compare(folder: Path, request: str, bars: int = 16, tempo: int = 110) -> None:
    if bars not in (4, 8, 12, 16) or not 70 <= tempo <= 140:
        raise ValueError("Выбери 4, 8, 12 или 16 тактов и темп 70–140.")
    settings = Settings.load()
    score = {"tempo": tempo, "melody": [], "chords": []}
    context = []
    forms = ["изложи основную тему", "развей тему", "сделай вариацию", "подведи к завершению и закончи на тонике"]
    async with httpx.AsyncClient(trust_env=False) as client:
        gateway = Gateway(client, settings)
        for index in range(bars // 4):
            action = forms[3] if index == bars // 4 - 1 and index else forms[index]
            instruction = (f"{request}. Темп {tempo}. Это такты {index * 4 + 1}–{index * 4 + 4} "
                           f"пьесы из {bars} тактов: {action}. Ровно 16 долей в этом фрагменте.")
            for attempt in range(2):
                try:
                    section = parse_score(await gateway.compose(context, {"name": "Сравнение", "text": instruction}))
                    if sum(n["beats"] for n in section["melody"]) != 16:
                        raise ValueError("Для сравнения нужны полные такты.")
                    break
                except ValueError:
                    if attempt:
                        raise
            score["melody"].extend(section["melody"])
            score["chords"].extend(section["chords"])
            context.append({"name": "Предыдущий фрагмент", "text": json.dumps(section, ensure_ascii=False)})
            print(f"OpenClaw: {index * 4 + 4}/{bars} bars", flush=True)
    folder.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    nano_notes = local_composer().compose(score, seed=42, bars=bars)
    elapsed = round(time.perf_counter() - started, 3)
    for name, notes in [("openclaw-piano", score_notes(score)), ("nanomaestro-piano", nano_notes)]:
        wav, duration = render_piano(notes, score["tempo"])
        (folder / f"{name}.ogg").write_bytes(encode_voice(wav))
        print(f"{name}: {len(notes)} notes, {duration}s")
    (folder / "comparison.json").write_text(json.dumps({
        "request": request, "score": score, "nano_notes": nano_notes,
        "nano_generation_seconds": elapsed, "seed": 42, "bars": bars,
        "soundfont": "GeneralUser GS 2.0.3", "render_sample_rate": 48000,
        "note": "Один такт от OpenClaw служит началом для NanoMaestro; звучание одинаковое.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"NanoMaestro generation: {elapsed}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", default="Семён, сыграй весёлую мелодию про бананы на пианино")
    parser.add_argument("--bars", type=int, choices=[4, 8, 12, 16], default=16)
    parser.add_argument("--tempo", type=int, default=110)
    args = parser.parse_args()
    asyncio.run(compare(args.output, args.request, args.bars, args.tempo))

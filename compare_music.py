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


async def compare(folder: Path, request: str) -> None:
    settings = Settings.load()
    async with httpx.AsyncClient(trust_env=False) as client:
        gateway = Gateway(client, settings)
        score = parse_score(await gateway.compose([], {"name": "Сравнение", "text": request}))
    folder.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    nano_notes = local_composer().compose(score, seed=42)
    elapsed = round(time.perf_counter() - started, 3)
    for name, notes in [("openclaw-piano", score_notes(score)), ("nanomaestro-piano", nano_notes)]:
        wav, duration = render_piano(notes, score["tempo"])
        (folder / f"{name}.ogg").write_bytes(encode_voice(wav))
        print(f"{name}: {len(notes)} notes, {duration}s")
    (folder / "comparison.json").write_text(json.dumps({
        "request": request, "score": score, "nano_notes": nano_notes,
        "nano_generation_seconds": elapsed, "seed": 42,
        "note": "Один такт от OpenClaw служит началом для NanoMaestro; звучание одинаковое.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"NanoMaestro generation: {elapsed}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", default="Семён, сыграй весёлую мелодию про бананы на пианино")
    args = parser.parse_args()
    asyncio.run(compare(args.output, args.request))

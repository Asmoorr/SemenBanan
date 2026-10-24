"""Add shared drums and speech to an existing, reproducible piano comparison."""

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
from semen_banan.integrations.openclaw import OpenClawClient as Gateway


async def compare(source: Path, folder: Path) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    score = data["score"]
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
                        "text": data["request"]
                        + ". Добавь лёгкие барабаны и три короткие смешные фразы про бананы.",
                    },
                    beats,
                )
                arrangement = parse_arrangement(content, beats)
                break
            except RuntimeError:
                if attempt:
                    raise
    started = time.perf_counter()
    drums, speech = backing_tracks(score["tempo"], beats, arrangement)
    elapsed = round(time.perf_counter() - started, 3)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "drums.ogg").write_bytes(encode_voice(drums))
    (folder / "speech.ogg").write_bytes(encode_voice(speech))
    for name, notes in [("openclaw", score_notes(score)), ("nanomaestro", data["nano_notes"])]:
        piano, _ = render_piano(notes, score["tempo"])
        (folder / f"{name}-piano.ogg").write_bytes(encode_voice(piano))
        mixed, duration = mix_tracks(piano, drums, speech)
        (folder / f"{name}-mix.ogg").write_bytes(encode_voice(mixed))
        print(f"{name}: piano + drums + speech, {duration}s", flush=True)
    data["arrangement"] = arrangement
    data["backing_generation_seconds"] = elapsed
    data["speech_model"] = "Piper ru_RU-denis-medium"
    (folder / "comparison.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Backing tracks generation: {elapsed}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(compare(args.source, args.output))

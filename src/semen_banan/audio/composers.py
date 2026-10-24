from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from semen_banan.audio.models import ComposerKind, Score
from semen_banan.config import AppPaths


def score_notes(score: Score) -> list[dict]:
    notes = []
    offset = 0.0
    for index, note in enumerate(score["melody"]):
        notes.append(
            dict(
                start=offset,
                beats=note["beats"] * 0.9,
                midi=note["midi"],
                velocity=82 + (index % 3 - 1) * 5,
                channel=0,
            )
        )
        offset += note["beats"]
    for bar, chord in enumerate(score["chords"]):
        for beat in (0, 2):
            for pitch in chord:
                notes.append(
                    dict(start=bar * 4 + beat, beats=1.7, midi=pitch, velocity=48, channel=1)
                )
    return notes


class IncompleteCompositionError(RuntimeError):
    """The model finished without enough notes or bars."""


class NanoMaestro:
    def __init__(self, assets: Path | None = None) -> None:
        import numpy as np
        import onnxruntime as ort

        assets = assets or AppPaths.load().assets
        self.np = np
        vocab = json.loads((assets / "nanomaestro/vocab.json").read_text(encoding="utf-8"))
        self.stoi = vocab["stoi"]
        self.itos = {int(k): v for k, v in vocab["itos"].items()}
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(assets / "nanomaestro/model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def compose(self, score: Score, seed: int | None = None, bars: int = 4) -> list[dict]:
        """Continue the primer; allow one retry within a shared time budget."""
        if type(bars) is not int or not 4 <= bars <= 16:
            raise RuntimeError("Длина пьесы должна быть от 4 до 16 тактов.")
        deadline = time.monotonic() + 20
        for attempt in range(2):
            if time.monotonic() >= deadline:
                raise RuntimeError("NanoMaestro не закончила пьесу за 20 секунд.")
            attempt_seed = (seed + attempt) % (2**32) if seed is not None else None
            try:
                return self._compose(score, attempt_seed, bars, deadline)
            except IncompleteCompositionError:
                if attempt:
                    raise
        raise AssertionError("Unreachable local composition retry state")

    def _compose(self, score: Score, seed: int | None, bars: int, deadline: float) -> list[dict]:
        np = self.np
        rng = np.random.default_rng(seed)
        prompt = ["BOS", f"BPM_{score['tempo']}", "GRID_64", "BAR"]
        primer = [n for n in score_notes(score) if n["start"] < 4]
        position = None
        for note in sorted(primer, key=lambda n: (n["start"], n["midi"])):
            pos = round(note["start"] * 16)
            if pos != position:
                prompt.append(f"POS_{pos}")
                position = pos
            prompt.extend(
                [
                    f"NOTE_{note['midi']}",
                    f"DUR_{min(64, max(1, round(note['beats'] * 16)))}",
                    f"VEL_{min(8, max(1, round(note['velocity'] / 16)))}",
                ]
            )
        prompt.extend(["BAR", "POS_0"])
        h = np.zeros((2, 1, 1024), dtype=np.float32)
        c = np.zeros_like(h)
        logits = None

        def step(token: str):
            nonlocal h, c, logits
            if time.monotonic() >= deadline:
                raise RuntimeError("NanoMaestro не закончила пьесу за 20 секунд.")
            logits, h, c = self.session.run(
                None, {"input": np.array([[self.stoi[token]]], dtype=np.int64), "h": h, "c": c}
            )

        for token in prompt:
            step(token)
        notes = list(primer)
        bar, pos, chord_size = 1, 0, 0
        pending_pitch, pending_duration = None, None
        previous = "POS_0"
        for _ in range(bars * 400):
            if time.monotonic() > deadline:
                raise RuntimeError("NanoMaestro не закончила пьесу за 20 секунд.")
            if previous.startswith("NOTE_"):
                allowed = [i for t, i in self.stoi.items() if t.startswith("DUR_")]
            elif previous.startswith("DUR_"):
                allowed = [i for t, i in self.stoi.items() if t.startswith("VEL_")]
            else:
                allowed = [
                    i
                    for t, i in self.stoi.items()
                    if (t.startswith("NOTE_") and chord_size < 8)
                    or t == "BAR"
                    or (t.startswith("POS_") and int(t[4:]) > pos)
                ]
            values = np.asarray(logits).reshape(-1)[allowed].astype(np.float64) / 0.85
            top = np.argsort(values)[-min(24, len(values)) :]
            weights = np.exp(values[top] - values[top].max())
            selected = int(rng.choice(top, p=weights / weights.sum()))
            token = self.itos[allowed[selected]]
            if token == "BAR":
                bar += 1
                pos, chord_size = 0, 0
                if bar >= bars:
                    break
            elif token.startswith("POS_"):
                pos, chord_size = int(token[4:]), 0
            elif token.startswith("NOTE_"):
                pending_pitch = int(token[5:])
            elif token.startswith("DUR_"):
                pending_duration = min(4.0, int(token[4:]) / 16)
            elif token.startswith("VEL_") and pending_pitch is not None and pending_duration:
                start = bar * 4 + pos / 16
                notes.append(
                    dict(
                        start=start,
                        beats=min(pending_duration, bars * 4 - start),
                        midi=pending_pitch,
                        velocity=int(token[4:]) * 13,
                    )
                )
                pending_pitch, pending_duration = None, None
                chord_size += 1
            step(token)
            previous = token
        if (
            bar < bars
            or len(notes) < len(primer) + 8
            or max(n["start"] for n in notes) < (bars - 1) * 4
        ):
            raise IncompleteCompositionError("NanoMaestro вернула слишком короткую пьесу.")
        return notes


@lru_cache(maxsize=1)
def local_composer() -> NanoMaestro:
    try:
        return NanoMaestro()
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(
            "NanoMaestro недоступна: установи requirements-music.txt и запусти tools/setup_assets.py."
        ) from exc


class Composer(Protocol):
    def compose(self, score: Score, seed: int | None = None) -> list[dict]: ...


class ScoreComposer:
    def compose(self, score: Score, seed: int | None = None) -> list[dict]:
        return score_notes(score)


def select_composer(kind: ComposerKind) -> Composer:
    if kind == ComposerKind.NANOMAESTRO:
        return local_composer()
    return ScoreComposer()

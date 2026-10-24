from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from semen_banan.audio.models import ComposerKind, NoteSequence, Score
from semen_banan.config import AppPaths


def score_notes(score: Score) -> NoteSequence:
    """Преобразует мелодию и аккорды в ноты для озвучивания.

    :param score: Партитура с темпом, мелодией и аккордами.
    :return: Ноты с позицией, длительностью, силой и каналом.
    """
    notes: NoteSequence = []
    melody_offset = 0.0

    for index, note in enumerate(score["melody"]):
        notes.append(
            dict(
                start=melody_offset,
                beats=note["beats"] * 0.9,
                midi=note["midi"],
                velocity=82 + (index % 3 - 1) * 5,
                channel=0,
            )
        )
        melody_offset += note["beats"]

    for bar_index, chord in enumerate(score["chords"]):
        for beat in (0, 2):
            for pitch in chord:
                notes.append(
                    dict(start=bar_index * 4 + beat, beats=1.7, midi=pitch, velocity=48, channel=1)
                )

    return notes


class IncompleteCompositionError(RuntimeError):
    """Ошибка слишком короткого результата локальной модели."""


class NanoMaestro:
    """Локальный композитор с ограничением длины и времени генерации."""

    def __init__(self, assets: Path | None = None) -> None:
        """Загружает словарь и сессию локальной модели NanoMaestro.

        :param assets: Каталог музыкальных моделей и звуковых банков.
        :return: Не возвращает значение.
        """
        import numpy as np
        import onnxruntime as ort

        assets = assets or AppPaths.load().assets
        self.numpy_module = np
        vocabulary = json.loads((assets / "nanomaestro/vocab.json").read_text(encoding="utf-8"))
        self.token_indices = vocabulary["stoi"]
        self.tokens_by_index = {
            int(token_index): token_name for token_index, token_name in vocabulary["itos"].items()
        }
        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 2
        session_options.inter_op_num_threads = 1
        self.inference_session = ort.InferenceSession(
            str(assets / "nanomaestro/model.onnx"),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )

    def compose(self, score: Score, seed: int | None = None, bars: int = 4) -> NoteSequence:
        """Получает ноты для заданной партитуры.

        :param score: Партитура с темпом, мелодией и аккордами.
        :param seed: Начальное значение генератора случайных чисел.
        :param bars: Количество тактов пьесы.
        :return: Последовательность нот для озвучивания.
        """
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

        raise AssertionError("Недостижимое состояние повторной локальной генерации.")

    def _compose(self, score: Score, seed: int | None, bars: int, deadline: float) -> NoteSequence:
        """Создаёт музыкальное продолжение заданной партитуры.

        :param score: Партитура с темпом, мелодией и аккордами.
        :param seed: Начальное значение генератора случайных чисел.
        :param bars: Количество тактов пьесы.
        :param deadline: Предельная монотонная временная метка генерации.
        :return: Результат сочинения с проверенными ограничениями.
        """
        np = self.numpy_module
        random_generator = np.random.default_rng(seed)
        prompt = ["BOS", f"BPM_{score['tempo']}", "GRID_64", "BAR"]
        primer_notes = [note for note in score_notes(score) if note["start"] < 4]
        previous_grid_position = None

        for note in sorted(primer_notes, key=lambda note: (note["start"], note["midi"])):
            grid_position = round(note["start"] * 16)

            if grid_position != previous_grid_position:
                prompt.append(f"POS_{grid_position}")
                previous_grid_position = grid_position

            prompt.extend(
                [
                    f"NOTE_{note['midi']}",
                    f"DUR_{min(64, max(1, round(note['beats'] * 16)))}",
                    f"VEL_{min(8, max(1, round(note['velocity'] / 16)))}",
                ]
            )

        prompt.extend(["BAR", "POS_0"])
        hidden_state = np.zeros((2, 1, 1024), dtype=np.float32)
        cell_state = np.zeros_like(hidden_state)
        token_logits = None

        def step(token: str) -> None:
            """Выполняет один шаг модели и обновляет её внутреннее состояние.

            :param token: Токен модели или Telegram API.
            :return: Не возвращает значение.
            """
            nonlocal hidden_state, cell_state, token_logits

            if time.monotonic() >= deadline:
                raise RuntimeError("NanoMaestro не закончила пьесу за 20 секунд.")

            token_logits, hidden_state, cell_state = self.inference_session.run(
                None,
                {
                    "input": np.array([[self.token_indices[token]]], dtype=np.int64),
                    "h": hidden_state,
                    "c": cell_state,
                },
            )

        for token in prompt:
            step(token)

        notes = list(primer_notes)
        bar_index, grid_position, chord_size = 1, 0, 0
        pending_pitch, pending_duration = None, None
        previous_token = "POS_0"

        for _ in range(bars * 400):
            if time.monotonic() > deadline:
                raise RuntimeError("NanoMaestro не закончила пьесу за 20 секунд.")

            if previous_token.startswith("NOTE_"):
                allowed = [
                    token_index
                    for token_name, token_index in self.token_indices.items()
                    if token_name.startswith("DUR_")
                ]
            elif previous_token.startswith("DUR_"):
                allowed = [
                    token_index
                    for token_name, token_index in self.token_indices.items()
                    if token_name.startswith("VEL_")
                ]
            else:
                allowed = [
                    token_index
                    for token_name, token_index in self.token_indices.items()
                    if (token_name.startswith("NOTE_") and chord_size < 8)
                    or token_name == "BAR"
                    or (token_name.startswith("POS_") and int(token_name[4:]) > grid_position)
                ]

            values = np.asarray(token_logits).reshape(-1)[allowed].astype(np.float64) / 0.85
            candidate_indices = np.argsort(values)[-min(24, len(values)) :]
            sampling_weights = np.exp(values[candidate_indices] - values[candidate_indices].max())
            selected_index = int(
                random_generator.choice(
                    candidate_indices, p=sampling_weights / sampling_weights.sum()
                )
            )
            token = self.tokens_by_index[allowed[selected_index]]

            if token == "BAR":
                bar_index += 1
                grid_position, chord_size = 0, 0

                if bar_index >= bars:
                    break
            elif token.startswith("POS_"):
                grid_position, chord_size = int(token[4:]), 0
            elif token.startswith("NOTE_"):
                pending_pitch = int(token[5:])
            elif token.startswith("DUR_"):
                pending_duration = min(4.0, int(token[4:]) / 16)
            elif token.startswith("VEL_") and pending_pitch is not None and pending_duration:
                start = bar_index * 4 + grid_position / 16
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
            previous_token = token

        if (
            bar_index < bars
            or len(notes) < len(primer_notes) + 8
            or max(note["start"] for note in notes) < (bars - 1) * 4
        ):
            raise IncompleteCompositionError("NanoMaestro вернула слишком короткую пьесу.")

        return notes


@lru_cache(maxsize=1)
def local_composer() -> NanoMaestro:
    """Загружает и кеширует локальный композитор в текущем процессе.

    :return: Готовый композитор NanoMaestro.
    """
    try:
        return NanoMaestro()
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(
            "NanoMaestro недоступна: установи requirements-music.txt и запусти tools/setup_assets.py."
        ) from exc


class Composer(Protocol):
    """Контракт получения нот из исходной партитуры."""

    def compose(self, score: Score, seed: int | None = None) -> NoteSequence:
        """Получает ноты для заданной партитуры.

        :param score: Партитура с темпом, мелодией и аккордами.
        :param seed: Начальное значение генератора случайных чисел.
        :return: Последовательность нот для озвучивания.
        """
        ...


class ScoreComposer:
    """Композитор, использующий готовую партитуру без локальной модели."""

    def compose(self, score: Score, seed: int | None = None) -> NoteSequence:
        """Получает ноты для заданной партитуры.

        :param score: Партитура с темпом, мелодией и аккордами.
        :param seed: Начальное значение генератора случайных чисел.
        :return: Последовательность нот для озвучивания.
        """
        return score_notes(score)


def select_composer(kind: ComposerKind) -> Composer:
    """Выбирает способ получения нот по типу композитора.

    :param kind: Тип композитора или отложенного задания.
    :return: Объект выбранного композитора.
    """
    if kind == ComposerKind.NANOMAESTRO:
        return local_composer()

    return ScoreComposer()

from __future__ import annotations

import io
import json
import wave
from functools import lru_cache
from typing import TYPE_CHECKING

from semen_banan.config import AppPaths

if TYPE_CHECKING:
    from piper import PiperVoice


@lru_cache(maxsize=1)
def speech_voice() -> PiperVoice:
    """Загружает и кеширует голос Piper в текущем процессе.

    :return: Готовый голос для синтеза русской речи.
    """
    assets = AppPaths.load().assets

    try:
        import onnxruntime as ort
        from piper import PiperVoice
        from piper.config import PiperConfig

        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 2
        session_options.inter_op_num_threads = 1
        voice_configuration = json.loads(
            (assets / "speech/denis.onnx.json").read_text(encoding="utf-8")
        )
        inference_session = ort.InferenceSession(
            str(assets / "speech/denis.onnx"),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )

        return PiperVoice(
            session=inference_session,
            config=PiperConfig.from_dict(voice_configuration),
            download_dir=assets / "speech",
        )
    except Exception as exc:
        raise RuntimeError(
            "Piper недоступен: установи requirements-music.txt и запусти tools/setup_assets.py."
        ) from exc


@lru_cache(maxsize=16)
def synthesize_speech(text: str) -> bytes:
    """Синтезирует короткую русскую фразу в WAV.

    :param text: Текст сообщения или речевой фразы.
    :return: Байты речевой WAV-дорожки.
    """
    if not text.strip() or len(text) > 80:
        raise RuntimeError("Речевая фраза должна содержать от 1 до 80 символов.")

    wave_buffer = io.BytesIO()

    try:
        from piper import SynthesisConfig

        with wave.open(wave_buffer, "wb") as wave_writer:
            speech_voice().synthesize_wav(
                text, wave_writer, syn_config=SynthesisConfig(length_scale=1.05)
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Не удалось синтезировать речевую фразу.") from exc

    return wave_buffer.getvalue()

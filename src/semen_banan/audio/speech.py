from __future__ import annotations

import io
import json
import wave
from functools import lru_cache

from semen_banan.config import AppPaths


@lru_cache(maxsize=1)
def speech_voice():
    assets = AppPaths.load().assets
    try:
        import onnxruntime as ort
        from piper import PiperVoice
        from piper.config import PiperConfig

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        config = json.loads((assets / "speech/denis.onnx.json").read_text(encoding="utf-8"))
        session = ort.InferenceSession(
            str(assets / "speech/denis.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        return PiperVoice(
            session=session, config=PiperConfig.from_dict(config), download_dir=assets / "speech"
        )
    except Exception as exc:
        raise RuntimeError(
            "Piper недоступен: установи requirements-music.txt и запусти tools/setup_assets.py."
        ) from exc


@lru_cache(maxsize=16)
def synthesize_speech(text: str) -> bytes:
    if not text.strip() or len(text) > 80:
        raise RuntimeError("Речевая фраза должна содержать от 1 до 80 символов.")
    output = io.BytesIO()
    try:
        from piper import SynthesisConfig

        with wave.open(output, "wb") as wav:
            speech_voice().synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1.05))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Не удалось синтезировать речевую фразу.") from exc
    return output.getvalue()

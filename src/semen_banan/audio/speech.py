from __future__ import annotations

import io
import json
import subprocess
import wave
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from semen_banan.audio.encoding import ffmpeg_executable
from semen_banan.audio.voice_settings import VoiceEffect, VoiceSettings
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
def synthesize_speech(text: str, settings: VoiceSettings = VoiceSettings()) -> bytes:
    """Синтезирует короткую русскую фразу в WAV.

    :param text: Текст сообщения или речевой фразы.
    :param settings: Скорость, высота и эффект локального голоса.
    :return: Байты речевой WAV-дорожки.
    """
    if not text.strip() or len(text) > 80:
        raise RuntimeError("Речевая фраза должна содержать от 1 до 80 символов.")

    if settings.voice != "denis":
        wave_audio = synthesize_silero(text, settings.voice)
        return apply_voice_effects(wave_audio, settings, speed=settings.speed)

    wave_buffer = io.BytesIO()
    try:
        from piper import SynthesisConfig

        with wave.open(wave_buffer, "wb") as wave_writer:
            speech_voice().synthesize_wav(
                text, wave_writer, syn_config=SynthesisConfig(length_scale=1.05 / settings.speed)
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Не удалось синтезировать речевую фразу.") from exc

    return apply_voice_effects(wave_buffer.getvalue(), settings)


@lru_cache(maxsize=1)
def silero_voice() -> Any:
    """Загружает локальную Silero v5.6 на CPU без сетевых обращений.

    :return: Модель синтеза русской речи.
    """
    try:
        import torch

        torch.set_num_threads(4)
        model_path = AppPaths.load().assets / "speech/silero-v5_6-ru.pt"
        model = torch.package.PackageImporter(str(model_path)).load_pickle("tts_models", "model")
        model.to(torch.device("cpu"))
        return model
    except Exception as error:
        raise RuntimeError(
            "Silero недоступна: установи музыкальные зависимости и запусти tools/setup_assets.py."
        ) from error


def synthesize_silero(text: str, speaker: str) -> bytes:
    """Создаёт русскую речь с автоматическими ударениями в 48 кГц.

    :param text: Короткая речевая фраза.
    :param speaker: Проверенное имя голоса Silero.
    :return: WAV с монофонической речью.
    """
    import numpy as np
    import torch

    try:
        with torch.inference_mode():
            audio = silero_voice().apply_tts(
                text=text, speaker=speaker, sample_rate=48000, put_accent=True, put_yo=True
            )
        samples = audio.detach().cpu().numpy()
        if not len(samples) or len(samples) > 48000 * 30 or not np.isfinite(samples).all():
            raise RuntimeError("Синтезированная речь пуста или слишком длинная.")
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(48000)
            writer.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        return output.getvalue()
    except Exception as error:
        raise RuntimeError("Не удалось синтезировать речь Silero.") from error


def apply_voice_effects(wave_audio: bytes, settings: VoiceSettings, *, speed: float = 1.0) -> bytes:
    """Меняет высоту и подмешивает эффект, сохраняя разборчивую исходную речь.

    :param wave_audio: Исходная речевая WAV-дорожка.
    :param settings: Проверенные параметры обработки.
    :param speed: Коэффициент скорости для движка без собственного управления темпом.
    :return: Обработанная WAV-дорожка с частотой 48 кГц.
    """
    if (
        speed == 1.0
        and settings.pitch_semitones == 0
        and (settings.effect == VoiceEffect.NONE or settings.effect_amount == 0)
    ):
        return wave_audio

    filters = ["aresample=48000"]
    if settings.pitch_semitones:
        pitch_ratio = 2 ** (settings.pitch_semitones / 12)
        filters.extend(
            (f"asetrate={48000 * pitch_ratio}", "aresample=48000", f"atempo={1 / pitch_ratio}")
        )
    if speed != 1.0:
        filters.append(f"atempo={speed}")

    effect_filters = {
        VoiceEffect.ROBOT: "aeval=val(0)*sin(2*PI*70*t):c=same",
        VoiceEffect.TELEPHONE: "highpass=f=400,lowpass=f=3400",
        VoiceEffect.ECHO: "aecho=0.8:0.8:180:0.45",
        VoiceEffect.REVERB: "aecho=0.8:0.8:37|61|89|127:0.35|0.28|0.2|0.12",
        VoiceEffect.CHORUS: "chorus=0.5:0.9:40|55:0.3|0.25:0.25|0.4:2|2.5",
    }
    filter_graph = ",".join(filters)
    if settings.effect != VoiceEffect.NONE and settings.effect_amount:
        wet_gain = settings.effect_amount / 100
        filter_graph += (
            f",asplit=2[dry][wet];[wet]{effect_filters[settings.effect]}[effect];"
            f"[dry][effect]amix=inputs=2:weights='{1 - wet_gain} {wet_gain}':normalize=0"
        )
    try:
        result = subprocess.run(
            [
                ffmpeg_executable(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-filter_complex",
                filter_graph,
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                "pipe:1",
            ],
            input=wave_audio,
            capture_output=True,
            check=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Не удалось применить голосовой эффект.") from error
    return result.stdout

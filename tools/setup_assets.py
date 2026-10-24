"""Установка закреплённых музыкальных ресурсов с проверкой SHA-256."""

from __future__ import annotations

import hashlib
import io
import platform
import zipfile
from pathlib import Path
from urllib.request import urlopen

from semen_banan.config import AppPaths

ASSETS_DIRECTORY = AppPaths.load().assets
REVISION = "9a64dd24b3a550a6101f868af71bdc9960376e26"
NANOMAESTRO_MODEL_SOURCE = (
    f"https://huggingface.co/utkucoban/NanoMaestro-Realtime/resolve/{REVISION}/NanoMaestro-Light"
)
FONT_SOURCE = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/684543d5e5efaef08d02be50dcda8d552478fa60"
VOICE_SOURCE = "https://huggingface.co/rhasspy/piper-voices/resolve/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/ru/ru_RU/denis/medium"


def download(url: str, expected_digest: str) -> bytes:
    """Загружает ресурс и проверяет его контрольную сумму.

    :param url: Адрес загрузки ресурса.
    :param expected_digest: Ожидаемая контрольная сумма SHA-256.
    :return: Байты проверенного ресурса.
    """
    with urlopen(url, timeout=90) as response:
        downloaded_data = response.read(80 * 1024 * 1024)

    if hashlib.sha256(downloaded_data).hexdigest() != expected_digest:
        raise RuntimeError("Контрольная сумма загруженного файла не совпала.")

    return downloaded_data


def main() -> None:
    """Устанавливает проверенные модели и музыкальные ресурсы.

    :return: Не возвращает значение.
    """
    ASSETS_DIRECTORY.mkdir(exist_ok=True)
    soundfont = ASSETS_DIRECTORY / "GeneralUser-GS.sf2"

    if not soundfont.exists():
        soundfont.write_bytes(
            download(
                f"{FONT_SOURCE}/GeneralUser-GS.sf2",
                "9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe",
            )
        )

    license_path = ASSETS_DIRECTORY / "GeneralUser-GS-LICENSE.txt"

    if not license_path.exists():
        license_path.write_bytes(
            download(
                f"{FONT_SOURCE}/documentation/LICENSE.txt",
                "7b32efefdf95ce38a043799f0659853ddc00fbaa14d8c50f0aca16b9b8b405be",
            )
        )

    if platform.system() == "Windows":
        if platform.machine().lower() not in {"amd64", "x86_64"}:
            raise RuntimeError("Переносимый FluidSynth подготовлен для Windows x64.")

        if not (ASSETS_DIRECTORY / "fluidsynth/bin/fluidsynth.exe").exists():
            downloaded_data = download(
                "https://github.com/FluidSynth/fluidsynth/releases/download/v2.6.1/fluidsynth-v2.6.1-win10-x64-cpp11.zip",
                "fab7a2e4b85675b66970f97a39bbc239729c5e0f237198b5922a6a73cbc8677c",
            )

            with zipfile.ZipFile(io.BytesIO(downloaded_data)) as archive:
                for member in archive.infolist():
                    archive_parts = Path(member.filename).parts

                    if not member.is_dir() and "bin" in archive_parts:
                        destination_path = (
                            ASSETS_DIRECTORY / "fluidsynth/bin" / Path(member.filename).name
                        )
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        destination_path.write_bytes(archive.read(member))

    for filename, expected_digest, target_name in [
        (
            "model_int8_v2.onnx",
            "09ff6e036449c9c4fe14a52c7b90942f035d3e6f0e417a6e626fc30ad5faf6e2",
            "model.onnx",
        ),
        (
            "vocabv2.json",
            "8c6c81341e423252b3ec0208bd728a97e1a6d2265b6bb20a89965b7c4de41ecc",
            "vocab.json",
        ),
    ]:
        destination_path = ASSETS_DIRECTORY / "nanomaestro" / target_name
        destination_path.parent.mkdir(exist_ok=True)

        if (
            not destination_path.exists()
            or hashlib.sha256(destination_path.read_bytes()).hexdigest() != expected_digest
        ):
            destination_path.write_bytes(
                download(f"{NANOMAESTRO_MODEL_SOURCE}/{filename}", expected_digest)
            )

    for filename, expected_digest, target_name in [
        (
            "ru_RU-denis-medium.onnx",
            "15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a",
            "denis.onnx",
        ),
        (
            "ru_RU-denis-medium.onnx.json",
            "831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8",
            "denis.onnx.json",
        ),
        (
            "MODEL_CARD",
            "8b5d685dd80f8ad3f8dbbe1c56b16bb0809f00c144af3642dbcf3b707eb89c12",
            "MODEL_CARD",
        ),
    ]:
        destination_path = ASSETS_DIRECTORY / "speech" / target_name
        destination_path.parent.mkdir(exist_ok=True)

        if (
            not destination_path.exists()
            or hashlib.sha256(destination_path.read_bytes()).hexdigest() != expected_digest
        ):
            destination_path.write_bytes(download(f"{VOICE_SOURCE}/{filename}", expected_digest))

    print(
        "Пианино, NanoMaestro Light и Piper Denis готовы. На Linux/macOS также установи FluidSynth."
    )


if __name__ == "__main__":
    main()

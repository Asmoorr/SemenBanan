"""Install small, pinned music assets locally; never executed during chat replies."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import platform
import tarfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parent / "assets"
REVISION = "9a64dd24b3a550a6101f868af71bdc9960376e26"
HF = f"https://huggingface.co/utkucoban/NanoMaestro-Realtime/resolve/{REVISION}/NanoMaestro-Light"


def download(url: str, digest: str) -> bytes:
    with urlopen(url, timeout=90) as response:
        data = response.read(40 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError("Контрольная сумма загруженного файла не совпала.")
    return data


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    soundfont = ROOT / "TimGM6mb.sf2"
    if not soundfont.exists():
        data = download(
            "https://deb.debian.org/debian/pool/main/t/timgm6mb-soundfont/timgm6mb-soundfont_1.3.orig.tar.gz",
            "af8f3a00e416dfb262bcaa904a1c84df04a51b72bbc1313aed012bc754bdf99b")
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = archive.getmember("timgm6mb-soundfont_1.3/TimGM6mb.sf2")
            soundfont.write_bytes(archive.extractfile(member).read())
    if platform.system() == "Windows":
        if platform.machine().lower() not in {"amd64", "x86_64"}:
            raise RuntimeError("Переносимый FluidSynth подготовлен для Windows x64.")
        if not (ROOT / "fluidsynth/bin/fluidsynth.exe").exists():
            data = download(
                "https://github.com/FluidSynth/fluidsynth/releases/download/v2.6.1/fluidsynth-v2.6.1-win10-x64-cpp11.zip",
                "fab7a2e4b85675b66970f97a39bbc239729c5e0f237198b5922a6a73cbc8677c")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    parts = Path(member.filename).parts
                    if not member.is_dir() and "bin" in parts:
                        target = ROOT / "fluidsynth/bin" / Path(member.filename).name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(member))
    for filename, digest, target_name in [
        ("model_int8_v2.onnx", "09ff6e036449c9c4fe14a52c7b90942f035d3e6f0e417a6e626fc30ad5faf6e2", "model.onnx"),
        ("vocabv2.json", "8c6c81341e423252b3ec0208bd728a97e1a6d2265b6bb20a89965b7c4de41ecc", "vocab.json"),
    ]:
        target = ROOT / "nanomaestro" / target_name
        target.parent.mkdir(exist_ok=True)
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            target.write_bytes(download(f"{HF}/{filename}", digest))
    print("Пианино и NanoMaestro Light готовы. На Linux/macOS также установи FluidSynth.")


if __name__ == "__main__":
    main()

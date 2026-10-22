# Музыкальные компоненты

Компоненты загружаются отдельно командой `python setup_music.py` в `assets/`.
Их исходный код и лицензии доступны по ссылкам ниже; они не являются частью
собственного кода бота.

- **FluidSynth 2.6.1** — LGPL-2.1-or-later. Переносимая сборка Windows x64:
  https://github.com/FluidSynth/fluidsynth/releases/tag/v2.6.1
  Исходники и лицензия: https://github.com/FluidSynth/fluidsynth/tree/v2.6.1
- **TimGM6mb** — SoundFont Тима Бречбилла, GPL-2.0.
  Оригинальный банк из MuseScore 1.3; загружается из исходного пакета Debian:
  https://packages.debian.org/bookworm/timgm6mb-soundfont
  Сведения об авторстве и лицензии:
  https://metadata.ftp-master.debian.org/changelogs/main/t/timgm6mb-soundfont/timgm6mb-soundfont_1.3-5_copyright
- **NanoMaestro Light**, автор `utkucoban` — CC-BY-NC-4.0.
  https://huggingface.co/utkucoban/NanoMaestro-Realtime
  Закреплённая ревизия: `9a64dd24b3a550a6101f868af71bdc9960376e26`.
  Используется согласованная пара `model_int8_v2.onnx` / `vocabv2.json`.
  Модель предназначена для некоммерческого использования по её лицензии.

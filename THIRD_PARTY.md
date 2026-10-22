# Музыкальные компоненты

Компоненты загружаются отдельно командой `python setup_music.py` в `assets/`.
Их исходный код и лицензии доступны по ссылкам ниже; они не являются частью
собственного кода бота.

- **FluidSynth 2.6.1** — LGPL-2.1-or-later. Переносимая сборка Windows x64:
  https://github.com/FluidSynth/fluidsynth/releases/tag/v2.6.1
  Исходники и лицензия: https://github.com/FluidSynth/fluidsynth/tree/v2.6.1
- **GeneralUser GS 2.0.3**, автор S. Christian Collins — авторская лицензия
  GeneralUser GS v2.0, разрешающая создание музыкальных записей.
  https://github.com/mrbumpy409/GeneralUser-GS
  Закреплённая ревизия: `684543d5e5efaef08d02be50dcda8d552478fa60`.
  Установщик сохраняет лицензию рядом с банком в `assets/GeneralUser-GS-LICENSE.txt`.
  Условия: https://github.com/mrbumpy409/GeneralUser-GS/blob/main/documentation/LICENSE.txt
- **NanoMaestro Light**, автор `utkucoban` — CC-BY-NC-4.0.
  https://huggingface.co/utkucoban/NanoMaestro-Realtime
  Закреплённая ревизия: `9a64dd24b3a550a6101f868af71bdc9960376e26`.
  Используется согласованная пара `model_int8_v2.onnx` / `vocabv2.json`.
  Модель предназначена для некоммерческого использования по её лицензии.
- **Piper 1.8**, OHF-Voice — GPL-3.0, локальный синтез речи:
  https://github.com/OHF-Voice/piper1-gpl
  Голос **ru_RU-denis-medium**, один русский мужской голос, около 63 МБ:
  https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU/denis/medium
  Закреплённая ревизия: `5041a7a49ae5b3a0f30e6837769eb03fdbb231bd`.
  В карточке голоса указана лицензия CC0 для обучающего набора данных.
  Установщик сохраняет исходную карточку в `assets/speech/MODEL_CARD`.

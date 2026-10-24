# SemenBanan 🍌

Telegram-бот Семён: отвечает в разрешённых группах через OpenClaw Gateway и создаёт музыкальные голосовые сообщения и картинки. История, настройки характера и очередь ответов сохраняются локально. Режим ответа и параметры музыки определяет LLM через OpenClaw по сообщению и контексту чата.

## Быстрый запуск

Нужны **Python 3.13**, Telegram-бот и настроенный OpenClaw Gateway с endpoint `/v1/chat/completions` и агентом `semyon`.

1. Добавь бота в группу и отключи privacy через BotFather. После изменения privacy добавь бота в группу заново.
2. Создай `.env` по образцу `.env.example`, если файла ещё нет. Заполни токены, адрес Gateway и `ALLOWED_CHAT_IDS`.
3. Выполни из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

При первом запуске скрипт создаст окружение Python 3.13, установит пакет с зависимостями и загрузит музыкальные ресурсы. Напиши «Семён, ты тут?» или «Семён, сыграй 30 секунд при 85 BPM, гитара и бас, без голоса, бас 40%». Остановка — Ctrl+C.

Фоновый запуск и остановка:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Background
powershell -ExecutionPolicy Bypass -File .\stop.ps1
```

## Диагностика и проверка генерации

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 --check
powershell -ExecutionPolicy Bypass -File .\start.ps1 --check-gateway
powershell -ExecutionPolicy Bypass -File .\start.ps1 --check-music
powershell -ExecutionPolicy Bypass -File .\start.ps1 --check-image
```

`--check` проверяет Telegram и ответ модели; `--check-gateway` — только модель. `--check-music` определяет режим и параметры через LLM, запрашивает ноты и аранжировку, запускает отдельный генератор, сводит дорожки и сохраняет OGG в `.runtime/checks/music.ogg`. Сообщения в Telegram не отправляются. Запросы к модели реальные.

Музыка поддерживает длительность 5–60 секунд, темп 60–180 BPM, до четырёх инструментов и громкость каждой дорожки 0–100%. Без новых параметров сохраняется прежний режим.

Для проверки NanoMaestro или другого состава дорожек:

```powershell
.\.venv\Scripts\python.exe -m semen_banan --check-music --request "Сыграй через NanoMaestro без речи" --output .runtime/checks/nano.ogg
```

Если ID группы неизвестен, останови основной экземпляр и запусти `start.ps1 --discover-chats`. Отправь сообщение в группе, перенеси выведенный ID в `.env` и заверши режим через Ctrl+C. Одновременно должен работать только один получатель обновлений Telegram. Остальные диагностические режимы не используют polling и могут работать рядом с ботом.

## Код и данные

- `src/semen_banan/` — приложение: диалоги, интеграции, хранение и аудио.
- `tests/unit/`, `tests/integration/` — быстрые и интеграционные проверки.
- `tools/` — установка ресурсов и инструменты сравнения музыки.
- `pyproject.toml` — зависимости, Python 3.13 и настройки инструментов.
- [`src/semen_banan/resources/prompts.toml`](src/semen_banan/resources/prompts.toml) — все промпты, характер персонажа и проверочные запросы.
- `assets/` — локальные модели; `.runtime/` — журналы и результаты диагностики.

Рабочие `.env`, `memory.sqlite3` и `state.json` остаются в корне. Не публикуй секреты и переписку. Не удаляй файлы SQLite при работающем боте.

## Проверки разработки

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[music,dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m mypy
```

Интеграционные проверки требуют музыкальных ресурсов. Быстрый прогон: `python -m unittest discover -s tests/unit -v`.

[Подробная инструкция](docs/usage.md) · [Архитектура](docs/architecture.md) · [Стиль кода](docs/code-style.md) · [Лицензии компонентов](THIRD_PARTY.md)

Голос настраивается в просьбе: «Семён, музыку с речью, голос ниже на 3 полутона, скорость 0.85, лёгкое эхо». Доступны локальные эффекты робота, телефона, эха, реверберации и хора. Подробности — в [инструкции](docs/usage.md#настройки-локального-голоса).

Модель подбирает инструменты по жанру и настроению запроса. Для тяжёлой музыки доступны электрогитары с овердрайвом и дисторшном, приглушённая электрогитара и электробас. Явно указанный состав имеет приоритет.

Речь по умолчанию создаёт локальная Silero v5.6 (Eugene); доступны ещё четыре голоса и прежний Denis. Во время речи инструментал приглушается мягко, максимум примерно на 2 дБ.


Картинки: «Семён, нарисуй кота в космосе, акварель, вертикально». OpenClaw создаёт изображение, бот отправляет его ответом в ту же тему Telegram. Нужны доступный `openclaw infer image generate` и авторизация провайдера изображений. Для OpenClaw в WSL задай `OPENCLAW_IMAGE_WSL_DISTRO` и, при необходимости, `OPENCLAW_IMAGE_EXECUTABLE` в `.env`. Проверка `--check-image` сохраняет JPEG без отправки в чат. [Настройка картинок](docs/usage.md#генерация-картинок).

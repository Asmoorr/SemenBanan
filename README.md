# SemenBanan 🍌

Telegram-бот Семён: отвечает в разрешённых группах через OpenClaw Gateway и создаёт музыкальные голосовые сообщения. История, настройки характера и очередь ответов сохраняются локально.

## Быстрый запуск

Нужны **Python 3.13**, Telegram-бот и настроенный OpenClaw Gateway с endpoint `/v1/chat/completions` и агентом `semyon`.

1. Добавь бота в группу и отключи privacy через BotFather. После изменения privacy добавь бота в группу заново.
2. Создай `.env` по образцу `.env.example`, если файла ещё нет. Заполни токены, адрес Gateway и `ALLOWED_CHAT_IDS`.
3. Выполни из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

При первом запуске скрипт создаст окружение Python 3.13, установит пакет с зависимостями и загрузит музыкальные ресурсы. Напиши «Семён, ты тут?» или «Семён, сыграй только пианино». Остановка — Ctrl+C.

Фоновый запуск и остановка:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Background
powershell -ExecutionPolicy Bypass -File .\stop.ps1
```

## Диагностика и проверка музыки

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 --check
powershell -ExecutionPolicy Bypass -File .\start.ps1 --check-gateway
powershell -ExecutionPolicy Bypass -File .\start.ps1 --check-music
```

`--check` проверяет Telegram и ответ модели; `--check-gateway` — только модель. `--check-music` запрашивает ноты и аранжировку, запускает отдельный генератор, сводит дорожки и сохраняет OGG в `.runtime/checks/music.ogg`. Сообщения в Telegram не отправляются. Запросы к модели реальные.

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

[Подробная инструкция](docs/usage.md) · [Архитектура](docs/architecture.md) · [Лицензии компонентов](THIRD_PARTY.md)

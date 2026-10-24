<div align="center">

![Белая волна](https://capsule-render.vercel.app/api?type=waving&color=FFFFFF&height=100&section=header)

# Семён Банан

### Шестой участник "Закулисья"

`† Разговоры после полуночи` · `† Музыка из подвала` · `† Образы из тьмы`

Telegram-бот с характером и памятью 🦇🖤<br />
Общается через **OpenClaw**, создаёт музыку, голосовые сообщения и картинки,<br />
знает участников группы и выбирает реакции по смыслу переписки

```text
        /\_/\
       ( o.o )   †
        >🍌<
```

### Технологии

![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&labelColor=000000&logo=python&logoColor=FFD43B)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Gateway-713747?style=for-the-badge&labelColor=000000)
![Telegram](https://img.shields.io/badge/Telegram-Bot_API-267A9E?style=for-the-badge&labelColor=000000&logo=telegram&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Memory-52616B?style=for-the-badge&labelColor=000000&logo=sqlite&logoColor=white)

![Silero](https://img.shields.io/badge/Silero-Local_TTS-66537A?style=flat-square&labelColor=000000)
![PyTorch](https://img.shields.io/badge/PyTorch-Audio-9B4235?style=flat-square&labelColor=000000&logo=pytorch&logoColor=EE4C2C)
![Ruff](https://img.shields.io/badge/Ruff-Lint-687349?style=flat-square&labelColor=000000&logo=ruff&logoColor=D7FF64)
![mypy](https://img.shields.io/badge/mypy-Types-626A86?style=flat-square&labelColor=000000)

🕯 ────────────── † ────────────── 🕯

</div>

## Запуск

Нужны **Python 3.13**, Telegram-бот и настроенный **OpenClaw Gateway**. Подготовь `.env` по [образцу](.env.example) — порядок настройки описан в [инструкции](docs/usage.md)

Запуск из папки проекта, остановка — `Ctrl+C`:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Первый запуск создаст окружение, установит зависимости и загрузит музыкальные ресурсы

Фоновый запуск и остановка:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Background
powershell -ExecutionPolicy Bypass -File .\stop.ps1
```

## Документация

| Вопрос | Куда заглянуть |
| :--- | :--- |
| Установка, OpenClaw и параметры `.env` | [Настройка проекта](docs/usage.md#установка-вручную) |
| Музыка и голос | [Параметры генерации](docs/usage.md#точные-параметры-музыкальной-записи) |
| Картинки и фото участников | [Изображения](docs/usage.md#генерация-картинок) · [Сведения о группе](docs/usage.md#сведения-о-группе-и-фотографии-участников) |
| Случайные ответы, реакции и вероятности | [Ответы](docs/usage.md#случайные-ответы-и-оформление) · [Реакции](docs/usage.md#реакции-на-сообщения) |
| Диагностика и тестирование | [Диагностика](docs/usage.md#диагностические-режимы) · [Проверки разработки](docs/usage.md#проверки-разработки) |
| Модули, данные и устройство приложения | [Архитектура](docs/architecture.md) |
| Промпты и правила разработки | [Промпты](docs/usage.md#редактирование-промптов) · [Стиль кода](docs/code-style.md) |

[Лицензии компонентов](THIRD_PARTY.md)

<div align="center">

🕯 ────────────── † ────────────── 🕯

<sub>Собран из кода, риффов и бананов · Не будить без контекста (¬､¬) 🦇🖤🍌</sub>

![Белая волна](https://capsule-render.vercel.app/api?type=waving&color=FFFFFF&height=100&section=footer)

</div>

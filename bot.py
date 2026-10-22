"""Семён: reactive Telegram bot backed by an OpenClaw Gateway."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from memory import ConversationStore, STYLE_CHANGE
from music import music_requested, parse_score
from arrangement import parse_arrangement
from audio_job import render_audio

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("semyon")
NAME = re.compile(r"(?<![\w@])(?:семен|семён(?:а|у|ом|е)?|сеня|сень|сенечка)(?!\w)", re.I)
BANANA = re.compile(r"(?<!\w)(?:банан[а-яё]*|bananas?)(?!\w)|🍌", re.I)


class BotError(Exception):
    """A user-readable error that never includes credential-bearing URLs."""


@dataclass(frozen=True)
class Settings:
    token: str
    chats: frozenset[int]
    base_url: str
    gateway_token: str
    agent: str = "semyon"
    cooldown: float = 10
    probability: float = 0.25
    timeout: float = 90
    audio_timeout: float = 90

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(ROOT / ".env")
        try:
            settings = cls(
                token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
                chats=frozenset(int(v.strip()) for v in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if v.strip()),
                base_url=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/"),
                gateway_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip(),
                agent=os.getenv("OPENCLAW_AGENT_ID", "semyon").strip(),
                cooldown=float(os.getenv("COOLDOWN_SECONDS", "10")),
                probability=float(os.getenv("BANANA_PROBABILITY", "0.25")),
                timeout=float(os.getenv("REQUEST_TIMEOUT", "90")),
                audio_timeout=float(os.getenv("AUDIO_TIMEOUT_SECONDS", "90")),
            )
        except ValueError:
            raise BotError("Проверь числовые значения в .env.") from None
        if not all(math.isfinite(v) for v in (settings.cooldown, settings.probability, settings.timeout, settings.audio_timeout)):
            raise BotError("Числовые настройки должны быть конечными.")
        if settings.cooldown < 0 or not 0 <= settings.probability <= 1 or settings.timeout <= 0 or settings.audio_timeout <= 0:
            raise BotError("Неверные интервалы или вероятность в .env.")
        parsed = urlsplit(settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise BotError("OPENCLAW_BASE_URL должен быть HTTP(S)-адресом без токена.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", settings.agent):
            raise BotError("Неверный OPENCLAW_AGENT_ID.")
        return settings


def trigger(message: dict[str, Any], username: str, bot_id: int) -> str | None:
    text = message.get("text") or message.get("caption") or ""
    replied_to = message.get("reply_to_message") or {}
    if replied_to.get("from", {}).get("id") == bot_id:
        return "direct"
    entities = message.get("entities") or message.get("caption_entities") or []
    for entity in entities:
        if entity.get("type") == "text_mention" and entity.get("user", {}).get("id") == bot_id:
            return "direct"
    if username and re.search(r"(?<!\w)@" + re.escape(username) + r"(?!\w)", text, re.I):
        return "direct"
    if NAME.search(text):
        return "direct"
    return "banana" if BANANA.search(text) else None


class Telegram:
    def __init__(self, client: httpx.AsyncClient, token: str):
        self.client = client
        self.url = f"https://api.telegram.org/bot{token}"

    async def call(self, method: str, **payload: Any) -> Any:
        try:
            response = await self.client.post(f"{self.url}/{method}", json=payload, timeout=40)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise BotError(f"Telegram: сеть или неверный ответ ({method}).") from None
        if not data.get("ok"):
            code = data.get("error_code", response.status_code)
            hint = {401: "неверный токен", 403: "бот удалён или нет прав", 409: "другой процесс или webhook", 429: "лимит запросов"}.get(code, "проверь настройки и права бота")
            raise BotError(f"Telegram {code}: {hint} ({method}).")
        return data["result"]

    async def send_voice(self, chat_id: int, message_id: int, voice: bytes,
                         duration: int, topic: int = 0) -> Any:
        fields = {"chat_id": str(chat_id), "duration": str(duration),
                  "reply_parameters": json.dumps({"message_id": message_id,
                                                   "allow_sending_without_reply": False})}
        if topic:
            fields["message_thread_id"] = str(topic)
        try:
            response = await self.client.post(
                f"{self.url}/sendVoice", data=fields,
                files={"voice": ("semyon-piano.ogg", voice, "audio/ogg")}, timeout=90)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise BotError("Telegram: не удалось отправить голосовое сообщение.") from None
        if not data.get("ok"):
            raise BotError(f"Telegram {data.get('error_code', response.status_code)}: ошибка отправки голосового.")
        return data["result"]


class Gateway:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings
        self.persona = (ROOT / "persona.txt").read_text(encoding="utf-8")

    async def reply(self, context: list[dict[str, str]], current: dict[str, str],
                    style_requests: list[str] | None = None) -> str:
        return (await self._complete(self.persona, json.dumps(
            {"conversation_chain": context, "reply_to": current,
             "character_requests": style_requests or []}, ensure_ascii=False)))[:1200]

    async def compose(self, context: list[dict[str, str]], current: dict[str, str]) -> str:
        system = (
            "Ты музыкальный композитор Семён. Придумай короткую оригинальную мелодию для простого пианино "
            "по запросу пользователя. Ответь ТОЛЬКО JSON без пояснений: "
            '{"tempo":100,"melody":[{"midi":64,"beats":1}],"chords":[[48,52,55],[50,53,57],[48,52,55],[43,47,50]]}. '
            "Темп целое 70–140. Мелодия: 8–40 нот MIDI 48–84, длительности по четвертям "
            "0.25–4 с шагом 0.25, суммарно ровно 16 долей (4 такта 4/4). "
            "chords: ровно 4 трезвучия по 3 ноты MIDI 40–72, по одному на такт. "
            "Сделай мелодию выразительной, гармоничной, запоминающейся. Не вызывай инструменты."
        )
        return await self._complete(system, json.dumps(
            {"conversation_chain": context[-8:], "request": current}, ensure_ascii=False), 12000)

    async def arrange(self, context: list[dict[str, str]], current: dict[str, str], beats: int = 16,
                      style_requests: list[str] | None = None) -> str:
        system = (self.persona + "\nРежим аранжировки: выдай ТОЛЬКО JSON с барабанами и речью. "
                  'Формат: {"drums":[{"midi":36,"beat":0,"velocity":70}],'
                  '"speech":[{"beat":0,"text":"С вами Семён. Бананы в студию."}]}. '
                  "drums — повторяющийся рисунок одного такта 4/4, от 1 до 32 ударов, "
                  "beat от 0 до 3.75 с шагом 0.25, velocity 25–105. "
                  "Допустимые MIDI: 35,36 бочка; 38,39 малый и хлопок; 42,44,46 хэты; 49,51 тарелки. "
                  "Сделай негромкий ритм, подходящий к просьбе, без перегруза тарелками. "
                  f"Всего в пьесе {beats} долей. speech — короткие русские фразы Семёна поверх музыки, "
                  f"каждая максимум 80 символов, beat от 0 до {beats - 4}. "
                  + ("Одна фраза максимум 45 символов на beat 0." if beats <= 16 else
                     "Две-три фразы максимум 60 символов каждая. Разнеси их на 16–20 долей.") +
                  " Это разговорная речь, не пение. Не имитируй голоса реальных людей. Не вызывай инструменты.")
        return await self._complete(system, json.dumps(
            {"conversation_chain": context[-4:], "request": current,
             "character_requests": style_requests or []}, ensure_ascii=False), 6000)

    async def _complete(self, system: str, user: str, limit: int = 1200) -> str:
        headers = {"Authorization": f"Bearer {self.settings.gateway_token}"} if self.settings.gateway_token else {}
        # No stable user/session key: persisted chain context is supplied explicitly.
        payload = {
            "model": f"openclaw/{self.settings.agent}", "stream": False,
            "tool_choice": "none",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        base = self.settings.base_url
        endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        try:
            response = await self.client.post(endpoint, json=payload, headers=headers, timeout=self.settings.timeout)
        except httpx.HTTPError:
            raise BotError("Gateway недоступен или истекло время ответа.") from None
        if response.status_code != 200:
            hint = {401: "проверь токен Gateway и авторизацию модели", 403: "проверь доступ", 404: "включи chatCompletions и проверь агента semyon"}.get(response.status_code, "проверь журнал OpenClaw")
            raise BotError(f"Gateway HTTP {response.status_code}: {hint}.")
        try:
            message = response.json()["choices"][0]["message"]
            content = message["content"]
            if message.get("tool_calls") or not isinstance(content, str) or not content.strip():
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise BotError("Gateway вернул пустой ответ или вызов инструмента.") from None
        return content.strip()[:limit]


class Semyon:
    def __init__(self, settings: Settings, telegram: Telegram, gateway: Gateway, me: dict[str, Any], state_path: Path = ROOT / "state.json"):
        self.settings, self.telegram, self.gateway, self.me = settings, telegram, gateway, me
        self.state_path = state_path
        self.memory = ConversationStore(state_path.with_name("memory.sqlite3"))
        self.last: dict[str, float] = {}
        if state_path.exists():
            try:
                self.last = {k: float(v) for k, v in json.loads(state_path.read_text()).items()}
                if not all(math.isfinite(v) for v in self.last.values()):
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise BotError("Повреждён state.json: переименуй его и повтори запуск.") from None

    def save(self) -> None:
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.last), encoding="utf-8")
        temp.replace(self.state_path)

    async def handle(self, message: dict[str, Any]) -> None:
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        sender = message.get("from", {})
        LOG.info("Получено: chat_id=%s, type=%s, text=%s, sender_bot=%s", chat_id, chat.get("type"), bool(message.get("text") or message.get("caption")), sender.get("is_bot"))
        if chat_id not in self.settings.chats or chat.get("type") not in {"group", "supergroup"}:
            LOG.info("Пропуск: группа не разрешена")
            return
        if sender.get("is_bot") or message.get("sender_chat"):
            LOG.info("Пропуск: сообщение от бота или анонимного администратора")
            return
        text = message.get("text") or message.get("caption")
        if not text or time.time() - message.get("date", 0) > 120:
            LOG.info("Пропуск: нет текста или сообщение старше двух минут")
            return
        replied_to = message.get("reply_to_message") or {}
        parent_id = replied_to.get("message_id")
        base_kind = trigger(message, self.me["username"], self.me["id"])
        style_change = bool(STYLE_CHANGE.search(text))
        music_change = music_requested(text)
        in_chain = self.memory.record_incoming(message, self.me["id"], base_kind == "direct" or style_change)
        if style_change:
            self.memory.add_style_request(chat_id, text)
            LOG.info("Изменение характера сохранено: chat_id=%s", chat_id)
        kind = ("music" if music_change else
                "direct" if base_kind == "direct" else
                "chain" if parent_id is not None and in_chain else
                "style" if style_change else base_kind)
        if not kind:
            LOG.info("Пропуск: нет обращения, цепочки или банана")
            return
        if kind == "banana" and random.random() >= self.settings.probability:
            LOG.info("Пропуск: вероятность 25%%")
            return
        await self.respond(message, kind)

    async def respond(self, message: dict[str, Any], kind: str) -> None:
        chat_id = message["chat"]["id"]
        topic = message.get("message_thread_id") or 0
        key = str(chat_id)
        now = time.time()
        if now - self.last.get(key, 0) < self.settings.cooldown:
            if kind != "banana":
                self.memory.queue_reply(message, kind, self.last[key] + self.settings.cooldown)
                LOG.info("Ответ поставлен в очередь: chat_id=%s, message_id=%s, trigger=%s",
                         chat_id, message["message_id"], kind)
            else:
                LOG.info("Пропуск: интервал 10 секунд, trigger=banana")
            return
        # Reserve before network I/O; failures stay silent and cannot cause a request storm.
        self.last[key] = now
        self.save()
        try:
            sender = message.get("from") or {}
            text = message.get("text") or message.get("caption") or ""
            current = {"name": sender.get("first_name", "Участник")[:80], "text": text[:2000]}
            replied_to = message.get("reply_to_message") or {}
            parent_id = replied_to.get("message_id")
            if replied_to.get("from", {}).get("id") == self.me["id"]:
                quoted = replied_to.get("text") or replied_to.get("caption")
                if quoted:
                    current["in_reply_to_semyon"] = quoted[:1200]
            context = self.memory.context(chat_id, topic, parent_id, message["message_id"])
            if kind == "music":
                score = None
                for attempt in range(2):
                    composition = await self.gateway.compose(context, current)
                    try:
                        score = parse_score(composition)
                        break
                    except ValueError:
                        if attempt:
                            raise BotError("Модель дважды вернула неверные ноты.") from None
                try:
                    use_nano = bool(re.search(r"\b(?:nano(?:maestro)?|наномаэстро|наномаестро|локальн\w*)\b", text, re.I))
                    solo = bool(re.search(r"только\s+(?:на\s+)?(?:пианино|роял[ье])", text, re.I))
                    arrangement = None
                    if not solo:
                        for attempt in range(2):
                            try:
                                arrangement = parse_arrangement(await self.gateway.arrange(
                                    context, current, style_requests=self.memory.style_requests(chat_id)))
                                break
                            except RuntimeError:
                                if attempt:
                                    raise
                        if re.search(r"без\s+(?:речи|голоса|слов)", text, re.I):
                            arrangement["speech"] = []
                        if re.search(r"без\s+(?:барабанов|ударных)", text, re.I):
                            arrangement["drums"] = []
                    audio = await render_audio(score, use_nano, arrangement, timeout=self.settings.audio_timeout)
                except RuntimeError as exc:
                    raise BotError(str(exc)) from None
                sent = await self.telegram.send_voice(chat_id, message["message_id"], audio.voice, audio.duration, topic)
                parts = ["пианино"]
                if not solo and arrangement["drums"]:
                    parts.append("барабаны")
                if not solo and arrangement["speech"]:
                    parts.append("речь")
                answer = ("[Семён записал: " + ", ".join(parts) +
                          (", NanoMaestro]" if use_nano else "]"))
            else:
                answer = await self.gateway.reply(context, current, self.memory.style_requests(chat_id))
                payload: dict[str, Any] = {
                    "chat_id": chat_id, "text": answer,
                    "reply_parameters": {"message_id": message["message_id"], "allow_sending_without_reply": False},
                    "link_preview_options": {"is_disabled": True},
                }
                if topic:
                    payload["message_thread_id"] = topic
                sent = await self.telegram.call("sendMessage", **payload)
            self.memory.record_bot(sent, chat_id, topic, message["message_id"], answer)
            self.memory.forget_reply(chat_id, message["message_id"])
            LOG.info("Ответ отправлен: chat_id=%s, trigger=%s", chat_id, kind)
        except BotError as exc:
            LOG.warning("%s", exc)
            if kind != "banana":
                self.memory.queue_reply(message, kind, time.time() + 30)
        finally:
            self.last[key] = time.time()
            self.save()

    async def process_pending(self) -> None:
        for _ in range(20):
            pending = self.memory.due_reply(time.time())
            if pending is None:
                return
            message, kind = pending
            chat_id = message["chat"]["id"]
            message_id = message["message_id"]
            if chat_id not in self.settings.chats or time.time() - message.get("date", 0) > 600:
                self.memory.forget_reply(chat_id, message_id)
                LOG.info("Устаревший отложенный ответ удалён: chat_id=%s, message_id=%s", chat_id, message_id)
                continue
            await self.respond(message, kind)


async def run(mode: str) -> None:
    settings = Settings.load()
    async with httpx.AsyncClient(follow_redirects=False) as client, httpx.AsyncClient(follow_redirects=False, trust_env=False) as gateway_client:
        gateway = Gateway(gateway_client, settings)
        if mode == "check-gateway":
            answer = await gateway.reply([], {"name": "Проверка", "text": "Семён, скажи одним словом: банан"})
            print("Gateway отвечает:", answer)
            return
        if not settings.token:
            raise BotError("Заполни TELEGRAM_BOT_TOKEN в .env.")
        telegram = Telegram(client, settings.token)
        me = await telegram.call("getMe")
        if mode == "check":
            print(f"Telegram OK: @{me['username']}; ID {me['id']}")
            answer = await gateway.reply([], {"name": "Проверка", "text": "Семён, скажи одним словом: банан"})
            print("Gateway OK:", answer)
            return
        if mode == "run" and not settings.chats:
            raise BotError("Сначала --discover-chats, затем заполни ALLOWED_CHAT_IDS.")
        if (await telegram.call("getWebhookInfo")).get("url"):
            raise BotError("У бота уже настроен webhook. Отключи прежнюю интеграцию; см. README.")
        # Discard offline backlog so starting the script never causes unsolicited replies.
        tail = await telegram.call("getUpdates", offset=-1, timeout=0, allowed_updates=[])
        offset = tail[-1]["update_id"] + 1 if tail else 0
        bot = Semyon(settings, telegram, gateway, me)
        print("Режим поиска групп: напиши /id в группе, ID появится здесь." if mode == "discover-chats" else f"Семён @{me['username']} слушает группу. Остановка: Ctrl+C.", flush=True)
        while True:
            if mode == "run":
                await bot.process_pending()
            next_due = bot.memory.next_reply_due() if mode == "run" else None
            poll_timeout = 25 if next_due is None else max(1, min(25, math.ceil(next_due - time.time())))
            try:
                updates = await telegram.call("getUpdates", offset=offset, timeout=poll_timeout, allowed_updates=[])
            except BotError as exc:
                if "409" in str(exc) or "401" in str(exc):
                    raise
                LOG.warning("%s Повтор через 10 секунд.", exc)
                await asyncio.sleep(10)
                continue
            for update in updates:
                LOG.info("Telegram update_id=%s, type=%s", update.get("update_id"), next((key for key in update if key != "update_id"), "unknown"))
                offset = update["update_id"] + 1
                message = update.get("message", {})
                if mode == "discover-chats":
                    chat = message.get("chat", {})
                    if chat.get("type") in {"group", "supergroup"}:
                        print(f"ALLOWED_CHAT_IDS={chat['id']}  ({chat.get('title', '')})", flush=True)
                else:
                    await bot.handle(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--discover-chats", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--check-gateway", action="store_true")
    args = parser.parse_args()
    mode = "discover-chats" if args.discover_chats else "check-gateway" if args.check_gateway else "check" if args.check else "run"
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    LOG.setLevel(logging.INFO)
    try:
        asyncio.run(run(mode))
    except KeyboardInterrupt:
        print("Семён спит.")
    except (BotError, OSError) as exc:
        print(f"Не удалось продолжить: {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

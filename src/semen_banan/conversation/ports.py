from __future__ import annotations

from typing import Any, Protocol

from semen_banan.conversation.models import (
    ContextMessage,
    ConversationContext,
    Correction,
    RecentMessage,
    RoutingMetadata,
    StoredMessage,
    TelegramMessage,
)


class Telegram(Protocol):
    """Контракт внешних операций Telegram."""

    async def call(self, method: str, **payload: Any) -> Any:
        """Выполняет запрос Telegram и проверяет ответ API.

        :param method: Имя метода Telegram API.
        :param payload: Именованные параметры запроса Telegram.
        :return: Результат метода Telegram; его структура зависит от метода.
        """
        ...

    async def send_voice(
        self, chat_id: int, message_id: int, voice: bytes, duration: int, topic: int = 0
    ) -> Any:
        """Отправляет голосовое ответом на исходное сообщение.

        :param chat_id: Идентификатор Telegram-группы.
        :param message_id: Идентификатор сообщения Telegram.
        :param voice: Байты голосового сообщения OGG/Opus.
        :param duration: Длительность записи в секундах.
        :param topic: Идентификатор темы группы, 0 для общего чата.
        :return: Ответ Telegram с данными отправленного сообщения.
        """
        ...

    async def send_photo(
        self, chat_id: int, message_id: int, photo: bytes, caption: str = "", topic: int = 0
    ) -> Any:
        """Отправляет картинку ответом в исходную тему Telegram.

        :param chat_id: Идентификатор группы.
        :param message_id: Идентификатор исходного сообщения.
        :param photo: Байты подготовленного JPEG.
        :param caption: Подпись изображения.
        :param topic: Идентификатор темы, ноль для общего чата.
        :return: Данные отправленного сообщения Telegram.
        """
        ...


class Gateway(Protocol):
    """Контракт запросов языковой модели через OpenClaw."""

    async def classify(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        metadata: RoutingMetadata,
        style_requests: list[str] | None = None,
        correction: Correction | None = None,
    ) -> str:
        """Запрашивает у модели режим обработки и параметры сообщения.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param metadata: Признаки обращения, цепочки и личность бота.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :param correction: Причина ошибки и предыдущий JSON для исправления.
        :return: JSON-ответ маршрутизатора модели.
        """
        ...

    async def reply(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        style_requests: list[str] | None = None,
    ) -> str:
        """Получает текстовую реплику с учётом контекста и характера.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :return: Текст ответа Семёна.
        """
        ...

    async def compose(
        self, conversation_context: ConversationContext, current_message: ContextMessage
    ) -> str:
        """Получает ноты для заданной партитуры.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :return: Последовательность нот для озвучивания.
        """
        ...

    async def arrange(
        self,
        conversation_context: ConversationContext,
        current_message: ContextMessage,
        beats: int = 16,
        style_requests: list[str] | None = None,
        correction: Correction | None = None,
    ) -> str:
        """Запрашивает у модели барабаны и речевые фразы.

        :param conversation_context: Контекст текущей темы или цепочки сообщений.
        :param current_message: Текущее сообщение в формате контекста модели.
        :param beats: Длительность пьесы в музыкальных долях.
        :param style_requests: Сохранённые пожелания к характеру и манере речи.
        :param correction: Причина ошибки и предыдущий JSON для исправления.
        :return: JSON аранжировки для дальнейшей проверки.
        """
        ...


class Cooldowns(Protocol):
    """Контракт сохранения интервалов между ответами."""

    def load(self) -> dict[str, float]:
        """Загружает и проверяет настройки компонента.

        :return: Проверенные настройки компонента.
        """
        ...

    def save(self, values: dict[str, float]) -> None:
        """Сохраняет интервалы между ответами в рабочем файле.

        :param values: Сохранённые временные метки последних ответов.
        :return: Не возвращает значение.
        """
        ...


class ConversationStore(Protocol):
    """Контракт истории, характера и очереди ответов."""

    def get(self, chat_id: int, message_id: int | None) -> StoredMessage | None:
        """Находит сохранённое сообщение по группе и идентификатору.

        :param chat_id: Идентификатор Telegram-группы.
        :param message_id: Идентификатор сообщения Telegram.
        :return: Запись сообщения либо None, если её нет.
        """
        ...

    def recent_messages(self, chat_id: int, topic_id: int, current_id: int) -> list[RecentMessage]:
        """Читает последние сообщения одной темы до текущего сообщения.

        :param chat_id: Идентификатор Telegram-группы.
        :param topic_id: Идентификатор темы группы, 0 для общего чата.
        :param current_id: Идентификатор текущего сообщения.
        :return: До двенадцати записей от новых к старым.
        """
        ...

    def record_incoming(self, message: TelegramMessage, bot_id: int, direct: bool) -> bool:
        """Сохраняет сообщение и его принадлежность цепочке бота.

        :param message: Исходное сообщение Telegram.
        :param bot_id: Идентификатор бота в Telegram.
        :param direct: Признак начала или продолжения цепочки обращения к боту.
        :return: Признак включения сообщения в цепочку Семёна.
        """
        ...

    def record_bot(
        self, sent: dict[str, Any], chat_id: int, topic_id: int, parent_id: int, body: str
    ) -> None:
        """Сохраняет отправленный ответ и его связь с исходным сообщением.

        :param sent: Данные отправленного ответа Telegram.
        :param chat_id: Идентификатор Telegram-группы.
        :param topic_id: Идентификатор темы группы, 0 для общего чата.
        :param parent_id: Идентификатор родительского сообщения либо None.
        :param body: Текст ответа для сохранения в истории.
        :return: Не возвращает значение.
        """
        ...

    def add_style_request(self, chat_id: int, text: str) -> None:
        """Сохраняет пожелание к характеру бота для группы.

        :param chat_id: Идентификатор Telegram-группы.
        :param text: Текст сообщения или речевой фразы.
        :return: Не возвращает значение.
        """
        ...

    def style_requests(self, chat_id: int) -> list[str]:
        """Читает последние пожелания к характеру для группы.

        :param chat_id: Идентификатор Telegram-группы.
        :return: До пяти инструкций в порядке поступления.
        """
        ...

    def queue_reply(self, message: TelegramMessage, kind: str, due_at: float) -> None:
        """Добавляет или обновляет отложенное задание вместе с параметрами.

        :param message: Исходное сообщение Telegram.
        :param kind: Тип композитора или отложенного задания.
        :param due_at: Временная метка следующей попытки обработки.
        :return: Не возвращает значение.
        """
        ...

    def next_reply_due(self) -> float | None:
        """Определяет ближайшее время обработки очереди.

        :return: Временная метка либо None, если очередь пуста.
        """
        ...

    def due_reply(self, now: float) -> tuple[TelegramMessage, str] | None:
        """Выбирает первое задание, срок обработки которого наступил.

        :param now: Текущая временная метка.
        :return: Сообщение и вид задания либо None.
        """
        ...

    def forget_reply(self, chat_id: int, message_id: int) -> None:
        """Удаляет обработанное или устаревшее задание.

        :param chat_id: Идентификатор Telegram-группы.
        :param message_id: Идентификатор сообщения Telegram.
        :return: Не возвращает значение.
        """
        ...

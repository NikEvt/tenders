"""Потребление событий: разбор конверта, идемпотентность, ретраи."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import aio_pika
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractIncomingMessage,
    AbstractRobustConnection,
)

from libs.shared.contracts.events import EVENT_BY_ROUTING_KEY, RETRY_EXCHANGE, Event
from libs.shared.logging import get_logger, set_correlation_id
from libs.shared.messaging.topology import (
    QueueSpec,
    declare_consumer_queues,
)

log = get_logger(__name__)

Handler = Callable[[Event], Awaitable[None]]

_ATTEMPT_HEADER = "x-attempt"


class IdempotencyStore(Protocol):
    """Хранилище обработанных message_id (таблица `processed_messages`).

    Протокол, а не ABC, — чтобы `libs.shared` не тянул зависимость на слой БД.
    """

    async def seen(self, message_id: str, consumer: str) -> bool: ...

    async def mark(self, message_id: str, consumer: str) -> None: ...


class RetryableError(Exception):
    """Ошибка, которую имеет смысл повторить (недоступен внешний сервис, таймаут)."""


class PermanentError(Exception):
    """Ошибка, которую повторять бессмысленно (битые данные) — сразу в dead-letter."""


class EventConsumer:
    """Подписка очереди на набор обработчиков по routing key.

    Ошибка обработчика приводит к публикации сообщения в очередь ретрая нужного
    уровня; исходное сообщение при этом подтверждается — иначе оно останется
    в рабочей очереди и продублируется.
    """

    def __init__(
        self,
        connection: AbstractRobustConnection,
        spec: QueueSpec,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self._connection = connection
        self._spec = spec
        self._idempotency = idempotency
        self._handlers: dict[str, Handler] = {}
        self._retry_exchange: AbstractExchange | None = None
        self._channel: AbstractChannel | None = None

    def on(self, event_type: type[Event], handler: Handler) -> None:
        self._handlers[event_type.routing_key] = handler

    async def run(self) -> None:
        channel = await self._connection.channel()
        self._channel = channel
        queue = await declare_consumer_queues(channel, self._spec)
        self._retry_exchange = await channel.get_exchange(RETRY_EXCHANGE)
        log.info("consumer.started", queue=self._spec.name, keys=list(self._handlers))
        await queue.consume(self._on_message)

    async def set_prefetch(self, prefetch: int) -> None:
        """Меняет `basic.qos` на живом канале — под смену уровня нагрузки.

        Уже выданные сообщения не отзываются: новый потолок действует со
        следующей выдачи. Поэтому сужение видно не мгновенно, а по мере того,
        как воркер разбирает то, что уже взял.
        """
        if self._channel is None:
            log.warning("consumer.prefetch_before_start", queue=self._spec.name)
            return
        await self._channel.set_qos(prefetch_count=max(int(prefetch), 1))
        log.info("consumer.prefetch_changed", queue=self._spec.name, prefetch=prefetch)

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        # requeue=False: при ошибке мы сами решаем судьбу сообщения (retry или dead).
        async with message.process(requeue=False, ignore_processed=True):
            routing_key = message.type or message.routing_key or ""
            event_cls = EVENT_BY_ROUTING_KEY.get(routing_key)
            handler = self._handlers.get(routing_key)

            if event_cls is None or handler is None:
                log.warning("event.unhandled", routing_key=routing_key)
                return

            set_correlation_id(message.correlation_id)
            message_id = message.message_id or ""

            if (
                self._idempotency
                and message_id
                and await self._idempotency.seen(message_id, self._spec.name)
            ):
                log.info("event.duplicate_skipped", event_id=message_id)
                return

            try:
                event = event_cls.model_validate_json(message.body)
            except Exception as exc:
                log.error("event.malformed", routing_key=routing_key, error=str(exc))
                await self._to_dead(message)
                return

            try:
                await handler(event)
            except PermanentError as exc:
                log.error("event.permanent_failure", routing_key=routing_key, error=str(exc))
                await self._to_dead(message)
                return
            except Exception as exc:
                log.warning("event.failed", routing_key=routing_key, error=str(exc), exc_info=True)
                await self._schedule_retry(message)
                return

            if self._idempotency and message_id:
                await self._idempotency.mark(message_id, self._spec.name)

    def _attempt(self, message: AbstractIncomingMessage) -> int:
        raw = message.headers.get(_ATTEMPT_HEADER, 0) if message.headers else 0
        try:
            return int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    async def _schedule_retry(self, message: AbstractIncomingMessage) -> None:
        attempt = self._attempt(message)
        if self._retry_exchange is None or attempt >= self._spec.max_attempts:
            log.error("event.retries_exhausted", attempts=attempt, queue=self._spec.name)
            await self._to_dead(message)
            return

        headers = dict(message.headers or {})
        headers[_ATTEMPT_HEADER] = attempt + 1
        await self._retry_exchange.publish(
            aio_pika.Message(
                body=message.body,
                content_type=message.content_type,
                message_id=message.message_id,
                correlation_id=message.correlation_id,
                type=message.type,
                headers=headers,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=self._spec.retry_queue(attempt),
        )
        log.info("event.retry_scheduled", attempt=attempt + 1, queue=self._spec.name)

    async def _to_dead(self, message: AbstractIncomingMessage) -> None:
        """Отклоняем без requeue — рабочая очередь сама отправит сообщение в DLX."""
        await message.reject(requeue=False)

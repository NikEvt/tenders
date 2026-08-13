"""Публикация событий в RabbitMQ."""

from __future__ import annotations

import json
from collections.abc import Sequence

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractRobustConnection

from libs.shared.contracts.events import Event
from libs.shared.contracts.ports import EventPublisher
from libs.shared.logging import get_correlation_id, get_logger
from libs.shared.messaging.topology import declare_exchanges

log = get_logger(__name__)


class RabbitPublisher(EventPublisher):
    """Прямая публикация в exchange.

    Годится там, где потеря события при падении между коммитом БД и publish не критична
    (например, повторный запуск обогащения). Для событий, порождающих внешние эффекты,
    используйте `OutboxPublisher`.
    """

    def __init__(self, connection: AbstractRobustConnection) -> None:
        self._connection = connection
        self._exchange: AbstractExchange | None = None

    async def setup(self) -> None:
        channel = await self._connection.channel()
        self._exchange = await declare_exchanges(channel)

    async def publish(self, event: Event) -> None:
        await self.publish_many([event])

    async def publish_many(self, events: Sequence[Event]) -> None:
        if self._exchange is None:
            raise RuntimeError("RabbitPublisher.setup() не вызван")
        for event in events:
            if event.correlation_id is None:
                event.correlation_id = get_correlation_id()
            message = aio_pika.Message(
                body=event.model_dump_json().encode(),
                content_type="application/json",
                message_id=str(event.event_id),
                correlation_id=event.correlation_id,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                type=event.routing_key,
            )
            await self._exchange.publish(message, routing_key=event.routing_key)
            log.debug(
                "event.published", routing_key=event.routing_key, event_id=str(event.event_id)
            )

    async def publish_raw(
        self,
        routing_key: str,
        payload: dict,
        event_id: str,
        correlation_id: str | None = None,
    ) -> None:
        """Публикация уже сериализованного события — используется outbox-relay.

        Relay не восстанавливает pydantic-модель из JSONB: тип события мог измениться
        с момента записи, а перепубликовать нужно ровно то, что было зафиксировано.
        """
        if self._exchange is None:
            raise RuntimeError("RabbitPublisher.setup() не вызван")
        message = aio_pika.Message(
            body=json.dumps(payload, ensure_ascii=False).encode(),
            content_type="application/json",
            message_id=event_id,
            correlation_id=correlation_id,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            type=routing_key,
        )
        await self._exchange.publish(message, routing_key=routing_key)
        log.debug("event.published", routing_key=routing_key, event_id=event_id)

"""Transactional outbox: надёжная публикация событий."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.contracts.events import Event
from libs.shared.contracts.ports import EventPublisher
from libs.shared.db.models import OutboxMessage, ProcessedMessage
from libs.shared.logging import get_correlation_id, get_logger
from libs.shared.messaging.consumer import IdempotencyStore
from libs.shared.messaging.publisher import RabbitPublisher

log = get_logger(__name__)

RELAY_BATCH_SIZE = 100
RELAY_INTERVAL_SECONDS = 2.0


class OutboxPublisher(EventPublisher):
    """Пишет событие в таблицу `outbox` в рамках уже открытой транзакции.

    Коммит делает вызывающий use-case — событие и данные фиксируются атомарно.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, event: Event) -> None:
        await self.publish_many([event])

    async def publish_many(self, events: Sequence[Event]) -> None:
        for event in events:
            if event.correlation_id is None:
                event.correlation_id = get_correlation_id()
            self._session.add(
                OutboxMessage(
                    event_id=str(event.event_id),
                    routing_key=event.routing_key,
                    payload=event.model_dump(mode="json"),
                    correlation_id=event.correlation_id,
                )
            )


class OutboxRelay:
    """Фоновая задача: вычитывает неопубликованные записи и шлёт их в RabbitMQ.

    `FOR UPDATE SKIP LOCKED` позволяет держать несколько реплик relay без дублей.
    Повторная публикация при падении после publish, но до отметки, безопасна —
    потребители дедуплицируют по `event_id` через `processed_messages`.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: RabbitPublisher,
        interval: float = RELAY_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._interval = interval
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        log.info("outbox_relay.started")
        while not self._stopped.is_set():
            try:
                sent = await self._drain_once()
            except Exception as exc:
                log.error("outbox_relay.error", error=str(exc), exc_info=True)
                sent = 0
            if sent == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)

    def stop(self) -> None:
        self._stopped.set()

    async def _drain_once(self) -> int:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        select(OutboxMessage)
                        .where(OutboxMessage.published_at.is_(None))
                        .order_by(OutboxMessage.id)
                        .limit(RELAY_BATCH_SIZE)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )

            if not rows:
                return 0

            published: list[int] = []
            for row in rows:
                try:
                    await self._publisher.publish_raw(
                        routing_key=row.routing_key,
                        payload=row.payload,
                        event_id=row.event_id,
                        correlation_id=row.correlation_id,
                    )
                    published.append(row.id)
                except Exception as exc:
                    row.attempts += 1
                    row.last_error = str(exc)[:1000]
                    log.warning(
                        "outbox_relay.publish_failed", event_id=row.event_id, error=str(exc)
                    )

            if published:
                await session.execute(
                    update(OutboxMessage)
                    .where(OutboxMessage.id.in_(published))
                    .values(published_at=func.now())
                )
            return len(published)


class SqlIdempotencyStore(IdempotencyStore):
    """Реализация дедупликации поверх таблицы `processed_messages`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def seen(self, message_id: str, consumer: str) -> bool:
        async with self._session_factory() as session:
            found = await session.scalar(
                select(ProcessedMessage.id).where(
                    ProcessedMessage.message_id == message_id,
                    ProcessedMessage.consumer == consumer,
                )
            )
            return found is not None

    async def mark(self, message_id: str, consumer: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                pg_insert(ProcessedMessage)
                .values(message_id=message_id, consumer=consumer)
                .on_conflict_do_nothing(constraint="uq_processed_message")
            )

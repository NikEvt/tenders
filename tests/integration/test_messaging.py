"""Шина событий: доставка, идемпотентность, ретраи, dead-letter, outbox."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from libs.shared.config import rabbit_settings
from libs.shared.contracts.events import TenderIngested
from libs.shared.db.models import OutboxMessage
from libs.shared.messaging.consumer import EventConsumer, PermanentError
from libs.shared.messaging.outbox import OutboxPublisher, OutboxRelay, SqlIdempotencyStore
from libs.shared.messaging.publisher import RabbitPublisher
from libs.shared.messaging.topology import QueueSpec, connect

# Ретрай-лестница начинается с 5 секунд — ждём чуть дольше первого уровня.
FIRST_RETRY_WAIT = 9.0
DELIVERY_WAIT = 5.0


@pytest_asyncio.fixture(scope="session")
async def connection() -> AsyncIterator:
    try:
        connection = await asyncio.wait_for(connect(rabbit_settings().dsn), timeout=10)
    except Exception as exc:  # pragma: no cover - зависит от окружения
        pytest.skip(f"RabbitMQ недоступен ({exc}); подними: docker compose up -d rabbitmq")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def queue_spec(connection) -> AsyncIterator[QueueSpec]:
    """Своя очередь на каждый тест — тесты не мешают друг другу."""
    spec = QueueSpec(name=f"test.{uuid.uuid4().hex[:8]}", routing_keys=("tender.ingested",))
    yield spec

    channel = await connection.channel()
    for name in [spec.name, spec.dead_queue, *(spec.retry_queue(i) for i in range(5))]:
        queue = await channel.get_queue(name, ensure=False)
        await queue.delete(if_unused=False, if_empty=False)
    await channel.close()


def make_event(tender_id: int = 1) -> TenderIngested:
    return TenderIngested(
        tender_id=tender_id, reg_num=f"REG-{tender_id}", is_new=True, attachment_count=3
    )


async def wait_for(predicate, timeout: float) -> bool:
    """Ждёт условия, опрашивая его; возвращает False по таймауту."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.1)
    return predicate()


@pytest.mark.asyncio
async def test_event_round_trip(connection, queue_spec) -> None:
    received: list[TenderIngested] = []

    async def handler(event: TenderIngested) -> None:
        received.append(event)

    consumer = EventConsumer(connection, queue_spec)
    consumer.on(TenderIngested, handler)
    await consumer.run()

    publisher = RabbitPublisher(connection)
    await publisher.setup()
    await publisher.publish(make_event(42))

    assert await wait_for(lambda: received, DELIVERY_WAIT), "событие не доставлено"
    assert received[0].tender_id == 42
    assert received[0].reg_num == "REG-42"
    assert received[0].attachment_count == 3


@pytest.mark.asyncio
async def test_failure_is_retried_then_succeeds(connection, queue_spec) -> None:
    attempts: list[int] = []

    async def flaky(event: TenderIngested) -> None:
        attempts.append(event.tender_id)
        if len(attempts) == 1:
            raise RuntimeError("временный сбой внешнего сервиса")

    consumer = EventConsumer(connection, queue_spec)
    consumer.on(TenderIngested, flaky)
    await consumer.run()

    publisher = RabbitPublisher(connection)
    await publisher.setup()
    await publisher.publish(make_event(7))

    assert await wait_for(lambda: len(attempts) >= 2, FIRST_RETRY_WAIT), (
        f"повторной доставки не было, попыток: {len(attempts)}"
    )
    assert attempts == [7, 7]


@pytest.mark.asyncio
async def test_permanent_error_goes_straight_to_dead_letter(connection, queue_spec) -> None:
    attempts: list[int] = []

    async def broken(event: TenderIngested) -> None:
        attempts.append(event.tender_id)
        raise PermanentError("битые данные, повтор бессмысленен")

    consumer = EventConsumer(connection, queue_spec)
    consumer.on(TenderIngested, broken)
    await consumer.run()

    publisher = RabbitPublisher(connection)
    await publisher.setup()
    await publisher.publish(make_event(13))

    assert await wait_for(lambda: attempts, DELIVERY_WAIT)

    channel = await connection.channel()
    dead = await channel.get_queue(queue_spec.dead_queue)
    assert await wait_for(
        lambda: dead.declaration_result.message_count is not None, DELIVERY_WAIT
    )

    # Повторов быть не должно: PermanentError минует ретрай-лестницу.
    await asyncio.sleep(FIRST_RETRY_WAIT)
    assert attempts == [13]
    await channel.close()


@pytest.mark.asyncio
async def test_duplicate_delivery_is_skipped(connection, queue_spec, session_factory) -> None:
    handled: list[int] = []

    async def handler(event: TenderIngested) -> None:
        handled.append(event.tender_id)

    store = SqlIdempotencyStore(session_factory)
    consumer = EventConsumer(connection, queue_spec, idempotency=store)
    consumer.on(TenderIngested, handler)
    await consumer.run()

    publisher = RabbitPublisher(connection)
    await publisher.setup()

    event = make_event(99)
    await publisher.publish(event)
    assert await wait_for(lambda: handled, DELIVERY_WAIT)

    # То же самое событие (тот же event_id) — брокер гарантирует лишь at-least-once.
    await publisher.publish(event)
    await asyncio.sleep(2)
    assert handled == [99], "дубликат должен быть отброшен по message_id"


@pytest.mark.asyncio
async def test_outbox_relay_publishes_and_marks(connection, session_factory, queue_spec) -> None:
    received: list[TenderIngested] = []

    async def handler(event: TenderIngested) -> None:
        received.append(event)

    consumer = EventConsumer(connection, queue_spec)
    consumer.on(TenderIngested, handler)
    await consumer.run()

    event = make_event(555)
    async with session_factory() as session, session.begin():
        await OutboxPublisher(session).publish(event)

    publisher = RabbitPublisher(connection)
    await publisher.setup()
    relay = OutboxRelay(session_factory, publisher, interval=0.2)
    relay_task = asyncio.create_task(relay.run())

    try:
        assert await wait_for(lambda: received, DELIVERY_WAIT), "relay не опубликовал событие"
        assert received[0].tender_id == 555

        async with session_factory() as session:
            row = await session.scalar(
                select(OutboxMessage).where(OutboxMessage.event_id == str(event.event_id))
            )
            assert row is not None
            assert row.published_at is not None, "запись outbox не помечена как отправленная"
    finally:
        relay.stop()
        await asyncio.wait_for(relay_task, timeout=5)
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(OutboxMessage).where(OutboxMessage.event_id == str(event.event_id))
            )

"""Единое объявление топологии RabbitMQ.

Топологию объявляет каждый сервис при старте — объявления идемпотентны, поэтому
порядок запуска контейнеров не важен.

Схема ретрая — «лестница» очередей с фиксированным TTL на уровень:

    zakupki.events ──(routing key)──> <queue>
                                        │ обработчик упал
                                        ▼
    zakupki.retry ──> <queue>.retry.N (x-message-ttl=TTL[N], потребителей нет)
                                        │ TTL истёк
                                        ▼
    zakupki.retry ──(routing key=<queue>)──> <queue>   (повторная обработка)

Фиксированный TTL на очередь, а не per-message: в per-message варианте сообщение с
большой задержкой в голове очереди блокирует стоящие за ним с меньшей — классический
head-of-line blocking. Исчерпав уровни, сообщение уходит в `<queue>.dead`.
"""

from __future__ import annotations

from dataclasses import dataclass

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue, AbstractRobustConnection

from libs.shared.contracts.events import DLX, EXCHANGE, RETRY_EXCHANGE

# Задержки уровней ретрая: 5с → 30с → 2мин → 10мин → 1ч.
RETRY_DELAYS_MS: tuple[int, ...] = (5_000, 30_000, 120_000, 600_000, 3_600_000)
MAX_RETRY_ATTEMPTS = len(RETRY_DELAYS_MS)


@dataclass(frozen=True)
class QueueSpec:
    """Описание очереди потребителя: имя, подписки и лестница повторов.

    Задержки живут здесь, а не глобальной константой, потому что объявляются
    они per-queue — через `x-message-ttl` каждой retry-очереди. Заодно это
    даёт тестам короткую лестницу: проверять надо, что повтор случился и в
    правильном порядке, а не что RabbitMQ умеет ждать пять секунд.
    """

    name: str
    routing_keys: tuple[str, ...]
    prefetch: int = 8
    retry_delays_ms: tuple[int, ...] = RETRY_DELAYS_MS

    @property
    def max_attempts(self) -> int:
        return len(self.retry_delays_ms)

    def retry_queue(self, attempt: int) -> str:
        return f"{self.name}.retry.{attempt}"

    @property
    def dead_queue(self) -> str:
        return f"{self.name}.dead"


async def declare_exchanges(channel: AbstractChannel) -> AbstractExchange:
    """Объявляет основной topic-exchange, DLX и retry-exchange. Возвращает основной."""
    events = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    await channel.declare_exchange(DLX, aio_pika.ExchangeType.TOPIC, durable=True)
    await channel.declare_exchange(RETRY_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    return events


async def declare_consumer_queues(channel: AbstractChannel, spec: QueueSpec) -> AbstractQueue:
    """Объявляет рабочую очередь, лестницу retry-очередей и dead-letter очередь."""
    events = await declare_exchanges(channel)
    retry_exchange = await channel.get_exchange(RETRY_EXCHANGE)
    dlx = await channel.get_exchange(DLX)

    work = await channel.declare_queue(
        spec.name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            # Отклонённое без ретрая (или протухшее) сообщение уходит в dead-очередь.
            "x-dead-letter-exchange": DLX,
            "x-dead-letter-routing-key": spec.dead_queue,
        },
    )
    for key in spec.routing_keys:
        await work.bind(events, routing_key=key)
    # Возврат из retry-лестницы идёт по routing key, равному имени очереди.
    await work.bind(retry_exchange, routing_key=spec.name)

    for attempt, delay_ms in enumerate(spec.retry_delays_ms):
        retry = await channel.declare_queue(
            spec.retry_queue(attempt),
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-message-ttl": delay_ms,
                # По истечении TTL сообщение возвращается в рабочую очередь.
                "x-dead-letter-exchange": RETRY_EXCHANGE,
                "x-dead-letter-routing-key": spec.name,
            },
        )
        await retry.bind(retry_exchange, routing_key=spec.retry_queue(attempt))

    dead = await channel.declare_queue(
        spec.dead_queue, durable=True, arguments={"x-queue-type": "quorum"}
    )
    await dead.bind(dlx, routing_key=spec.dead_queue)

    await channel.set_qos(prefetch_count=spec.prefetch)
    return work


async def connect(dsn: str) -> AbstractRobustConnection:
    """Robust-соединение: переподключается само при обрыве."""
    return await aio_pika.connect_robust(dsn)

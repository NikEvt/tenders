"""Точка входа docs-worker: потребитель `tender.ingested`."""

from __future__ import annotations

import asyncio
import os

from libs.shared.config import (
    database_settings,
    eis_settings,
    minio_settings,
    rabbit_settings,
)
from libs.shared.contracts.events import TenderIngested
from libs.shared.load_policy import LoadBudget
from libs.shared.logging import configure_logging, get_logger
from libs.shared.messaging.consumer import EventConsumer
from libs.shared.messaging.topology import QueueSpec
from services.docs_worker.bootstrap import build_container

log = get_logger(__name__)

# Сколько извещений воркер берёт из очереди одновременно.
#
# Раньше здесь стояла двойка, и она была не выбором, а страховкой: разбор шёл в
# потоках, а `pypdfium2` не потокобезопасен, и параллельные PDF роняли процесс
# нативным сигналом. Теперь разбор идёт в пуле процессов, делить между потоками
# нечего, и потолок задаётся уровнем нагрузки — вместе с размером пула, чтобы
# очередь не тянула больше, чем есть разборщиков.
#
# Переменная оставлена как аварийный рычаг: если очередь надо придержать,
# не трогая уровень целиком.
def _prefetch_override() -> int | None:
    raw = os.getenv("DOCS_WORKER_PREFETCH", "")
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def _queue(prefetch: int) -> QueueSpec:
    return QueueSpec(
        name="docs-worker.tender-ingested",
        routing_keys=("tender.ingested",),
        prefetch=prefetch,
    )


async def run() -> None:
    configure_logging("docs-worker")

    async with build_container(
        database_settings(), rabbit_settings(), minio_settings(), eis_settings()
    ) as container:
        relay_task = asyncio.create_task(container.relay.run())

        override = _prefetch_override()
        queue = _queue(override or container.controller.budget.docs_prefetch)

        consumer = EventConsumer(container.connection, queue, idempotency=container.idempotency)
        consumer.on(TenderIngested, container.use_case.execute)
        await consumer.run()

        if override is None:
            # Аварийный рычаг важнее уровня: выставленный руками потолок
            # не должен молча возвращаться к вычисленному через пятнадцать секунд.
            container.controller.subscribe(_apply_prefetch(consumer))

        watcher_task = asyncio.create_task(container.load_watcher.run())

        log.info(
            "docs_worker.ready",
            queue=queue.name,
            prefetch=queue.prefetch,
            level=int(container.controller.level),
            extraction_workers=container.extraction.workers,
        )
        try:
            await asyncio.Event().wait()
        finally:
            container.load_watcher.stop()
            container.relay.stop()
            watcher_task.cancel()
            relay_task.cancel()


def _apply_prefetch(consumer: EventConsumer):
    async def apply(budget: LoadBudget) -> None:
        await consumer.set_prefetch(budget.docs_prefetch)

    return apply


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

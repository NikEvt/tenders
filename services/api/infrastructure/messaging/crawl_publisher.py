"""Публикация заявки на выгрузку в RabbitMQ.

Единственное место в шлюзе, знающее про AMQP. Состояние очередей он читает
через management-API по HTTP, а вот команду краулеру иначе как событием не
отдать.

Публикуется напрямую, а не через outbox: заявку породил живой запрос человека,
и если она потеряется между ответом 202 и брокером, человек нажмёт кнопку
снова. Дозаказ идемпотентен — повтор ничего не сломает, а таблица outbox в
шлюзе завелась бы ради одного этого случая.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from aio_pika.abc import AbstractRobustConnection

from libs.shared.contracts.events import CrawlRequested
from libs.shared.logging import get_logger
from libs.shared.messaging.publisher import RabbitPublisher
from services.api.application.ports.crawl import CrawlPublisherPort

log = get_logger(__name__)


class RabbitCrawlPublisher(CrawlPublisherPort):
    def __init__(self, connection: AbstractRobustConnection) -> None:
        self._publisher = RabbitPublisher(connection)
        self._ready = False

    async def setup(self) -> None:
        await self._publisher.setup()
        self._ready = True

    async def request(
        self,
        job_id: uuid.UUID,
        regions: Sequence[str],
        date_from: date,
        date_to: date,
    ) -> None:
        if not self._ready:
            raise RuntimeError("RabbitCrawlPublisher.setup() не вызван")

        await self._publisher.publish(
            CrawlRequested(
                regions=list(regions),
                date_from=date_from,
                date_to=date_to,
                job_id=job_id,
            )
        )
        log.info(
            "crawl.requested",
            job_id=str(job_id),
            regions=list(regions),
            since=date_from.isoformat(),
            until=date_to.isoformat(),
        )

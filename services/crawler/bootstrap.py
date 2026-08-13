"""Composition root краулера.

Единственное место, где конкретные адаптеры встречаются с use-case'ами. Слои
`application` и `domain` про существование SOAP, SQLAlchemy и RabbitMQ не знают (DIP).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aio_pika.abc import AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from libs.shared.config import DatabaseSettings, EisSettings, RabbitSettings
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.load_control import LoadController
from libs.shared.load_store import LoadLevelWatcher, SqlLoadLevelStore
from libs.shared.messaging.outbox import OutboxPublisher, OutboxRelay
from libs.shared.messaging.publisher import RabbitPublisher
from libs.shared.messaging.topology import connect
from services.crawler.application.use_cases.crawl_period import CrawlPeriodUseCase
from services.crawler.application.use_cases.crawl_tenders import (
    CrawlAllUseCase,
    CrawlTendersUseCase,
)
from services.crawler.infrastructure.db.crawl_runner import SessionScopedCrawlRunner
from services.crawler.infrastructure.db.run_log import SqlCrawlRunLog
from services.crawler.infrastructure.db.tender_repository import SqlTenderRepository
from services.crawler.infrastructure.eis.soap_client import ZakupkiSoapClient
from services.crawler.infrastructure.eis.tender_source import EisTenderSource


@dataclass
class CrawlerContainer:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    connection: AbstractRobustConnection
    relay: OutboxRelay
    source: EisTenderSource
    run_log: SqlCrawlRunLog
    regions: list[str]
    document_types: list[str]
    #: Уровень нагрузки: от него зависит, сколько дней тянуть одновременно.
    controller: LoadController
    load_watcher: LoadLevelWatcher

    def crawl_all(self, session: AsyncSession) -> CrawlAllUseCase:
        """Собирает use-case на конкретной сессии — одна выгрузка, одна транзакция."""
        crawl = CrawlTendersUseCase(
            source=self.source,
            repository=SqlTenderRepository(session),
            run_log=self.run_log,
            publisher=OutboxPublisher(session),
        )
        return CrawlAllUseCase(crawl, self.regions, self.document_types)

    def crawl_period(self) -> CrawlPeriodUseCase:
        """Дозаказ произвольного периода — со своей сессией на каждую выгрузку.

        Степень параллельности берётся из текущего уровня нагрузки: на фоновом
        выгрузка идёт по одному дню, на полном — по шесть, больше ЕИС не держит.
        """
        return CrawlPeriodUseCase(
            runner=SessionScopedCrawlRunner(self.session_factory, self.source, self.run_log),
            run_log=self.run_log,
            document_types=self.document_types,
            workers=self.controller.budget.crawl_workers,
        )


@asynccontextmanager
async def build_container(
    db: DatabaseSettings,
    rabbit: RabbitSettings,
    eis: EisSettings,
) -> AsyncIterator[CrawlerContainer]:
    if not eis.token.get_secret_value():
        raise RuntimeError("EIS_TOKEN не задан — выгрузка невозможна")

    engine = create_engine(db.async_dsn)
    session_factory = create_session_factory(engine)
    connection = await connect(rabbit.dsn)

    publisher = RabbitPublisher(connection)
    await publisher.setup()

    controller = LoadController()

    container = CrawlerContainer(
        engine=engine,
        session_factory=session_factory,
        connection=connection,
        relay=OutboxRelay(session_factory, publisher),
        source=EisTenderSource(ZakupkiSoapClient(token=eis.token.get_secret_value())),
        run_log=SqlCrawlRunLog(session_factory),
        regions=eis.region_list,
        document_types=eis.document_type_list,
        controller=controller,
        load_watcher=LoadLevelWatcher(SqlLoadLevelStore(session_factory), controller),
    )

    try:
        yield container
    finally:
        container.load_watcher.stop()
        container.relay.stop()
        await connection.close()
        await engine.dispose()

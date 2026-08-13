"""Выгрузка одного дня в собственной транзакции.

Сценарий периода запускает выгрузки параллельно, а сессия SQLAlchemy
одновременной работы из нескольких задач не переживает: у неё общий буфер
операций, и две задачи в одной сессии рано или поздно получают чужой результат
или `InterfaceError`. Значит, каждая выгрузка обязана открыть свою сессию.

Открыть её должен кто-то, кто про сессии знает, — то есть инфраструктура.
Сценарий периода получает `CrawlRunnerPort` и остаётся без единого упоминания
SQL, сохраняя направление зависимостей (DIP).

Побочная выгода: транзакции разошлись по дням, и сбой на одном регионе больше
не откатывает сохранённое по соседнему.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.base import transaction
from libs.shared.messaging.outbox import OutboxPublisher
from services.crawler.application.ports import (
    CrawlRunLogPort,
    CrawlRunnerPort,
    TenderSourcePort,
)
from services.crawler.application.use_cases.crawl_tenders import CrawlTendersUseCase
from services.crawler.domain.models import CrawlRequest, CrawlResult
from services.crawler.infrastructure.db.tender_repository import SqlTenderRepository


class SessionScopedCrawlRunner(CrawlRunnerPort):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        source: TenderSourcePort,
        run_log: CrawlRunLogPort,
    ) -> None:
        self._session_factory = session_factory
        self._source = source
        self._run_log = run_log

    async def run(self, request: CrawlRequest) -> CrawlResult:
        async with transaction(self._session_factory) as session:
            use_case = CrawlTendersUseCase(
                source=self._source,
                repository=SqlTenderRepository(session),
                run_log=self._run_log,
                # Событие уезжает в outbox той же транзакцией, что и тендеры:
                # либо сохранилось и объявлено, либо ничего.
                publisher=OutboxPublisher(session),
            )
            return await use_case.execute(request)

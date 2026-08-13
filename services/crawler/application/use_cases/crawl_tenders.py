"""Use-case выгрузки тендеров: источник → репозиторий → события."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from libs.shared.contracts.events import TenderIngested
from libs.shared.contracts.ports import EventPublisher
from libs.shared.logging import get_logger
from services.crawler.application.ports import (
    CrawlRunLogPort,
    TenderRepositoryPort,
    TenderSourcePort,
)
from services.crawler.domain.models import CrawlRequest, CrawlResult

log = get_logger(__name__)


class CrawlTendersUseCase:
    """Одна выгрузка: регион × тип документа × дата.

    Controller (GRASP): владеет сценарием, но ничего не знает ни о SOAP, ни о SQL —
    только о портах.
    """

    def __init__(
        self,
        source: TenderSourcePort,
        repository: TenderRepositoryPort,
        run_log: CrawlRunLogPort,
        publisher: EventPublisher,
    ) -> None:
        self._source = source
        self._repository = repository
        self._run_log = run_log
        self._publisher = publisher

    async def execute(self, request: CrawlRequest) -> CrawlResult:
        run_id = await self._run_log.start(request)
        result = CrawlResult(request=request)

        try:
            # Источник синхронный (requests + zipfile) — уводим в тред,
            # чтобы не блокировать событийный цикл.
            tenders = await asyncio.to_thread(self._source.fetch, request)
            result.fetched = len(tenders)

            valid = [t for t in tenders if t.is_valid]
            result.errors = len(tenders) - len(valid)

            if valid:
                saved = await self._repository.upsert_many(valid)
                result.saved = len(saved)
                result.new = sum(1 for s in saved if s.is_new)

                await self._publisher.publish_many(
                    [
                        TenderIngested(
                            tender_id=s.id,
                            reg_num=s.reg_num,
                            is_new=s.is_new,
                            attachment_count=s.attachment_count,
                        )
                        for s in saved
                    ]
                )

            log.info(
                "crawl.finished",
                region=request.region,
                document_type=request.document_type,
                target_date=request.target_date.isoformat(),
                fetched=result.fetched,
                saved=result.saved,
                new=result.new,
            )
        except Exception as exc:
            result.error_message = str(exc)[:1000]
            log.error(
                "crawl.failed",
                region=request.region,
                target_date=request.target_date.isoformat(),
                error=str(exc),
                exc_info=True,
            )
        finally:
            await self._run_log.finish(run_id, result)

        return result


class CrawlAllUseCase:
    """Обход всех сконфигурированных комбинаций регион × тип документа."""

    def __init__(
        self,
        crawl: CrawlTendersUseCase,
        regions: list[str],
        document_types: list[str],
    ) -> None:
        self._crawl = crawl
        self._regions = regions
        self._document_types = document_types

    async def execute(self, target_date: date | None = None) -> list[CrawlResult]:
        # ЕИС отдаёт выгрузку за завершившийся день, поэтому по умолчанию — вчера.
        day = target_date or (date.today() - timedelta(days=1))

        results: list[CrawlResult] = []
        for region in self._regions:
            for document_type in self._document_types:
                results.append(
                    await self._crawl.execute(
                        CrawlRequest(
                            region=region,
                            document_type=document_type,
                            target_date=day,
                        )
                    )
                )
        return results

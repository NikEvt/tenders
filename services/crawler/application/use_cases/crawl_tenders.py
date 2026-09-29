"""Use-case выгрузки тендеров: источник → репозиторий → события.

Здесь одна выгрузка — регион × тип × день. Набором таких выгрузок владеет
`CrawlPeriodUseCase`: он один знает, что уже выгружено, и в каком порядке
обходить. Второй сценарий на ту же ответственность здесь когда-то был
(`CrawlAllUseCase`) — последовательный, в одной транзакции на все регионы, — и
на восьмидесяти пяти субъектах это стало неприемлемо.
"""

from __future__ import annotations

import asyncio

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

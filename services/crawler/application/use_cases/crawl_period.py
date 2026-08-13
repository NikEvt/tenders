"""Выгрузка произвольного периода: догнать то, чего ещё нет.

Штатный краулер тянет вчерашний день по расписанию. Исследованию рынка этого
мало: вопрос «что происходило с января» требует двухсот с лишним дней по
нескольким регионам, и заказывать их по одному вручную бессмысленно.

Два свойства делают такую выгрузку пригодной для работы.

**Она догоняет, а не переделывает.** Сочетания регион × тип × день, уже
выгруженные успешно, пропускаются. Поэтому заявку можно повторять сколько
угодно, а прерванный на середине прогон продолжается с места остановки — это
то же свойство, благодаря которому прогон ХПК/БПК пережил три перезапуска без
единой потери.

**Она идёт параллельно.** Регионы независимы, ЕИС держит шесть одновременных
обращений без отказов. Прежний обход был строго последовательным, и на
223 днях × 4 региона это стоило суток ожидания на ровном месте.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from libs.shared.logging import get_logger
from services.crawler.application.ports import CrawlRunLogPort, CrawlRunnerPort
from services.crawler.domain.models import CrawlRequest, CrawlResult

log = get_logger(__name__)


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


@dataclass(slots=True)
class PeriodOutcome:
    """Чем кончился дозаказ периода.

    `skipped` — не потеря, а показатель того, что покрытие уже было: без него
    «выгружено 0 дней» невозможно отличить от «всё уже на месте».
    """

    requested: int = 0
    skipped: int = 0
    fetched: int = 0
    saved: int = 0
    failed: int = 0
    results: list[CrawlResult] = field(default_factory=list)


class CrawlPeriodUseCase:
    """Догоняет период, пропуская уже выгруженное.

    Controller (GRASP): владеет порядком и параллельностью, но не знает ни про
    SOAP, ни про SQL — только про порты.
    """

    def __init__(
        self,
        runner: CrawlRunnerPort,
        run_log: CrawlRunLogPort,
        document_types: Sequence[str],
        workers: int = 1,
    ) -> None:
        self._runner = runner
        self._run_log = run_log
        self._document_types = list(document_types)
        self._workers = max(int(workers), 1)

    async def execute(
        self,
        regions: Sequence[str],
        date_from: date,
        date_to: date,
        document_types: Sequence[str] | None = None,
    ) -> PeriodOutcome:
        if date_to < date_from:
            date_from, date_to = date_to, date_from

        types = list(document_types) if document_types else self._document_types
        done = await self._run_log.completed(date_from, date_to)

        outcome = PeriodOutcome()
        pending: list[CrawlRequest] = []
        for day in days_between(date_from, date_to):
            for region in regions:
                for document_type in types:
                    if (region, document_type, day) in done:
                        outcome.skipped += 1
                        continue
                    pending.append(
                        CrawlRequest(
                            region=region, document_type=document_type, target_date=day
                        )
                    )

        outcome.requested = len(pending)
        if not pending:
            log.info(
                "crawl_period.nothing_to_do",
                regions=list(regions),
                since=date_from.isoformat(),
                until=date_to.isoformat(),
                skipped=outcome.skipped,
            )
            return outcome

        log.info(
            "crawl_period.started",
            regions=list(regions),
            since=date_from.isoformat(),
            until=date_to.isoformat(),
            requests=outcome.requested,
            skipped=outcome.skipped,
            workers=self._workers,
        )

        # Потолок одновременных обращений к ЕИС. Больше шести он не выдерживает,
        # а бан прилетает на весь прогон, а не на одну выгрузку.
        limit = asyncio.Semaphore(self._workers)

        async def run_one(request: CrawlRequest) -> CrawlResult:
            async with limit:
                return await self._runner.run(request)

        results = await asyncio.gather(
            *(run_one(request) for request in pending), return_exceptions=True
        )

        for request, result in zip(pending, results, strict=True):
            if isinstance(result, BaseException):
                # Выгрузка одного дня упала так, что даже не вернула результат.
                # Соседние дни к этому отношения не имеют и теряться не должны.
                outcome.failed += 1
                log.error(
                    "crawl_period.request_crashed",
                    region=request.region,
                    target_date=request.target_date.isoformat(),
                    error=str(result),
                )
                continue

            outcome.results.append(result)
            outcome.fetched += result.fetched
            outcome.saved += result.saved
            outcome.failed += result.status == "failed"

        log.info(
            "crawl_period.finished",
            requests=outcome.requested,
            fetched=outcome.fetched,
            saved=outcome.saved,
            failed=outcome.failed,
        )
        return outcome

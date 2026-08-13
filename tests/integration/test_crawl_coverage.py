"""Карта покрытия выгрузки — журнал запусков, а не отдельная таблица.

Дозаказ периода сверяется с ней, чтобы тянуть только недостающее. Ошибка здесь
стоит либо повторной выкачки сотен дней, либо незаметной дыры в покрытии.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import delete

from libs.shared.db.schema import CrawlerRun
from services.crawler.domain.models import CrawlRequest, CrawlResult
from services.crawler.infrastructure.db.run_log import SqlCrawlRunLog

TYPE = "epNotificationEF2020"
JANUARY = date(2026, 1, 1)


@pytest.fixture
async def run_log(session_factory):
    log = SqlCrawlRunLog(session_factory)
    yield log
    async with session_factory() as session, session.begin():
        await session.execute(delete(CrawlerRun).where(CrawlerRun.source == "eis-soap"))


async def record(log: SqlCrawlRunLog, region: str, day: date, *, failed: bool = False) -> None:
    request = CrawlRequest(region=region, document_type=TYPE, target_date=day)
    run_id = await log.start(request)
    result = CrawlResult(request=request)
    if failed:
        result.error_message = "ЕИС не ответил"
    else:
        result.fetched = 5
        result.saved = 5
    await log.finish(run_id, result)


@pytest.mark.asyncio
async def test_successful_days_are_reported_as_covered(run_log) -> None:
    await record(run_log, "77", JANUARY)
    await record(run_log, "50", JANUARY)

    covered = await run_log.completed(JANUARY, JANUARY)

    assert covered == {("77", TYPE, JANUARY), ("50", TYPE, JANUARY)}


@pytest.mark.asyncio
async def test_failed_day_is_not_covered(run_log) -> None:
    """Провалившийся день обязан быть повторён.

    Иначе дыра в покрытии станет постоянной, а заметить её будет не по чему:
    дозаказ просто перестанет предлагать этот день.
    """
    await record(run_log, "77", JANUARY, failed=True)

    assert await run_log.completed(JANUARY, JANUARY) == set()


@pytest.mark.asyncio
async def test_repeated_run_of_the_same_day_collapses(run_log) -> None:
    """День, выгруженный дважды, остаётся одной клеткой покрытия."""
    await record(run_log, "77", JANUARY)
    await record(run_log, "77", JANUARY)

    assert await run_log.completed(JANUARY, JANUARY) == {("77", TYPE, JANUARY)}


@pytest.mark.asyncio
async def test_period_boundaries_are_inclusive(run_log) -> None:
    await record(run_log, "77", date(2026, 1, 1))
    await record(run_log, "77", date(2026, 1, 5))
    await record(run_log, "77", date(2026, 1, 9))

    covered = await run_log.completed(date(2026, 1, 1), date(2026, 1, 5))

    assert {day for _, _, day in covered} == {date(2026, 1, 1), date(2026, 1, 5)}


@pytest.mark.asyncio
async def test_days_outside_the_period_are_not_returned(run_log) -> None:
    await record(run_log, "77", date(2025, 12, 31))

    assert await run_log.completed(JANUARY, date(2026, 1, 31)) == set()

"""Карта покрытия выгрузки — журнал запусков, а не отдельная таблица.

Дозаказ периода сверяется с ней, чтобы тянуть только недостающее. Ошибка здесь
стоит либо повторной выкачки сотен дней, либо незаметной дыры в покрытии.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from libs.shared.db.schema import CrawlerRun
from services.crawler.domain.models import CrawlRequest, CrawlResult
from services.crawler.infrastructure.db.run_log import SqlCrawlRunLog

#: Тип документа, которого в настоящей выгрузке не бывает. Тесты живут в общей
#: базе рядом с реальным журналом, и утверждать про всю таблицу нельзя: регион
#: «77» за вчера там появляется сам собой.
TYPE = "TEST-epNotification"
JANUARY = date(2026, 1, 1)


@pytest.fixture
async def run_log(session_factory):
    """Журнал с уборкой ровно за собой.

    Раньше фикстура сносила всё, у чего `source = 'eis-soap'`, — то есть весь
    настоящий журнал покрытия. Прогон тестов молча стирал карту выгрузок, и
    краулер потом качал заново то, что уже было. Теперь удаляются только те
    строки, которые тест и создал.
    """
    log = SqlCrawlRunLog(session_factory)
    log.created_run_ids = []  # type: ignore[attr-defined]
    yield log

    if log.created_run_ids:  # type: ignore[attr-defined]
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(CrawlerRun).where(CrawlerRun.id.in_(log.created_run_ids))  # type: ignore[attr-defined]
            )


async def _ours(log: SqlCrawlRunLog, since: date, until: date) -> set[tuple[str, str, date]]:
    """Покрытие только по строкам этого теста — соседей в общей базе не трогаем."""
    return {row for row in await log.completed(since, until) if row[1] == TYPE}


async def record(log: SqlCrawlRunLog, region: str, day: date, *, failed: bool = False) -> None:
    request = CrawlRequest(region=region, document_type=TYPE, target_date=day)
    run_id = await log.start(request)
    log.created_run_ids.append(run_id)  # type: ignore[attr-defined]
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

    covered = await _ours(run_log, JANUARY, JANUARY)

    assert covered == {("77", TYPE, JANUARY), ("50", TYPE, JANUARY)}


@pytest.mark.asyncio
async def test_failed_day_is_not_covered(run_log) -> None:
    """Провалившийся день обязан быть повторён.

    Иначе дыра в покрытии станет постоянной, а заметить её будет не по чему:
    дозаказ просто перестанет предлагать этот день.
    """
    await record(run_log, "77", JANUARY, failed=True)

    assert await _ours(run_log, JANUARY, JANUARY) == set()


@pytest.mark.asyncio
async def test_repeated_run_of_the_same_day_collapses(run_log) -> None:
    """День, выгруженный дважды, остаётся одной клеткой покрытия."""
    await record(run_log, "77", JANUARY)
    await record(run_log, "77", JANUARY)

    assert await _ours(run_log, JANUARY, JANUARY) == {("77", TYPE, JANUARY)}


@pytest.mark.asyncio
async def test_period_boundaries_are_inclusive(run_log) -> None:
    await record(run_log, "77", date(2026, 1, 1))
    await record(run_log, "77", date(2026, 1, 5))
    await record(run_log, "77", date(2026, 1, 9))

    covered = await _ours(run_log, date(2026, 1, 1), date(2026, 1, 5))

    assert {day for _, _, day in covered} == {date(2026, 1, 1), date(2026, 1, 5)}


@pytest.mark.asyncio
async def test_days_outside_the_period_are_not_returned(run_log) -> None:
    await record(run_log, "77", date(2025, 12, 31))

    assert await _ours(run_log, JANUARY, date(2026, 1, 31)) == set()


@pytest.mark.asyncio
async def test_today_is_never_covered(run_log) -> None:
    """Суточный архив дописывается до полуночи — полдня это не день.

    Успешная выгрузка сегодняшнего дня раньше закрывала его навсегда, и остаток
    суток не забирался уже никогда. На этом же свойстве стоит ручное
    обновление: перекачать сегодня можно всегда, без флага «всё равно».
    """
    today = date.today()
    await record(run_log, "77", today)

    assert await _ours(run_log, today, today) == set()


@pytest.mark.asyncio
async def test_yesterday_is_covered_by_a_pass_made_today(run_log) -> None:
    """А вчерашний день дневной проход закрывает — иначе перекачивал бы вечно."""
    yesterday = date.today() - timedelta(days=1)
    await record(run_log, "77", yesterday)

    assert await _ours(run_log, yesterday, yesterday) == {("77", TYPE, yesterday)}


@pytest.mark.asyncio
async def test_a_window_spanning_today_keeps_only_the_closed_days(run_log) -> None:
    """Ровно то, что делает кнопка обновления: вчера пропустить, сегодня взять."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    await record(run_log, "77", yesterday)
    await record(run_log, "77", today)

    assert await _ours(run_log, yesterday, today) == {("77", TYPE, yesterday)}

"""Дозаказ периода: догнать недостающее, не переделывая сделанное."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from services.crawler.application.use_cases.crawl_period import (
    CrawlPeriodUseCase,
    days_between,
)
from services.crawler.domain.models import CrawlRequest, CrawlResult

JANUARY = date(2026, 1, 1)
TYPE = "epNotificationEF2020"


class FakeRunLog:
    def __init__(self, done: set[tuple[str, str, date]] | None = None) -> None:
        self.done = done or set()

    async def completed(self, since: date, until: date) -> set[tuple[str, str, date]]:
        return {item for item in self.done if since <= item[2] <= until}

    async def start(self, request: CrawlRequest) -> int:
        return 1

    async def finish(self, run_id: int, result: CrawlResult) -> None:
        return None


class FakeRunner:
    """Считает выгрузки и, если попросить, замеряет реальную одновременность."""

    def __init__(self, fetched: int = 10, fail_on: set[str] | None = None) -> None:
        self.requests: list[CrawlRequest] = []
        self.fetched = fetched
        self.fail_on = fail_on or set()
        self.running = 0
        self.peak = 0
        self.delay = 0.0

    async def run(self, request: CrawlRequest) -> CrawlResult:
        self.requests.append(request)
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if request.region in self.fail_on:
                raise RuntimeError("ЕИС не ответил")
            result = CrawlResult(request=request)
            result.fetched = self.fetched
            result.saved = self.fetched
            return result
        finally:
            self.running -= 1


def use_case(runner, run_log, workers: int = 1) -> CrawlPeriodUseCase:
    return CrawlPeriodUseCase(
        runner=runner, run_log=run_log, document_types=[TYPE], workers=workers
    )


class TestDaysBetween:
    def test_inclusive_on_both_ends(self) -> None:
        assert days_between(JANUARY, date(2026, 1, 3)) == [
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 3),
        ]

    def test_single_day(self) -> None:
        assert days_between(JANUARY, JANUARY) == [JANUARY]


class TestCoverage:
    async def test_requests_every_missing_combination(self) -> None:
        runner = FakeRunner()
        outcome = await use_case(runner, FakeRunLog()).execute(
            regions=["77", "50"], date_from=JANUARY, date_to=date(2026, 1, 3)
        )

        # 3 дня × 2 региона × 1 тип
        assert outcome.requested == 6
        assert len(runner.requests) == 6
        assert outcome.fetched == 60

    async def test_already_crawled_days_are_skipped(self) -> None:
        """Заявку можно повторять: покрытие — это журнал запусков."""
        done = {("77", TYPE, JANUARY), ("77", TYPE, date(2026, 1, 2))}
        runner = FakeRunner()

        outcome = await use_case(runner, FakeRunLog(done)).execute(
            regions=["77"], date_from=JANUARY, date_to=date(2026, 1, 3)
        )

        assert outcome.skipped == 2
        assert outcome.requested == 1
        assert [r.target_date for r in runner.requests] == [date(2026, 1, 3)]

    async def test_fully_covered_period_does_nothing(self) -> None:
        done = {("77", TYPE, JANUARY)}
        runner = FakeRunner()

        outcome = await use_case(runner, FakeRunLog(done)).execute(
            regions=["77"], date_from=JANUARY, date_to=JANUARY
        )

        assert outcome.requested == 0
        assert runner.requests == []
        # Ноль выгрузок и ноль покрытия — разные вещи, и их видно по отдельности.
        assert outcome.skipped == 1

    async def test_interrupted_run_resumes(self) -> None:
        """Прерванный прогон продолжается с места остановки, а не с начала."""
        run_log = FakeRunLog()
        first = FakeRunner()
        await use_case(first, run_log).execute(
            regions=["77"], date_from=JANUARY, date_to=date(2026, 1, 4)
        )

        # Первые два дня успели записаться в журнал, остальные — нет.
        run_log.done = {("77", TYPE, JANUARY), ("77", TYPE, date(2026, 1, 2))}

        second = FakeRunner()
        outcome = await use_case(second, run_log).execute(
            regions=["77"], date_from=JANUARY, date_to=date(2026, 1, 4)
        )

        assert [r.target_date for r in second.requests] == [
            date(2026, 1, 3),
            date(2026, 1, 4),
        ]
        assert outcome.skipped == 2


class TestParallelism:
    async def test_never_exceeds_the_worker_limit(self) -> None:
        """Больше шести одновременных ЕИС не держит, а бан прилетает на прогон."""
        runner = FakeRunner()
        runner.delay = 0.01

        await use_case(runner, FakeRunLog(), workers=3).execute(
            regions=["77", "50", "78", "47"], date_from=JANUARY, date_to=date(2026, 1, 3)
        )

        assert runner.peak <= 3
        assert len(runner.requests) == 12

    async def test_single_worker_is_sequential(self) -> None:
        runner = FakeRunner()
        runner.delay = 0.005

        await use_case(runner, FakeRunLog(), workers=1).execute(
            regions=["77", "50"], date_from=JANUARY, date_to=JANUARY
        )

        assert runner.peak == 1

    async def test_parallel_is_actually_faster(self) -> None:
        runner = FakeRunner()
        runner.delay = 0.02

        started = asyncio.get_running_loop().time()
        await use_case(runner, FakeRunLog(), workers=6).execute(
            regions=["77", "50", "78", "47", "23", "66"],
            date_from=JANUARY,
            date_to=JANUARY,
        )
        elapsed = asyncio.get_running_loop().time() - started

        # Шесть выгрузок по 20 мс: последовательно это 120 мс, параллельно ~20.
        assert elapsed < 0.1


class TestFailures:
    async def test_one_failed_region_does_not_lose_the_others(self) -> None:
        runner = FakeRunner(fail_on={"50"})

        outcome = await use_case(runner, FakeRunLog(), workers=4).execute(
            regions=["77", "50"], date_from=JANUARY, date_to=date(2026, 1, 2)
        )

        assert outcome.failed == 2
        # Регион 77 за оба дня всё равно выгружен.
        assert outcome.saved == 20

    async def test_reversed_period_is_understood(self) -> None:
        """`--since` и `--until` перепутаны местами — это опечатка, а не пустой период."""
        runner = FakeRunner()
        outcome = await use_case(runner, FakeRunLog()).execute(
            regions=["77"], date_from=date(2026, 1, 3), date_to=JANUARY
        )
        assert outcome.requested == 3


class TestDocumentTypes:
    async def test_explicit_types_override_the_defaults(self) -> None:
        runner = FakeRunner()
        await use_case(runner, FakeRunLog()).execute(
            regions=["77"],
            date_from=JANUARY,
            date_to=JANUARY,
            document_types=["epNotificationEOK2020", "epNotificationZK2020"],
        )
        assert {r.document_type for r in runner.requests} == {
            "epNotificationEOK2020",
            "epNotificationZK2020",
        }

    async def test_defaults_are_used_when_not_given(self) -> None:
        runner = FakeRunner()
        await use_case(runner, FakeRunLog()).execute(
            regions=["77"], date_from=JANUARY, date_to=JANUARY
        )
        assert {r.document_type for r in runner.requests} == {TYPE}


@pytest.mark.parametrize("workers", [0, -1])
async def test_worker_count_never_drops_below_one(workers: int) -> None:
    runner = FakeRunner()
    await use_case(runner, FakeRunLog(), workers=workers).execute(
        regions=["77"], date_from=JANUARY, date_to=JANUARY
    )
    assert len(runner.requests) == 1

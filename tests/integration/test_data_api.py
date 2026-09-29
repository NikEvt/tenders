"""Вкладка «Данные»: состав корпуса и ход его обогащения.

Главное, что здесь проверяется, — **знаменатели**. Разрез без хвоста и итога
читается как весь корпус, а день без выгрузки, слитый с днём без закупок,
превращает дыру в наших данных в утверждение о рынке.

Требует Postgres.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete

from libs.shared.db.schema import CrawlerRun, Tender
from services.api.application.errors import InvalidRequest
from services.api.application.use_cases.read_corpus import CorpusOverviewUseCase
from services.api.infrastructure.db.corpus_repository import SqlCorpusRepository

PREFIX = "TEST-DATA-"

#: Окно намеренно в прошлом, до первой выгрузки проекта: разрезы считаются по
#: всей таблице, и на живой базе разработчика соседние строки иначе попадали бы
#: в те же счётчики. Своей схемы на тест здесь нет — интеграционные тесты
#: проекта работают с общей базой.
TODAY = date(2019, 6, 15)


@pytest.fixture
async def corpus(session_factory):
    """Корпус из шести закупок за три дня и журнал выгрузок с дырой.

    14 августа выгрузки не было вовсе — это и есть случай, который обязан
    отличаться от «в этот день ничего не публиковали».
    """
    rows = [
        ("MSK-1", "77", "26.20.11", "Компьютеры", TODAY),
        ("MSK-2", "77", "26.20.11", "Компьютеры", TODAY),
        ("MSK-3", "77", "20.11.11", "Газы", TODAY - timedelta(days=2)),
        ("SPB-1", "78", "20.11.11", "Газы", TODAY - timedelta(days=2)),
        ("SPB-2", "78", None, None, TODAY - timedelta(days=2)),
        ("OLD-1", "23", "20.11.11", "Газы", TODAY - timedelta(days=200)),
    ]
    async with session_factory() as session, session.begin():
        for reg, region, okpd, okpd_name, published in rows:
            session.add(
                Tender(
                    reg_num=f"{PREFIX}{reg}",
                    name=f"Закупка {reg}",
                    region_code=region,
                    okpd2_code=okpd,
                    okpd2_name=okpd_name,
                    publish_date=datetime.combine(published, datetime.min.time(), tzinfo=UTC),
                )
            )
        session.add_all(
            [
                CrawlerRun(
                    source=f"{PREFIX}eis",
                    region="77",
                    document_type="notice",
                    target_date=TODAY,
                    status="success",
                    fetched=2,
                    saved=2,
                ),
                CrawlerRun(
                    source=f"{PREFIX}eis",
                    region="78",
                    document_type="notice",
                    target_date=TODAY,
                    status="failed",
                    error_message="организация заблокирована",
                ),
                CrawlerRun(
                    source=f"{PREFIX}eis",
                    region="77",
                    document_type="notice",
                    target_date=TODAY - timedelta(days=2),
                    status="success",
                    fetched=3,
                    saved=3,
                ),
            ]
        )

    yield SqlCorpusRepository(session_factory)

    async with session_factory() as session, session.begin():
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))
        await session.execute(delete(CrawlerRun).where(CrawlerRun.source == f"{PREFIX}eis"))


async def _overview(corpus, days: int = 3, limit: int = 12):
    return await corpus.overview(TODAY - timedelta(days=days - 1), TODAY, limit)


@pytest.mark.asyncio
async def test_days_are_a_continuous_row(corpus) -> None:
    """Ряд без пропусков: каждый день периода на месте, даже пустой."""
    view = await _overview(corpus)

    assert [bucket.day for bucket in view.by_day] == [
        TODAY - timedelta(days=2),
        TODAY - timedelta(days=1),
        TODAY,
    ]


@pytest.mark.asyncio
async def test_a_day_without_a_crawl_differs_from_a_day_without_tenders(corpus) -> None:
    """Дыра в покрытии — не факт о рынке.

    14 августа выгрузки не было: ноль закупок в этот день ничего не говорит о
    том, публиковали ли их. Слить это с настоящим нулём значило бы выдать
    отсутствие данных за отсутствие закупок.
    """
    by_day = {bucket.day: bucket for bucket in (await _overview(corpus)).by_day}

    gap = by_day[TODAY - timedelta(days=1)]
    assert (gap.count, gap.crawled) == (0, False)

    real = by_day[TODAY]
    assert real.count == 2
    assert real.crawled is True


@pytest.mark.asyncio
async def test_the_top_plus_the_tail_equals_the_total(corpus) -> None:
    """Сумма показанного, хвоста и «без признака» равна итогу.

    Без этого правила двенадцать столбиков читаются как весь корпус.
    """
    view = await _overview(corpus, limit=1)

    for distribution in (view.by_region, view.by_okpd2):
        shown = sum(item.count for item in distribution.top)
        assert shown + distribution.others + distribution.unknown == distribution.total


@pytest.mark.asyncio
async def test_tenders_without_okpd2_are_counted_as_unknown(corpus) -> None:
    """Закупка без ОКПД2 не исчезает — она попадает в «без признака»."""
    view = await _overview(corpus)

    assert view.by_okpd2.unknown == 1


@pytest.mark.asyncio
async def test_the_window_bounds_every_slice(corpus) -> None:
    """Все разрезы считаются за один период — тот же, что у гистограммы.

    Закупка двухсотдневной давности в трёхдневное окно не попадает ни в один
    разрез, иначе «топ регионов» описывал бы другое множество, чем столбики.
    """
    view = await _overview(corpus)

    assert view.total == 5
    assert view.by_region.total == 5
    assert sum(bucket.count for bucket in view.by_day) == 5
    # Но корпус целиком виден отдельным числом — иначе непонятно, какую его
    # часть вообще показывает экран.
    assert view.total_all_time >= 6


@pytest.mark.asyncio
async def test_an_empty_period_reports_zeros_with_denominators(corpus) -> None:
    """Пустой период — это нули и знаменатели, а не отсутствие ответа."""
    empty = await corpus.overview(TODAY - timedelta(days=100), TODAY - timedelta(days=98), 12)

    assert empty.total == 0
    assert len(empty.by_day) == 3
    assert empty.by_region.top == []
    assert empty.by_region.total == 0


@pytest.mark.asyncio
async def test_today_counts_runs_by_outcome(corpus) -> None:
    view = await corpus.today(TODAY)

    assert (view.runs_succeeded, view.runs_failed) == (1, 1)
    assert view.saved == 2
    assert view.published_today == 2


@pytest.mark.asyncio
async def test_embeddings_report_both_denominators(corpus) -> None:
    """«Векторизовано столько-то» имеет смысл только рядом с «из скольки»."""
    view = await corpus.embeddings()

    assert view.chunks_embedded <= view.chunks_total
    assert view.tenders_embedded <= view.tenders_total


class TestWindowValidation:
    """Недопустимое окно — ошибка запроса, а не молчаливое приведение."""

    async def test_zero_days_is_rejected(self) -> None:
        with pytest.raises(InvalidRequest):
            await CorpusOverviewUseCase(_NullCorpus()).execute(days=0)

    async def test_a_period_beyond_the_ceiling_is_rejected(self) -> None:
        with pytest.raises(InvalidRequest):
            await CorpusOverviewUseCase(_NullCorpus()).execute(days=5000)

    async def test_an_empty_top_is_rejected(self) -> None:
        with pytest.raises(InvalidRequest):
            await CorpusOverviewUseCase(_NullCorpus()).execute(limit=0)


class _NullCorpus:
    async def overview(self, since, until, limit):  # pragma: no cover - до него не доходит
        raise AssertionError("проверка окна обязана отсечь запрос раньше")

    async def embeddings(self): ...

    async def today(self, day): ...

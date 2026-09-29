"""Сводка отбирает закупки по фильтрам, включённым в неё.

До этого файла тумблер «включать в сводку» не был подключён ни к чему: сводка
молча брала весь день, и пользователь, настроивший два фильтра, получал ленту
из пяти тысяч чужих закупок.

Отбор идёт теми же предикатами, что и каталог
(`libs/shared/db/tender_criteria.py`). Здесь проверяется, что он действительно
идёт, а не что предикаты правильные, — за это отвечает `test_matching_consistency`.

Требует Postgres.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete

from libs.shared.db.schema import ResearchVerdict, SavedFilter, Tender
from services.llm_service.infrastructure.db.repositories import SqlDigestRepository

PREFIX = "TEST-DIGEST-"
DAY = date(2019, 7, 10)
VERSION = "test-digest-v1"


def _spec(version: str = VERSION) -> dict:
    return {
        "name": "газовые смеси",
        "terms": [],
        "context_rules": [],
        "card_pattern": None,
        "okpd2_prefixes": [],
        "structural": {
            "regions": [],
            "customer_inns": [],
            "price_min": None,
            "price_max": None,
            "only_active": False,
        },
        "version": version,
    }


@pytest.fixture
async def corpus(session_factory):
    """Три закупки за день: две прошли фильтр, одна — посторонняя."""
    async with session_factory() as session, session.begin():
        tenders = [
            Tender(
                reg_num=f"{PREFIX}{suffix}",
                name=name,
                price=Decimal("100000"),
                customer_name=customer,
                customer_inn=inn,
                okpd2_code="20.11.11",
                okpd2_name="Газы промышленные",
                publish_date=datetime.combine(DAY, datetime.min.time(), tzinfo=UTC),
            )
            for suffix, name, customer, inn in [
                ("HIT-1", "Поставка кислорода", "ГКУ Больница", "7700000101"),
                ("HIT-2", "Поставка азота", "ГКУ Поликлиника", "7700000102"),
                ("MISS", "Поставка мебели", "ГКУ Школа", "7700000103"),
            ]
        ]
        session.add_all(tenders)
        await session.flush()

        session.add(
            SavedFilter(
                name=f"{PREFIX}газовые смеси",
                nl_query="газовые смеси",
                spec=_spec(),
                is_active=True,
                in_digest=True,
            )
        )
        # Вердикты — по версии критерия, а не по фильтру: так устроено правило
        # отбора, и здесь оно только используется.
        session.add_all(
            [
                ResearchVerdict(
                    tender_id=tender.id,
                    criteria_version=VERSION,
                    prompt_version="p1",
                    confidence="confirmed",
                    reason="подходит",
                    decided_by="rules",
                    model="test",
                )
                for tender in tenders[:2]
            ]
        )

    yield SqlDigestRepository(session_factory)

    async with session_factory() as session, session.begin():
        await session.execute(
            delete(SavedFilter).where(SavedFilter.name.like(f"{PREFIX}%"))
        )
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))


@pytest.fixture
async def only_test_filters(session_factory):
    """Отключает чужие фильтры на время теста и возвращает их обратно.

    Отбор читает всю таблицу `saved_filters`, а на машине разработчика там
    лежат настоящие фильтры пользователя. Тесты, которым нужно состояние «в
    сводку не включён ни один фильтр», обязаны его создать — и восстановить,
    что бы ни случилось. Трогается только булев тумблер.
    """
    from sqlalchemy import select, update

    async with session_factory() as session, session.begin():
        restore = (
            await session.scalars(
                select(SavedFilter.id).where(
                    SavedFilter.in_digest.is_(True),
                    SavedFilter.name.not_like(f"{PREFIX}%"),
                )
            )
        ).all()
        if restore:
            await session.execute(
                update(SavedFilter)
                .where(SavedFilter.id.in_(restore))
                .values(in_digest=False)
            )
    try:
        yield
    finally:
        async with session_factory() as session, session.begin():
            if restore:
                await session.execute(
                    update(SavedFilter)
                    .where(SavedFilter.id.in_(restore))
                    .values(in_digest=True)
                )


@pytest.mark.asyncio
async def test_the_digest_takes_only_what_passed_the_filter(session_factory, corpus) -> None:
    """Главное: посторонняя закупка в сводку не попадает."""
    data = await corpus.collect(DAY)

    assert data.total == 2
    names = {candidate.name for candidate in data.top_by_price}
    assert "Поставка мебели" not in names


@pytest.mark.asyncio
async def test_the_digest_names_its_scope(session_factory, corpus) -> None:
    """«Две закупки» без имени фильтра — число без основания."""
    data = await corpus.collect(DAY)

    assert data.scope.filtered
    assert f"{PREFIX}газовые смеси" in data.scope.filters


@pytest.mark.asyncio
async def test_without_filters_the_digest_covers_the_whole_day(
    session_factory, corpus, only_test_filters
) -> None:
    """Фильтров нет — сводка честно описывает весь день, и говорит об этом."""
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(SavedFilter).where(SavedFilter.name.like(f"{PREFIX}%"))
        )

    data = await corpus.collect(DAY)

    assert data.total == 3
    assert not data.scope.filtered
    assert data.scope.filters == []


@pytest.mark.asyncio
async def test_a_filter_excluded_from_the_digest_does_not_narrow_it(
    session_factory, corpus, only_test_filters
) -> None:
    """Тумблер работает в обе стороны — иначе он снова ничего не значит."""
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(SavedFilter).where(SavedFilter.name.like(f"{PREFIX}%"))
        )
        session.add(
            SavedFilter(
                name=f"{PREFIX}вне сводки",
                nl_query="газовые смеси",
                spec=_spec(),
                is_active=True,
                in_digest=False,
            )
        )

    data = await corpus.collect(DAY)

    assert data.total == 3
    assert not data.scope.filtered


@pytest.mark.asyncio
async def test_a_filter_that_never_ran_is_named(
    session_factory, corpus, only_test_filters
) -> None:
    """Фильтр без вердиктов не приносит закупок.

    Молчать об этом нельзя: пустая сводка выглядела бы выводом о рынке, хотя
    это несделанная работа.
    """
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(SavedFilter).where(SavedFilter.name.like(f"{PREFIX}%"))
        )
        session.add(
            SavedFilter(
                name=f"{PREFIX}не запускался",
                nl_query="что-то",
                spec=_spec(version="never-run-v1"),
                is_active=True,
                in_digest=True,
            )
        )

    data = await corpus.collect(DAY)

    assert data.total == 0
    assert data.scope.unrun_filters == [f"{PREFIX}не запускался"]


@pytest.mark.asyncio
async def test_built_at_tells_a_draft_from_a_final(session_factory, corpus) -> None:
    """`built_at` вместо `exists`: важно не наличие, а когда собрали."""
    assert await corpus.built_at(DAY) is None

    await corpus.save(DAY, "## Главное", {"total": 2}, 2, "test", "p1")

    built = await corpus.built_at(DAY)
    assert built is not None and built.date() > DAY

    async with session_factory() as session, session.begin():
        from libs.shared.db.schema import DailyDigest

        await session.execute(delete(DailyDigest).where(DailyDigest.digest_date == DAY))

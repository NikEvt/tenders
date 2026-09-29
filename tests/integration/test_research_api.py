"""Чтение исследований шлюзом: прогоны, закупки с цитатами, рынок."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete

from libs.shared.db.schema import (
    ResearchHit,
    ResearchRun,
    ResearchVerdict,
    Tender,
)
from services.api.infrastructure.db.research_repository import SqlResearchRepository

PREFIX = "TEST-RESEARCH-API-"
VERSION = "тест-v1"


@pytest.fixture
async def run(session_factory):
    """Прогон с тремя закупками: подтверждённая, отклонённая и спорная."""
    async with session_factory() as session, session.begin():
        run_id = await session.scalar(
            ResearchRun.__table__.insert()
            .values(
                name="ХПК/БПК",
                criteria_version=VERSION,
                criteria={"name": "ХПК/БПК", "terms": []},
                regions=["77", "50"],
                status="done",
                started_at=datetime.now(UTC),
                tenders_total=1000,
                tenders_candidate=120,
                documents_scanned=300,
                documents_pending=640,
                hits_found=9,
                tenders_confirmed=1,
                tenders_rejected=1,
                tenders_disputed=1,
            )
            .returning(ResearchRun.id)
        )

        ids = {}
        rows = [
            ("CONFIRMED", "Анализ сточных вод", Decimal("5000000"), "50", "confirmed"),
            ("REJECTED", "Ремонт кровли БПК", Decimal("900000"), "77", "rejected"),
            ("DISPUTED", "Поставка стандартов", Decimal("300000"), "77", None),
        ]
        for suffix, name, price, region, confidence in rows:
            tender_id = await session.scalar(
                Tender.__table__.insert()
                .values(
                    reg_num=f"{PREFIX}{suffix}",
                    name=name,
                    price=price,
                    region_code=region,
                    customer_name="Водоканал",
                    customer_inn="5000000001",
                    okpd2_code="71.20.11",
                )
                .returning(Tender.id)
            )
            ids[suffix] = tender_id

            await session.execute(
                ResearchHit.__table__.insert().values(
                    run_id=run_id,
                    tender_id=tender_id,
                    term="БПК",
                    role="primary",
                    quote="норматив по показателю БПК5 в сточной воде",
                    match_start=23,
                    match_end=27,
                    file_name="ТЗ.docx",
                    page=4,
                )
            )
            if confidence:
                await session.execute(
                    ResearchVerdict.__table__.insert().values(
                        tender_id=tender_id,
                        criteria_version=VERSION,
                        prompt_version="hits-judge-v1",
                        confidence=confidence,
                        reason="химия воды" if confidence == "confirmed" else "название объекта",
                        score=0.9 if confidence == "confirmed" else 0.1,
                        decided_by="rules",
                    )
                )

    yield {"run_id": run_id, "ids": ids}

    async with session_factory() as session, session.begin():
        await session.execute(delete(ResearchRun).where(ResearchRun.id == run_id))
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))


def repo(session_factory) -> SqlResearchRepository:
    return SqlResearchRepository(session_factory)


class TestRuns:
    @pytest.mark.asyncio
    async def test_run_carries_its_funnel(self, session_factory, run) -> None:
        """Воронка приезжает вместе с прогоном — иначе её негде взять."""
        card = await repo(session_factory).run(run["run_id"])

        assert card is not None
        assert card.funnel.tenders_total == 1000
        # Знаменатель: без него «находок 9» ничего не говорит.
        assert card.funnel.documents_pending == 640
        assert card.regions == ["77", "50"]

    @pytest.mark.asyncio
    async def test_missing_run_is_none(self, session_factory) -> None:
        assert await repo(session_factory).run(10_000_000) is None

    @pytest.mark.asyncio
    async def test_runs_are_listed_newest_first(self, session_factory, run) -> None:
        cards = await repo(session_factory).runs(50)
        assert run["run_id"] in [c.run_id for c in cards]


class TestTenders:
    @pytest.mark.asyncio
    async def test_all_tenders_of_the_run_are_returned(self, session_factory, run) -> None:
        items, total = await repo(session_factory).tenders(run["run_id"], None, 50, 0)

        assert total == 3
        assert {i.reg_num for i in items} == {
            f"{PREFIX}CONFIRMED",
            f"{PREFIX}REJECTED",
            f"{PREFIX}DISPUTED",
        }

    @pytest.mark.asyncio
    async def test_tender_without_a_verdict_is_disputed_not_rejected(
        self, session_factory, run
    ) -> None:
        """До закупки не дошли — это не «отклонено». Врать нельзя."""
        items, _ = await repo(session_factory).tenders(run["run_id"], None, 50, 0)
        disputed = next(i for i in items if i.reg_num == f"{PREFIX}DISPUTED")

        assert disputed.confidence == "disputed"

    @pytest.mark.asyncio
    async def test_filtering_by_confidence(self, session_factory, run) -> None:
        items, total = await repo(session_factory).tenders(
            run["run_id"], "confirmed", 50, 0
        )
        assert total == 1
        assert items[0].reg_num == f"{PREFIX}CONFIRMED"

    @pytest.mark.asyncio
    async def test_hits_carry_offsets_for_highlighting(self, session_factory, run) -> None:
        """Смещение — то, без чего обрезка цитаты прячет совпадение."""
        items, _ = await repo(session_factory).tenders(run["run_id"], "confirmed", 50, 0)
        hit = items[0].hits[0]

        assert hit.quote[hit.match_start : hit.match_end] == "БПК5"
        assert hit.file_name == "ТЗ.docx"
        assert hit.page == 4

    @pytest.mark.asyncio
    async def test_pagination(self, session_factory, run) -> None:
        first, total = await repo(session_factory).tenders(run["run_id"], None, 2, 0)
        second, _ = await repo(session_factory).tenders(run["run_id"], None, 2, 2)

        assert total == 3
        assert len(first) == 2 and len(second) == 1
        assert {i.tender_id for i in first} & {i.tender_id for i in second} == set()


class TestMarket:
    @pytest.mark.asyncio
    async def test_only_confirmed_tenders_count(self, session_factory, run) -> None:
        """Отклонённая закупка на 900 тыс. в сумму рынка попадать не должна."""
        market = await repo(session_factory).market(run["run_id"])

        assert market.total_count == 1
        assert market.total_value == Decimal("5000000")

    @pytest.mark.asyncio
    async def test_median_comes_with_the_mean(self, session_factory, run) -> None:
        market = await repo(session_factory).market(run["run_id"])

        assert market.median_price is not None
        assert market.average_price is not None

    @pytest.mark.asyncio
    async def test_customers_are_grouped_by_inn_with_a_readable_label(
        self, session_factory, run
    ) -> None:
        """Ключ — ИНН, подпись — название: под одним именем бывают разные юрлица."""
        market = await repo(session_factory).market(run["run_id"])

        assert market.by_customer[0].key == "5000000001"
        assert market.by_customer[0].label == "Водоканал"

    @pytest.mark.asyncio
    async def test_region_gets_a_human_label(self, session_factory, run) -> None:
        market = await repo(session_factory).market(run["run_id"])
        assert market.by_region[0].label == "Московская область"

    @pytest.mark.asyncio
    async def test_market_of_a_missing_run_is_empty(self, session_factory) -> None:
        market = await repo(session_factory).market(10_000_000)
        assert market.total_count == 0

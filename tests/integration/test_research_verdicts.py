"""Шов между судьёй и отбором каталога.

Дефект, ради которого написан этот файл, прожил долго именно потому, что его
некому было увидеть: юнит-тесты проверяли `outcome.verdicts` в памяти, а
интеграционные вставляли вердикты в базу руками. Каждый гонял либо
производителя без писателя, либо читателя без производителя, и шов между ними
не пересекал никто.

Здесь настоящий `JudgeDisputedUseCase` пишет через настоящий `SqlVerdictStore`,
а спрашивает `libs/shared/db/tender_criteria.py` — тот самый отбор, которым
каталог показывает выдачу по сохранённому фильтру.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from libs.shared.db.schema import ResearchVerdict, SavedFilter, Tender
from libs.shared.db.tender_criteria import TenderCriteria, predicates
from services.research.application.ports import TenderCandidate
from services.research.application.use_cases.judge_disputed import JudgeDisputedUseCase
from services.research.domain.criteria import OXYGEN_DEMAND_CRITERIA as CRITERIA
from services.research.domain.hits import find_hits
from services.research.domain.verdict import ModelVerdict
from services.research.infrastructure.repositories import SqlVerdictStore

PREFIX = "TEST-VERDICT-"

CONFIRMED_TEXT = "ХПК не более 30 мг/дм3 в сточных водах"
REJECTED_TEXT = "Капитальный ремонт кровли БПК ФКУ СИЗО-12"
DISPUTED_TEXT = "Поставка стандартов. Показатель ХПК"


class FakeModel:
    """Модель, отвечающая заранее известное."""

    def __init__(self, match: bool = True) -> None:
        self.verdict = ModelVerdict(match=match, score=0.9, reasoning="решение модели")
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def judge(self, system: str, user: str) -> ModelVerdict:
        self.prompts.append(user)
        return self.verdict


@pytest.fixture
async def corpus(session_factory):
    """Три закупки под три исхода: правила «за», правила «против», спор."""
    now = datetime.now(UTC)
    ids: dict[str, int] = {}
    async with session_factory() as session, session.begin():
        for key, name in (
            ("confirmed", "Химический анализ сточных вод"),
            ("rejected", "Капитальный ремонт кровли"),
            ("disputed", "Поставка стандартных образцов"),
        ):
            ids[key] = await session.scalar(
                Tender.__table__.insert()
                .values(
                    reg_num=f"{PREFIX}{key.upper()}",
                    name=name,
                    region_code="77",
                    publish_date=now - timedelta(days=1),
                    okpd2_code="71.20.11",
                    okpd2_codes=["71.20.11"],
                )
                .returning(Tender.id)
            )

        ids["filter"] = await session.scalar(
            SavedFilter.__table__.insert()
            .values(
                name=f"{PREFIX}фильтр",
                spec={"name": "ХПК/БПК", "version": CRITERIA.version},
            )
            .returning(SavedFilter.id)
        )

    yield ids

    async with session_factory() as session, session.begin():
        await session.execute(
            delete(ResearchVerdict).where(
                ResearchVerdict.tender_id.in_(
                    [ids["confirmed"], ids["rejected"], ids["disputed"]]
                )
            )
        )
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))
        await session.execute(delete(SavedFilter).where(SavedFilter.id == ids["filter"]))


def _candidate(tender_id: int, text: str) -> TenderCandidate:
    return TenderCandidate(
        tender_id=tender_id,
        reg_num=f"REG-{tender_id}",
        hits=find_hits(text, CRITERIA, file_name="ТЗ.docx"),
    )


async def _selected(session_factory, filter_id: int, **kwargs) -> set[int]:
    """Кого вернёт каталог по этому фильтру — тем же правилом отбора."""
    criteria = TenderCriteria(filter_id=filter_id, **kwargs)
    async with session_factory() as session:
        rows = await session.scalars(
            select(Tender.id).where(*predicates(criteria).values())
        )
    return set(rows)


class TestTheSeam:
    @pytest.mark.asyncio
    async def test_rules_verdicts_reach_the_catalog(self, session_factory, corpus) -> None:
        """Главное утверждение: правила решают большинство, и это видно в выдаче."""
        store = SqlVerdictStore(session_factory)
        await JudgeDisputedUseCase(CRITERIA, FakeModel(), store=store).execute(
            [
                _candidate(corpus["confirmed"], CONFIRMED_TEXT),
                _candidate(corpus["rejected"], REJECTED_TEXT),
                _candidate(corpus["disputed"], DISPUTED_TEXT),
            ]
        )

        matched = await _selected(session_factory, corpus["filter"])

        # Подтверждённая правилами обязана быть здесь — ровно этого и не было.
        assert corpus["confirmed"] in matched
        # Модель сказала «подходит» по спорной — она тоже проходит.
        assert corpus["disputed"] in matched
        assert corpus["rejected"] not in matched

    @pytest.mark.asyncio
    async def test_rejected_are_reachable_on_request(self, session_factory, corpus) -> None:
        """«Что этот фильтр отклонил» — вопрос, который тоже надо уметь задать."""
        store = SqlVerdictStore(session_factory)
        await JudgeDisputedUseCase(CRITERIA, FakeModel(), store=store).execute(
            [
                _candidate(corpus["confirmed"], CONFIRMED_TEXT),
                _candidate(corpus["rejected"], REJECTED_TEXT),
            ]
        )

        rejected = await _selected(
            session_factory, corpus["filter"], filter_verdicts=("rejected",)
        )

        assert rejected == {corpus["rejected"]}

    @pytest.mark.asyncio
    async def test_a_run_without_disputes_still_lands(
        self, session_factory, corpus
    ) -> None:
        """Ранний возврат в судье не должен уносить решения правил."""
        store = SqlVerdictStore(session_factory)
        await JudgeDisputedUseCase(CRITERIA, FakeModel(), store=store).execute(
            [_candidate(corpus["confirmed"], CONFIRMED_TEXT)]
        )

        assert await _selected(session_factory, corpus["filter"]) == {corpus["confirmed"]}

    @pytest.mark.asyncio
    async def test_dry_run_leaves_the_catalog_alone(self, session_factory, corpus) -> None:
        """Пробный прогон не имеет права попасть в выдачу настоящего фильтра."""
        store = SqlVerdictStore(session_factory)
        await JudgeDisputedUseCase(
            CRITERIA, FakeModel(), store=store, dry_run=True
        ).execute(
            [
                _candidate(corpus["confirmed"], CONFIRMED_TEXT),
                _candidate(corpus["disputed"], DISPUTED_TEXT),
            ]
        )

        assert await _selected(session_factory, corpus["filter"]) == set()

    @pytest.mark.asyncio
    async def test_rules_verdicts_cost_nothing(self, session_factory, corpus) -> None:
        """`model IS NULL` отделяет бесплатные решения от оплаченных."""
        store = SqlVerdictStore(session_factory)
        await JudgeDisputedUseCase(CRITERIA, FakeModel(), store=store).execute(
            [
                _candidate(corpus["confirmed"], CONFIRMED_TEXT),
                _candidate(corpus["disputed"], DISPUTED_TEXT),
            ]
        )

        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(ResearchVerdict.decided_by, ResearchVerdict.model).where(
                        ResearchVerdict.tender_id.in_(
                            [corpus["confirmed"], corpus["disputed"]]
                        )
                    )
                )
            ).all()

        assert dict(rows) == {"rules": None, "model": "fake-model"}

"""Персистентность движка отбора против настоящего Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from libs.shared.db.schema import (
    DocumentText,
    ResearchHit,
    ResearchRun,
    ResearchVerdict,
    Tender,
    TenderDocument,
)
from services.research.application.ports import TenderVerdict
from services.research.domain.criteria import OXYGEN_DEMAND_CRITERIA as CRITERIA
from services.research.domain.criteria import Confidence
from services.research.domain.hits import find_hits
from services.research.domain.verdict import JUDGE_PROMPT_VERSION
from services.research.infrastructure.repositories import (
    SqlCorpusRepository,
    SqlHitRepository,
    SqlResearchRunRepository,
    SqlVerdictStore,
)

PREFIX = "TEST-RESEARCH-"


@pytest.fixture
async def corpus(session_factory):
    """Две закупки: у одной документ с текстом, у другой — без."""
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        water = await session.scalar(
            Tender.__table__.insert()
            .values(
                reg_num=f"{PREFIX}WATER",
                name="Химический анализ сточных вод",
                region_code="77",
                publish_date=now - timedelta(days=1),
                okpd2_code="71.20.11",
                okpd2_codes=["71.20.11"],
            )
            .returning(Tender.id)
        )
        other = await session.scalar(
            Tender.__table__.insert()
            .values(
                reg_num=f"{PREFIX}OTHER",
                name="Поставка офисной мебели",
                region_code="50",
                publish_date=now - timedelta(days=1),
                okpd2_code="31.01.11",
            )
            .returning(Tender.id)
        )

        with_text = await session.scalar(
            TenderDocument.__table__.insert()
            .values(
                tender_id=water,
                attachment_id="TZ",
                file_name="ТЗ.docx",
                extraction_status="done",
                priority=0,
            )
            .returning(TenderDocument.id)
        )
        await session.execute(
            DocumentText.__table__.insert().values(
                document_id=with_text,
                tender_id=water,
                text_key="texts/aa/water.txt",
                text_sha256="a" * 64,
                char_count=100,
            )
        )
        # Документ без извлечённого текста — тот самый знаменатель воронки.
        await session.execute(
            TenderDocument.__table__.insert().values(
                tender_id=water,
                attachment_id="SCAN",
                file_name="скан.pdf",
                extraction_status="deferred",
            )
        )

    yield {"water": water, "other": other, "document": with_text}

    async with session_factory() as session, session.begin():
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))


class TestCorpus:
    @pytest.mark.asyncio
    async def test_tenders_are_streamed(self, session_factory, corpus) -> None:
        repo = SqlCorpusRepository(session_factory)
        found = [
            tender
            async for tender in repo.tenders(["77"], None, None)
            if tender.reg_num.startswith(PREFIX)
        ]

        assert [t.reg_num for t in found] == [f"{PREFIX}WATER"]
        assert found[0].okpd2_codes == ("71.20.11",)

    @pytest.mark.asyncio
    async def test_documents_without_text_come_back_too(
        self, session_factory, corpus
    ) -> None:
        """Неразобранный документ — это знаменатель, и он обязан доехать до обхода.

        Раньше запрос отсекал такие соединением, а знаменатель считался
        отдельно по всему корпусу — то есть по другой популяции, чем числитель.
        """
        documents = await SqlCorpusRepository(session_factory).documents(corpus["water"])

        assert sorted(d.file_name for d in documents) == ["ТЗ.docx", "скан.pdf"]
        assert [d.text_key for d in documents if d.text_key] == ["texts/aa/water.txt"]
        # Нечитаемый приезжает с пустым ключом — по нему проход и считает пропуск.
        assert any(d.text_key is None for d in documents)


class TestHits:
    @pytest.mark.asyncio
    async def test_hits_are_stored_with_their_offsets(
        self, session_factory, corpus
    ) -> None:
        """Смещение — то, что позволяет показать цитату с подсветкой."""
        runs = SqlResearchRunRepository(session_factory)
        run_id = await runs.start("проба", CRITERIA, ["77"], None, None)

        hits = find_hits("норматив по показателю БПК5 в сточной воде", CRITERIA,
                         file_name="ТЗ.docx")
        await SqlHitRepository(session_factory).save(run_id, corpus["water"], hits)

        async with session_factory() as session:
            row = await session.scalar(
                select(ResearchHit).where(ResearchHit.run_id == run_id)
            )

        assert row.term == "БПК"
        assert row.quote[row.match_start : row.match_end] == "БПК5"

        async with session_factory() as session, session.begin():
            await session.execute(delete(ResearchRun).where(ResearchRun.id == run_id))


class TestRuns:
    @pytest.mark.asyncio
    async def test_criteria_are_stored_readably(self, session_factory) -> None:
        """Прогон должен быть объясним задним числом: чем именно искали."""
        runs = SqlResearchRunRepository(session_factory)
        run_id = await runs.start("ХПК/БПК", CRITERIA, ["77", "50"], None, None)

        async with session_factory() as session:
            row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))

        assert row.criteria_version == CRITERIA.version
        assert {t["name"] for t in row.criteria["terms"]} == {
            "ХПК", "БПК", "потребление кислорода"
        }
        # Шаблон хранится текстом — видно, что пробела внутри аббревиатуры нет.
        pattern = next(t["pattern"] for t in row.criteria["terms"] if t["name"] == "БПК")
        assert r"\s?" not in pattern

        async with session_factory() as session, session.begin():
            await session.execute(delete(ResearchRun).where(ResearchRun.id == run_id))


class TestVerdictStore:
    @pytest.mark.asyncio
    async def test_verdict_survives_a_round_trip(self, session_factory, corpus) -> None:
        store = SqlVerdictStore(session_factory)
        verdict = TenderVerdict(
            tender_id=corpus["water"],
            confidence=Confidence.CONFIRMED,
            reason="химия воды",
            score=0.91,
            decided_by="model",
            evidence=[{"hit_number": 1, "quote": "БПК5"}],
        )

        await store.save([verdict], CRITERIA.version, JUDGE_PROMPT_VERSION, "test-model")
        found = await store.stored(
            [corpus["water"]], CRITERIA.version, JUDGE_PROMPT_VERSION
        )

        assert found[corpus["water"]].confidence is Confidence.CONFIRMED
        assert found[corpus["water"]].score == pytest.approx(0.91)

        await _clear(session_factory, corpus["water"])

    @pytest.mark.asyncio
    async def test_new_criteria_version_invalidates_the_cache(
        self, session_factory, corpus
    ) -> None:
        """Правка шаблонов обязана обесценить прежние решения, а не смешаться с ними."""
        store = SqlVerdictStore(session_factory)
        await store.save(
            [
                TenderVerdict(
                    tender_id=corpus["water"], confidence=Confidence.CONFIRMED, reason="x"
                )
            ],
            "хпк-бпк-v2",
            JUDGE_PROMPT_VERSION,
            "test-model",
        )

        assert await store.stored([corpus["water"]], "хпк-бпк-v3", JUDGE_PROMPT_VERSION) == {}

        await _clear(session_factory, corpus["water"])

    @pytest.mark.asyncio
    async def test_saving_twice_updates_instead_of_duplicating(
        self, session_factory, corpus
    ) -> None:
        store = SqlVerdictStore(session_factory)
        for reason in ("первое", "второе"):
            await store.save(
                [
                    TenderVerdict(
                        tender_id=corpus["water"],
                        confidence=Confidence.REJECTED,
                        reason=reason,
                    )
                ],
                CRITERIA.version,
                JUDGE_PROMPT_VERSION,
                "test-model",
            )

        found = await store.stored(
            [corpus["water"]], CRITERIA.version, JUDGE_PROMPT_VERSION
        )
        assert found[corpus["water"]].reason == "второе"

        await _clear(session_factory, corpus["water"])

    @pytest.mark.asyncio
    async def test_rules_verdicts_carry_no_model(self, session_factory, corpus) -> None:
        """`model IS NULL` — признак решения, которое ничего не стоило."""
        store = SqlVerdictStore(session_factory)
        await store.save(
            [
                TenderVerdict(
                    tender_id=corpus["water"],
                    confidence=Confidence.CONFIRMED,
                    reason="по правилам",
                    decided_by="rules",
                )
            ],
            CRITERIA.version,
            JUDGE_PROMPT_VERSION,
            "test-model",
        )

        async with session_factory() as session:
            model = await session.scalar(
                select(ResearchVerdict.model).where(
                    ResearchVerdict.tender_id == corpus["water"]
                )
            )
        assert model is None

        await _clear(session_factory, corpus["water"])

    @pytest.mark.asyncio
    async def test_a_batch_with_one_tender_twice_does_not_explode(
        self, session_factory, corpus
    ) -> None:
        """Postgres не применяет ON CONFLICT дважды к одной строке за INSERT."""
        store = SqlVerdictStore(session_factory)
        await store.save(
            [
                TenderVerdict(
                    tender_id=corpus["water"], confidence=Confidence.REJECTED, reason="раз"
                ),
                TenderVerdict(
                    tender_id=corpus["water"], confidence=Confidence.CONFIRMED, reason="два"
                ),
            ],
            CRITERIA.version,
            JUDGE_PROMPT_VERSION,
            "test-model",
        )

        found = await store.stored(
            [corpus["water"]], CRITERIA.version, JUDGE_PROMPT_VERSION
        )
        assert found[corpus["water"]].reason == "два"

        await _clear(session_factory, corpus["water"])


async def _clear(session_factory, tender_id: int) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(ResearchVerdict).where(ResearchVerdict.tender_id == tender_id)
        )

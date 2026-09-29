"""Управление фильтрами: запись в llm-service, чтение в шлюзе.

Разрез по CQRS проверяется здесь целиком: обе стороны работают с одной таблицей,
и разойтись они не должны.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from libs.shared.contracts.criteria_spec import (
    ContextRuleSpec,
    CriteriaSpec,
    StructuralSpec,
    TermSpec,
)
from libs.shared.db.schema import LlmVerdict, SavedFilter, Tender
from services.api.domain.filters import MATCH_HISTORY_DAYS
from services.api.infrastructure.db.filter_repository import SqlFilterReadRepository
from services.llm_service.domain.models import FilterPatch
from services.llm_service.infrastructure.db.repositories import SqlFilterRepository
from services.research.infrastructure.repositories import SqlCriteriaRepository

PREFIX = "TEST-FILTERS-"


@pytest.fixture
async def writer(session_factory) -> SqlFilterRepository:
    return SqlFilterRepository(session_factory)


@pytest.fixture
def reader(session_factory) -> SqlFilterReadRepository:
    return SqlFilterReadRepository(session_factory)


@pytest.fixture
async def cleanup(session_factory):
    yield
    async with session_factory() as session, session.begin():
        await session.execute(delete(SavedFilter).where(SavedFilter.name.like(f"{PREFIX}%")))
        await session.execute(
            delete(SavedFilter).where(SavedFilter.name.like(f"%{PREFIX}%(копия)"))
        )
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))


def spec_of(name: str = "Поставка газа") -> CriteriaSpec:
    return CriteriaSpec(
        name=name,
        terms=[TermSpec(name="газ", pattern=r"газ\w*")],
        structural=StructuralSpec(regions=["77"]),
    )


@pytest.mark.asyncio
async def test_saved_filter_is_readable_by_the_gateway(writer, reader, cleanup) -> None:
    filter_id = await writer.save_spec(f"{PREFIX}Газ", "поставка газа", spec_of())

    card = await reader.get(filter_id, MATCH_HISTORY_DAYS)

    assert card is not None
    assert card.name == f"{PREFIX}Газ"
    # Исходный текст хранится отдельно от спецификации — ради истории.
    assert card.query == "поставка газа"
    assert [t["name"] for t in card.spec["terms"]] == ["газ"]
    # Значения по умолчанию: в сводку попадает, уведомлений не шлёт.
    assert card.in_digest is True
    assert card.notify is False
    assert card.last_run_at is None


@pytest.mark.asyncio
async def test_edited_spec_is_stored_verbatim(writer, reader, cleanup) -> None:
    """Правки конструктора не должны теряться при сохранении.

    Пользователь сменил роль термина, убрал регион и добавил правило по
    контексту — всё это обязано доехать до базы дословно. Перекомпиляция текста
    здесь молча откатила бы его работу.
    """
    edited = spec_of()
    edited.terms[0].role = "supporting"
    edited.terms.append(TermSpec(name="баллон", pattern=r"баллон\w*"))
    edited.context_rules.append(
        ContextRuleSpec(name="не тара", pattern="упаковк", verdict="rejected", window=40)
    )
    edited.structural.regions = []

    filter_id = await writer.save_spec(f"{PREFIX}Правленый", "поставка газа в москве", edited)
    card = await reader.get(filter_id, MATCH_HISTORY_DAYS)

    assert card is not None
    assert card.spec["structural"]["regions"] == []
    assert [t["role"] for t in card.spec["terms"]] == ["supporting", "primary"]
    assert card.spec["context_rules"][0]["window"] == 40
    # Текст сохранён как был, хотя spec ему уже не соответствует.
    assert card.query == "поставка газа в москве"


@pytest.mark.asyncio
async def test_patch_touches_only_named_fields(writer, reader, cleanup) -> None:
    filter_id = await writer.save_spec(f"{PREFIX}Газ", "поставка газа", spec_of())

    await writer.update_filter(filter_id, FilterPatch(notify=True))
    card = await reader.get(filter_id, MATCH_HISTORY_DAYS)

    assert card is not None
    assert card.notify is True
    # Остальное не поехало.
    assert card.in_digest is True
    assert card.name == f"{PREFIX}Газ"
    assert [t["name"] for t in card.spec["terms"]] == ["газ"]


@pytest.mark.asyncio
async def test_run_is_marked_and_visible_to_the_reader(
    writer, reader, session_factory, cleanup
) -> None:
    """Отметку о прогоне ставит движок отбора, а читает её шлюз.

    Отметку когда-то умел ставить llm-service, но не звал никто, и `last_run_at`
    не заполнялся никогда. Меню фильтров на каталоге показывает по нему
    «не запускался», поэтому писать обязан тот, кто прогон и выполняет.
    """
    filter_id = await writer.save_spec(f"{PREFIX}Газ", "поставка газа", spec_of())

    assert (await reader.get(filter_id, MATCH_HISTORY_DAYS)).last_run_at is None

    await SqlCriteriaRepository(session_factory).mark_run(filter_id)
    card = await reader.get(filter_id, MATCH_HISTORY_DAYS)

    assert card is not None and card.last_run_at is not None


@pytest.mark.asyncio
async def test_delete_removes_filter_and_its_verdicts(
    writer, reader, session_factory, cleanup
) -> None:
    filter_id = await writer.save_spec(f"{PREFIX}Газ", "поставка газа", spec_of())

    async with session_factory() as session, session.begin():
        tender_id = await session.scalar(
            Tender.__table__.insert()
            .values(reg_num=f"{PREFIX}1", name="Поставка газа")
            .returning(Tender.id)
        )
        await session.execute(
            LlmVerdict.__table__.insert().values(
                tender_id=tender_id,
                filter_id=filter_id,
                match=True,
                model="test",
                prompt_version="judge-v1",
            )
        )

    assert await writer.delete_filter(filter_id) is True
    assert await reader.get(filter_id, MATCH_HISTORY_DAYS) is None

    async with session_factory() as session:
        # Вердикты без фильтра не интерпретируются — уходят каскадом.
        left = await session.scalar(
            LlmVerdict.__table__.select().where(LlmVerdict.filter_id == filter_id)
        )
    assert left is None


@pytest.mark.asyncio
async def test_delete_of_missing_filter_reports_failure(writer, cleanup) -> None:
    assert await writer.delete_filter(10_000_000) is False


@pytest.mark.asyncio
async def test_match_counts_group_positive_verdicts_by_day(
    writer, reader, session_factory, cleanup
) -> None:
    filter_id = await writer.save_spec(f"{PREFIX}Газ", "поставка газа", spec_of())
    now = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        for index, (match, moment) in enumerate(
            [
                (True, now),
                (True, now),
                (False, now),
                # За пределами окна истории — в спарклайн не попадает.
                (True, now - timedelta(days=MATCH_HISTORY_DAYS + 3)),
            ]
        ):
            tender_id = await session.scalar(
                Tender.__table__.insert()
                .values(reg_num=f"{PREFIX}{index}", name="Поставка газа")
                .returning(Tender.id)
            )
            await session.execute(
                LlmVerdict.__table__.insert().values(
                    tender_id=tender_id,
                    filter_id=filter_id,
                    match=match,
                    model="test",
                    prompt_version="judge-v1",
                    created_at=moment,
                )
            )

    card = await reader.get(filter_id, MATCH_HISTORY_DAYS)

    assert card is not None
    # Только положительные и только за окно истории.
    assert sum(c.count for c in card.match_counts) == 2


@pytest.mark.asyncio
async def test_listing_carries_counts_for_every_filter(writer, reader, cleanup) -> None:
    await writer.save_spec(f"{PREFIX}Первый", "поставка газа", spec_of())
    await writer.save_spec(f"{PREFIX}Второй", "поставка мебели", spec_of())

    cards = await reader.list(MATCH_HISTORY_DAYS)

    ours = [c for c in cards if c.name.startswith(PREFIX)]
    assert len(ours) == 2
    assert all(isinstance(c.match_counts, list) for c in ours)

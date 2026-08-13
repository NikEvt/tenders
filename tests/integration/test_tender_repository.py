"""Upsert тендеров: определение новизны, история дедлайна, вложения."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from libs.shared.db.schema import Tender as TenderRow
from libs.shared.db.schema import TenderDocument as DocumentRow
from services.crawler.domain.models import Attachment, Tender
from services.crawler.infrastructure.db.tender_repository import SqlTenderRepository


def make_tender(reg_num: str = "TEST-0000000001", **overrides) -> Tender:
    defaults = dict(
        name="Поставка газа в баллонах",
        description="Поставка технических газов в баллонах для нужд учреждения",
        price=Decimal("950000.00"),
        end_date=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
        customer_inn="7718690579",
        okpd2_codes=["20.11.11"],
        okpd2_names=["Газы промышленные"],
        region_code="77",
    )
    defaults.update(overrides)
    return Tender(reg_num=reg_num, **defaults)


@pytest.mark.asyncio
async def test_insert_then_update_reports_novelty(session) -> None:
    repo = SqlTenderRepository(session)

    first = await repo.upsert_many([make_tender()])
    assert len(first) == 1
    assert first[0].is_new is True

    second = await repo.upsert_many([make_tender(name="Уточнённое наименование")])
    assert second[0].is_new is False
    assert second[0].id == first[0].id

    row = await session.scalar(select(TenderRow).where(TenderRow.id == first[0].id))
    assert row.name == "Уточнённое наименование"


@pytest.mark.asyncio
async def test_prev_end_date_records_deadline_shift(session) -> None:
    repo = SqlTenderRepository(session)
    original = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    moved = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)

    saved = await repo.upsert_many([make_tender(end_date=original)])
    tender_id = saved[0].id

    row = await session.scalar(select(TenderRow).where(TenderRow.id == tender_id))
    assert row.prev_end_date is None

    await repo.upsert_many([make_tender(end_date=moved)])
    await session.refresh(row)
    assert row.end_date == moved
    assert row.prev_end_date == original

    # Повторная выгрузка без изменения даты не должна затирать историю сдвига.
    await repo.upsert_many([make_tender(end_date=moved)])
    await session.refresh(row)
    assert row.prev_end_date == original


@pytest.mark.asyncio
async def test_created_at_survives_update(session) -> None:
    """Регрессия: прежний upsert обновлял created_at вместо updated_at."""
    repo = SqlTenderRepository(session)
    saved = await repo.upsert_many([make_tender()])
    row = await session.scalar(select(TenderRow).where(TenderRow.id == saved[0].id))
    created_at = row.created_at

    await repo.upsert_many([make_tender(price=Decimal("1000000.00"))])
    await session.refresh(row)

    assert row.created_at == created_at
    assert row.updated_at >= created_at


@pytest.mark.asyncio
async def test_duplicate_reg_num_in_one_batch(session) -> None:
    """ЕИС отдаёт несколько версий извещения за день; побеждает последняя."""
    repo = SqlTenderRepository(session)
    saved = await repo.upsert_many(
        [make_tender(name="Версия 1"), make_tender(name="Версия 2")]
    )
    assert len(saved) == 1

    row = await session.scalar(select(TenderRow).where(TenderRow.id == saved[0].id))
    assert row.name == "Версия 2"


@pytest.mark.asyncio
async def test_attachments_are_stored_and_reupserted(session) -> None:
    repo = SqlTenderRepository(session)
    attachments = [
        Attachment(
            attachment_id="AAA",
            file_name="Техническое задание.pdf",
            url="https://zakupki.gov.ru/44fz/filestore/x?uid=AAA",
            file_size=1234,
            doc_kind_code="POD",
        ),
        Attachment(
            attachment_id="BBB",
            file_name="Проект контракта.pdf",
            url="https://zakupki.gov.ru/44fz/filestore/x?uid=BBB",
        ),
        # Без url скачать нечего — такое вложение записывать не нужно.
        Attachment(attachment_id="CCC", file_name="Битое.pdf", url=None),
    ]

    saved = await repo.upsert_many([make_tender(attachments=attachments)])
    assert saved[0].attachment_count == 2

    rows = (
        await session.scalars(
            select(DocumentRow).where(DocumentRow.tender_id == saved[0].id)
        )
    ).all()
    assert {r.attachment_id for r in rows} == {"AAA", "BBB"}
    assert all(r.extraction_status == "pending" for r in rows)

    # Повторная выгрузка не должна плодить дубли вложений.
    await repo.upsert_many([make_tender(attachments=attachments)])
    rows_again = (
        await session.scalars(
            select(DocumentRow).where(DocumentRow.tender_id == saved[0].id)
        )
    ).all()
    assert len(rows_again) == 2


@pytest.mark.asyncio
async def test_search_tsv_is_populated_by_database(session) -> None:
    repo = SqlTenderRepository(session)
    saved = await repo.upsert_many([make_tender()])

    found = await session.scalar(
        select(TenderRow.id).where(
            TenderRow.id == saved[0].id,
            TenderRow.search_tsv.bool_op("@@")(
                func.plainto_tsquery("russian", "баллоны газ")
            ),
        )
    )
    assert found == saved[0].id

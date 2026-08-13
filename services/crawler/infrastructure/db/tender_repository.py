"""Персистентность тендеров и вложений."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, func, literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from libs.shared.db.schema import Tender as TenderRow
from libs.shared.db.schema import TenderDocument as DocumentRow
from libs.shared.logging import get_logger
from services.crawler.application.ports import SavedTender, TenderRepositoryPort
from services.crawler.domain.models import Tender

log = get_logger(__name__)

UPSERT_PAGE_SIZE = 200


class SqlTenderRepository(TenderRepositoryPort):
    """Information Expert по хранению тендеров.

    Работает в транзакции вызывающего use-case, поэтому запись тендеров и запись
    событий в outbox коммитятся вместе.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, tenders: Sequence[Tender]) -> list[SavedTender]:
        if not tenders:
            return []

        # ON CONFLICT DO UPDATE падает, если один reg_num встречается в батче дважды.
        # В выгрузке ЕИС дубли — норма (несколько версий извещения за день),
        # побеждает последняя версия.
        unique: dict[str, Tender] = {t.reg_num: t for t in tenders if t.is_valid}
        ordered = list(unique.values())

        saved: list[SavedTender] = []
        for start in range(0, len(ordered), UPSERT_PAGE_SIZE):
            saved.extend(await self._upsert_page(ordered[start : start + UPSERT_PAGE_SIZE]))
        return saved

    async def _upsert_page(self, tenders: list[Tender]) -> list[SavedTender]:
        rows = [self._to_row(t) for t in tenders]

        statement = pg_insert(TenderRow).values(rows)
        excluded = statement.excluded

        statement = statement.on_conflict_do_update(
            index_elements=[TenderRow.reg_num],
            set_={
                "name": excluded.name,
                "description": excluded.description,
                "price": excluded.price,
                "currency": excluded.currency,
                "publish_date": excluded.publish_date,
                "direct_date": excluded.direct_date,
                "planned_publish_date": excluded.planned_publish_date,
                "start_date": excluded.start_date,
                # Сдвиг срока приёма заявок — сильный сигнал для пользователя,
                # поэтому прежний дедлайн сохраняется, а не затирается.
                "prev_end_date": case(
                    (
                        excluded.end_date.is_distinct_from(TenderRow.end_date),
                        TenderRow.end_date,
                    ),
                    else_=TenderRow.prev_end_date,
                ),
                "end_date": excluded.end_date,
                "bidding_date": excluded.bidding_date,
                "summarizing_date": excluded.summarizing_date,
                "contract_end_date": excluded.contract_end_date,
                "customer_name": excluded.customer_name,
                "customer_inn": excluded.customer_inn,
                "customer_region": excluded.customer_region,
                "region_code": excluded.region_code,
                "okpd2_code": excluded.okpd2_code,
                "okpd2_name": excluded.okpd2_name,
                "okpd2_codes": excluded.okpd2_codes,
                "law_type": excluded.law_type,
                "status": excluded.status,
                "raw_xml": excluded.raw_xml,
                # Прежний код здесь обновлял created_at — дата создания записи
                # затиралась при каждом повторном заходе краулера.
                "updated_at": func.now(),
            },
        ).returning(
            TenderRow.id,
            TenderRow.reg_num,
            # xmax = 0 у только что вставленной строки; у обновлённой — id транзакции.
            literal_column("(xmax = 0)").label("is_new"),
        )

        result = await self._session.execute(statement)
        by_reg_num = {t.reg_num: t for t in tenders}

        saved: list[SavedTender] = []
        for row in result.all():
            tender = by_reg_num[row.reg_num]
            await self._upsert_attachments(row.id, tender)
            saved.append(
                SavedTender(
                    id=row.id,
                    reg_num=row.reg_num,
                    is_new=bool(row.is_new),
                    attachment_count=len(tender.downloadable_attachments),
                )
            )
        return saved

    async def _upsert_attachments(self, tender_id: int, tender: Tender) -> None:
        """Пишет метаданные вложений. Файлы качает docs-worker, не краулер."""
        attachments = tender.downloadable_attachments
        if not attachments:
            return

        rows = [
            {
                "tender_id": tender_id,
                "attachment_id": a.attachment_id,
                "file_name": a.file_name,
                "doc_kind_code": a.doc_kind_code,
                "doc_kind_name": a.doc_kind_name,
                "doc_description": a.doc_description,
                "source_url": a.url,
                "file_size": a.file_size,
            }
            for a in attachments
        ]

        statement = pg_insert(DocumentRow).values(rows)
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_tender_attachment",
                set_={
                    "file_name": statement.excluded.file_name,
                    "source_url": statement.excluded.source_url,
                    "file_size": statement.excluded.file_size,
                    "doc_kind_code": statement.excluded.doc_kind_code,
                    "doc_kind_name": statement.excluded.doc_kind_name,
                    "doc_description": statement.excluded.doc_description,
                    "updated_at": func.now(),
                },
            )
        )

    @staticmethod
    def _to_row(tender: Tender) -> dict[str, Any]:
        return {
            "reg_num": tender.reg_num,
            "name": tender.name,
            "description": tender.description,
            "price": tender.price,
            "currency": tender.currency,
            "publish_date": tender.publish_date,
            "direct_date": tender.direct_date,
            "planned_publish_date": tender.planned_publish_date,
            "start_date": tender.start_date,
            "end_date": tender.end_date,
            "bidding_date": tender.bidding_date,
            "summarizing_date": tender.summarizing_date,
            "contract_end_date": tender.contract_end_date,
            "customer_name": tender.customer_name,
            "customer_inn": tender.customer_inn,
            "customer_region": tender.customer_region,
            "region_code": tender.region_code,
            "okpd2_code": tender.okpd2_code,
            "okpd2_name": tender.okpd2_name,
            "okpd2_codes": tender.okpd2_codes or None,
            "law_type": tender.law_type,
            "status": str(tender.status_at()),
            "raw_xml": tender.raw_xml,
        }

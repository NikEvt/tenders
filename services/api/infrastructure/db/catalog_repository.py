"""Чтение каталога закупок: список и карточка.

Отдельная реализация от поиска в llm-service: там задача — отобрать кандидатов
для модели, здесь — отдать пользователю страницу с точным счётчиком.
"""

from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import DocumentText, LlmVerdict, Tender, TenderDocument
from services.api.application.ports.catalog import TenderCatalogPort
from services.api.domain.models import (
    Page,
    TenderDetail,
    TenderDocumentInfo,
    TenderFilter,
)
from services.api.domain.pagination import PageRequest, encode_cursor
from services.api.infrastructure.db.queries import (
    conditions,
    cursor_of,
    keyset_condition,
    order_by,
    summary_columns,
    to_summary,
)


class SqlCatalogRepository(TenderCatalogPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list(self, filters: TenderFilter, page: PageRequest) -> Page:
        where = conditions(filters)
        statement = summary_columns().where(and_(*where)).order_by(*order_by(page.sort))

        if page.cursor is not None:
            statement = statement.where(keyset_condition(page.cursor))
        else:
            statement = statement.offset(page.offset)

        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(Tender).where(and_(*where))
            )
            # Берём на строку больше запрошенного: наличие «хвоста» — это и есть
            # ответ на вопрос, отдавать ли курсор дальше.
            rows = (await session.execute(statement.limit(page.limit + 1))).all()

        has_more = len(rows) > page.limit
        rows = rows[: page.limit]

        return Page(
            items=[to_summary(row) for row in rows],
            total=total or 0,
            page=page.page,
            page_size=page.limit,
            next_cursor=(
                encode_cursor(cursor_of(rows[-1], page.sort)) if has_more and rows else None
            ),
        )

    async def tender_id(self, reg_num: str) -> int | None:
        async with self._session_factory() as session:
            return await session.scalar(select(Tender.id).where(Tender.reg_num == reg_num))

    async def get(self, reg_num: str) -> TenderDetail | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(summary_columns().where(Tender.reg_num == reg_num))
            ).first()
            if row is None:
                return None

            document_rows = (
                await session.execute(
                    select(
                        TenderDocument.id,
                        TenderDocument.file_name,
                        TenderDocument.doc_kind_name,
                        TenderDocument.file_size,
                        TenderDocument.extraction_status,
                        TenderDocument.page_count,
                        TenderDocument.ocr_used,
                        DocumentText.char_count,
                    )
                    .outerjoin(DocumentText, DocumentText.document_id == TenderDocument.id)
                    .where(TenderDocument.tender_id == row.id)
                    .order_by(TenderDocument.id)
                )
            ).all()

            verdict_rows = (
                await session.execute(
                    select(
                        LlmVerdict.filter_id,
                        LlmVerdict.match,
                        LlmVerdict.score,
                        LlmVerdict.reasoning,
                        LlmVerdict.evidence,
                    ).where(LlmVerdict.tender_id == row.id)
                )
            ).all()

        return TenderDetail(
            summary=to_summary(row),
            documents=[
                TenderDocumentInfo(
                    document_id=d.id,
                    file_name=d.file_name,
                    doc_kind_name=d.doc_kind_name,
                    file_size=d.file_size,
                    extraction_status=d.extraction_status,
                    page_count=d.page_count,
                    ocr_used=d.ocr_used,
                    char_count=d.char_count,
                    has_text=d.char_count is not None and d.char_count > 0,
                )
                for d in document_rows
            ],
            verdicts=[
                {
                    "filter_id": v.filter_id,
                    "match": v.match,
                    "score": v.score,
                    "reasoning": v.reasoning,
                    "evidence": v.evidence,
                }
                for v in verdict_rows
            ],
        )

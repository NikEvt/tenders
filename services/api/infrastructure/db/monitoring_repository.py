"""Эксплуатационные проекции из общей БД.

Всё, что можно узнать из данных, читается из данных, а не опросом сервисов:
краулер и docs-worker HTTP не отдают, но следы их работы лежат в таблицах.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Outbox и таблица обработанных живут в models.py — они про транспорт,
# а не про предметную область.
from libs.shared.db.models import OutboxMessage, ProcessedMessage
from libs.shared.db.schema import (
    AppSetting,
    CrawlerRun,
    DocumentChunk,
    DocumentText,
    TenderDocument,
)
from libs.shared.messaging.topology import MAX_RETRY_ATTEMPTS
from services.api.application.ports.monitoring import (
    AppStatePort,
    CrawlerRunReadPort,
    DocumentPipelinePort,
    EventTrailPort,
)
from services.api.domain.monitoring import CrawlerRunView, PipelineFunnel, TenderEvent
from services.api.infrastructure.clients.rabbit_management import STAGE_LABELS

# Статусы, после которых файл считается скачанным.
DOWNLOADED_STATUSES = ("stored", "extracting", "done", "skipped")


class SqlCrawlerRunRepository(CrawlerRunReadPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def recent(self, limit: int) -> list[CrawlerRunView]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(CrawlerRun).order_by(CrawlerRun.started_at.desc()).limit(limit)
                )
            ).all()

        return [
            CrawlerRunView(
                run_id=row.id,
                target_date=row.target_date.isoformat() if row.target_date else None,
                status=row.status,
                fetched=row.fetched,
                saved=row.saved,
                error_code=row.error_code,
                error_message=row.error_message,
                raw=row.raw,
                started_at=row.started_at,
                finished_at=row.finished_at,
            )
            for row in rows
        ]


class SqlDocumentPipelineRepository(DocumentPipelinePort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def funnel(self) -> PipelineFunnel:
        async with self._session_factory() as session:
            by_status = dict(
                (
                    await session.execute(
                        select(TenderDocument.extraction_status, func.count()).group_by(
                            TenderDocument.extraction_status
                        )
                    )
                ).all()
            )
            ocr = await session.scalar(
                select(func.count()).select_from(TenderDocument).where(
                    TenderDocument.ocr_used.is_(True)
                )
            )
            extracted = await session.scalar(select(func.count()).select_from(DocumentText))
            chunked = await session.scalar(
                select(func.count(func.distinct(DocumentChunk.document_id)))
            )
            embedded = await session.scalar(
                select(func.count(func.distinct(DocumentChunk.document_id))).where(
                    DocumentChunk.embedding.is_not(None)
                )
            )

        downloaded = sum(by_status.get(status, 0) for status in DOWNLOADED_STATUSES)
        return PipelineFunnel(
            downloaded=downloaded,
            extracted=extracted or 0,
            ocr=ocr or 0,
            chunked=chunked or 0,
            embedded=embedded or 0,
            # Отказы показываются по этапам, а не одним числом: «не скачалось»
            # и «не распозналось» чинятся по-разному.
            failures=[
                (status, count)
                for status, count in sorted(by_status.items())
                if status in ("failed", "skipped")
            ],
        )


class SqlEventTrailRepository(EventTrailPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def for_tender(self, tender_id: int) -> list[TenderEvent]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        OutboxMessage.event_id,
                        OutboxMessage.routing_key,
                        OutboxMessage.created_at,
                        OutboxMessage.published_at,
                        OutboxMessage.attempts,
                        OutboxMessage.last_error,
                        func.count(ProcessedMessage.id).label("consumed_by"),
                    )
                    .outerjoin(
                        ProcessedMessage, ProcessedMessage.message_id == OutboxMessage.event_id
                    )
                    .where(OutboxMessage.payload["tender_id"].astext == str(tender_id))
                    .group_by(
                        OutboxMessage.event_id,
                        OutboxMessage.routing_key,
                        OutboxMessage.created_at,
                        OutboxMessage.published_at,
                        OutboxMessage.attempts,
                        OutboxMessage.last_error,
                    )
                    .order_by(OutboxMessage.created_at)
                )
            ).all()

        return [
            TenderEvent(
                message_id=row.event_id,
                event=row.routing_key,
                occurred_at=row.published_at or row.created_at,
                status=_status_of(row),
                attempt=row.attempts,
                retry_stage=_stage_of(row.attempts),
                error=row.last_error,
            )
            for row in rows
        ]


class SqlAppStateRepository(AppStatePort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, key: str) -> dict | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(AppSetting.value).where(AppSetting.key == key)
            )

    async def set(self, key: str, value: dict) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(AppSetting).values(key=key, value=value)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[AppSetting.key],
                    set_={"value": statement.excluded.value, "updated_at": func.now()},
                )
            )


def _status_of(row) -> str:
    """Состояние сообщения выводится, а не хранится.

    Отдельной колонки статуса нет, и заводить её ради экрана значило бы
    дублировать то, что уже следует из outbox и таблицы обработанных.
    """
    if row.consumed_by:
        return "consumed"
    if row.published_at is None:
        return "pending"
    if row.attempts >= MAX_RETRY_ATTEMPTS:
        return "dead"
    if row.attempts > 0:
        return "retry"
    return "published"


def _stage_of(attempts: int) -> str | None:
    if 0 < attempts <= len(STAGE_LABELS):
        return STAGE_LABELS[attempts - 1]
    return None

"""Чтение документов закупки: где лежит файл и что из него извлекли."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import DocumentChunk, DocumentText, TenderDocument
from services.api.application.ports.documents import DocumentReadPort
from services.api.domain.documents import ChunkOutline, TextLocation


class SqlDocumentRepository(DocumentReadPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def source(self, document_id: int) -> tuple[str, str | None] | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(TenderDocument.source_url, TenderDocument.file_name).where(
                        TenderDocument.id == document_id
                    )
                )
            ).first()
        if row is None or row.source_url is None:
            return None
        return row.source_url, row.file_name

    async def text_location(self, document_id: int) -> TextLocation | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(DocumentText.text_key, DocumentText.content).where(
                        DocumentText.document_id == document_id
                    )
                )
            ).first()
        if row is None:
            return None
        return TextLocation(key=row.text_key, inline=row.content)

    async def exists(self, document_id: int) -> bool:
        async with self._session_factory() as session:
            found = await session.scalar(
                select(TenderDocument.id).where(TenderDocument.id == document_id)
            )
        return found is not None

    async def chunks(self, document_id: int) -> list[ChunkOutline]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        DocumentChunk.id,
                        DocumentChunk.chunk_index,
                        DocumentChunk.char_start,
                        DocumentChunk.char_end,
                        DocumentChunk.page_from,
                    )
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            ).all()

        return [
            ChunkOutline(
                chunk_id=row.id,
                ordinal=row.chunk_index,
                char_start=row.char_start,
                char_end=row.char_end,
                page=row.page_from,
            )
            for row in rows
        ]

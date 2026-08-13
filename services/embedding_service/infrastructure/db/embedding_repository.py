"""Чтение текстов и запись векторов."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import DocumentChunk, Tender, TenderEmbedding
from services.embedding_service.application.ports import EmbeddingRepositoryPort
from services.embedding_service.domain.models import TenderCardText

# Сколько первых чанков документов идёт в карточку тендера. Первые страницы ТЗ
# описывают предмет закупки; дальше начинаются реквизиты и типовые условия.
CARD_CHUNK_LIMIT = 3
CARD_EXCERPT_CHARS = 3000


class SqlEmbeddingRepository(EmbeddingRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_tender_card(self, tender_id: int) -> TenderCardText | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        Tender.id,
                        Tender.name,
                        Tender.description,
                        Tender.okpd2_name,
                        Tender.okpd2_codes,
                    ).where(Tender.id == tender_id)
                )
            ).first()
            if row is None:
                return None

            excerpt_parts = (
                await session.scalars(
                    select(DocumentChunk.text)
                    .where(DocumentChunk.tender_id == tender_id)
                    .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
                    .limit(CARD_CHUNK_LIMIT)
                )
            ).all()

        excerpt = "\n".join(excerpt_parts)[:CARD_EXCERPT_CHARS] if excerpt_parts else None
        names = [row.okpd2_name] if row.okpd2_name else []
        return TenderCardText(
            tender_id=row.id,
            name=row.name,
            description=row.description,
            okpd2_names=names,
            document_excerpt=excerpt,
        )

    async def load_chunks(self, chunk_ids: Sequence[int]) -> list[tuple[int, str]]:
        if not chunk_ids:
            return []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(DocumentChunk.id, DocumentChunk.text).where(
                        DocumentChunk.id.in_(list(chunk_ids)),
                        # Уже посчитанные пропускаем: событие может прийти повторно.
                        DocumentChunk.embedding.is_(None),
                    )
                )
            ).all()
        return [(row.id, row.text) for row in rows]

    async def save_tender_embedding(
        self, tender_id: int, vector: Sequence[float], model: str, source_hash: str
    ) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(TenderEmbedding).values(
                tender_id=tender_id,
                embedding=list(vector),
                model=model,
                source_text_hash=source_hash,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[TenderEmbedding.tender_id],
                    set_={
                        "embedding": statement.excluded.embedding,
                        "model": statement.excluded.model,
                        "source_text_hash": statement.excluded.source_text_hash,
                        "updated_at": func.now(),
                    },
                )
            )

    async def save_chunk_embeddings(
        self, vectors: Sequence[tuple[int, Sequence[float]]]
    ) -> None:
        if not vectors:
            return
        async with self._session_factory() as session, session.begin():
            for chunk_id, vector in vectors:
                await session.execute(
                    update(DocumentChunk)
                    .where(DocumentChunk.id == chunk_id)
                    .values(embedding=list(vector))
                )

    async def tender_embedding_hash(self, tender_id: int) -> str | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(TenderEmbedding.source_text_hash).where(
                    TenderEmbedding.tender_id == tender_id
                )
            )

    async def pending_chunk_ids(self, tender_id: int, limit: int) -> list[int]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(DocumentChunk.id)
                    .where(
                        DocumentChunk.tender_id == tender_id,
                        DocumentChunk.embedding.is_(None),
                    )
                    .order_by(DocumentChunk.id)
                    .limit(limit)
                )
            ).all()
        return list(rows)

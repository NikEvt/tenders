"""Построение и сохранение эмбеддингов."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import pytest
from sqlalchemy import delete, select

from libs.shared.contracts.events import DocumentExtracted
from libs.shared.contracts.ports import EmbedderPort
from libs.shared.db.schema import (
    DocumentChunk,
    Tender,
    TenderDocument,
    TenderEmbedding,
)
from services.embedding_service.application.use_cases.build_embeddings import (
    EmbedChunksUseCase,
    EmbedTenderCardUseCase,
    HandleEmbeddingEventsUseCase,
)
from services.embedding_service.infrastructure.db.embedding_repository import (
    SqlEmbeddingRepository,
)

DIM = 1024
MODEL = "test-embedder"
REG_NUM = "TEST-EMB-0000000001"


class CountingEmbedder(EmbedderPort):
    """Детерминированный вектор из хеша текста + счётчик вызовов."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    @property
    def dim(self) -> int:
        return DIM

    async def embed(self, texts: Sequence[str], is_query: bool = False) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            base = [b / 255.0 for b in digest]
            vector = (base * (DIM // len(base) + 1))[:DIM]
            # Нормализация — индексы построены под косинусную метрику.
            norm = sum(v * v for v in vector) ** 0.5 or 1.0
            vectors.append([v / norm for v in vector])
        return vectors


@pytest.fixture
async def tender_fixture(session_factory):
    created: list[int] = []

    async def create(chunks: list[str] | None = None) -> tuple[int, list[int]]:
        async with session_factory() as session, session.begin():
            tender_id = await session.scalar(
                Tender.__table__.insert()
                .values(
                    reg_num=REG_NUM,
                    name="Поставка кислорода",
                    description="Поставка кислорода технического в баллонах",
                    okpd2_name="Газы промышленные",
                )
                .returning(Tender.id)
            )
            chunk_ids: list[int] = []
            if chunks:
                document_id = await session.scalar(
                    TenderDocument.__table__.insert()
                    .values(tender_id=tender_id, attachment_id="A", file_name="ТЗ.txt")
                    .returning(TenderDocument.id)
                )
                for index, text in enumerate(chunks):
                    chunk_id = await session.scalar(
                        DocumentChunk.__table__.insert()
                        .values(
                            document_id=document_id,
                            tender_id=tender_id,
                            chunk_index=index,
                            text=text,
                        )
                        .returning(DocumentChunk.id)
                    )
                    chunk_ids.append(chunk_id)
        created.append(tender_id)
        return tender_id, chunk_ids

    yield create

    async with session_factory() as session, session.begin():
        for tender_id in created:
            await session.execute(delete(Tender).where(Tender.id == tender_id))


@pytest.mark.asyncio
async def test_tender_card_embedding_is_saved(session_factory, tender_fixture) -> None:
    tender_id, _ = await tender_fixture()
    embedder = CountingEmbedder()
    repository = SqlEmbeddingRepository(session_factory)

    assert await EmbedTenderCardUseCase(repository, embedder, MODEL).execute(tender_id)

    async with session_factory() as session:
        row = await session.scalar(
            select(TenderEmbedding).where(TenderEmbedding.tender_id == tender_id)
        )
        assert row is not None
        assert len(row.embedding) == DIM
        assert row.model == MODEL
        assert row.source_text_hash

    # В карточку идут название, описание и ОКПД2 — по одному названию тендеры
    # вроде «Поставка товаров» неотличимы.
    card_text = embedder.calls[0][0]
    assert "Поставка кислорода" in card_text
    assert "Газы промышленные" in card_text


@pytest.mark.asyncio
async def test_unchanged_text_does_not_recompute(session_factory, tender_fixture) -> None:
    """Краулер перезаписывает извещение ежечасно — модель гонять на том же тексте незачем."""
    tender_id, _ = await tender_fixture()
    embedder = CountingEmbedder()
    use_case = EmbedTenderCardUseCase(SqlEmbeddingRepository(session_factory), embedder, MODEL)

    assert await use_case.execute(tender_id) is True
    assert await use_case.execute(tender_id) is False
    assert len(embedder.calls) == 1


@pytest.mark.asyncio
async def test_changed_text_recomputes(session_factory, tender_fixture) -> None:
    tender_id, _ = await tender_fixture()
    embedder = CountingEmbedder()
    use_case = EmbedTenderCardUseCase(SqlEmbeddingRepository(session_factory), embedder, MODEL)

    await use_case.execute(tender_id)
    async with session_factory() as session, session.begin():
        await session.execute(
            Tender.__table__.update()
            .where(Tender.id == tender_id)
            .values(description="Изменившееся описание закупки")
        )

    assert await use_case.execute(tender_id) is True
    assert len(embedder.calls) == 2


@pytest.mark.asyncio
async def test_chunk_embeddings_are_saved_in_batches(session_factory, tender_fixture) -> None:
    texts = [f"Пункт технического задания номер {i}." for i in range(5)]
    _, chunk_ids = await tender_fixture(texts)

    embedder = CountingEmbedder()
    saved = await EmbedChunksUseCase(
        SqlEmbeddingRepository(session_factory), embedder, batch_size=2
    ).execute(chunk_ids)

    assert saved == 5
    assert [len(call) for call in embedder.calls] == [2, 2, 1]

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(DocumentChunk.embedding).where(DocumentChunk.id.in_(chunk_ids))
            )
        ).all()
        assert all(row is not None and len(row) == DIM for row in rows)


@pytest.mark.asyncio
async def test_already_embedded_chunks_are_skipped(session_factory, tender_fixture) -> None:
    _, chunk_ids = await tender_fixture(["Первый пункт.", "Второй пункт."])
    repository = SqlEmbeddingRepository(session_factory)
    embedder = CountingEmbedder()
    use_case = EmbedChunksUseCase(repository, embedder)

    assert await use_case.execute(chunk_ids) == 2
    # Повторная доставка события — штатный режим RabbitMQ.
    assert await use_case.execute(chunk_ids) == 0
    assert len(embedder.calls) == 1


@pytest.mark.asyncio
async def test_document_extracted_updates_chunks_and_card(
    session_factory, tender_fixture
) -> None:
    tender_id, chunk_ids = await tender_fixture(["Поставка кислорода в баллонах 40 л."])
    repository = SqlEmbeddingRepository(session_factory)
    embedder = CountingEmbedder()

    handler = HandleEmbeddingEventsUseCase(
        repository=repository,
        tender_use_case=EmbedTenderCardUseCase(repository, embedder, MODEL),
        chunks_use_case=EmbedChunksUseCase(repository, embedder),
    )

    await handler.on_document_extracted(
        DocumentExtracted(document_id=1, tender_id=tender_id, chunk_ids=chunk_ids)
    )

    async with session_factory() as session:
        card = await session.scalar(
            select(TenderEmbedding).where(TenderEmbedding.tender_id == tender_id)
        )
        chunk = await session.scalar(
            select(DocumentChunk.embedding).where(DocumentChunk.id == chunk_ids[0])
        )

    assert card is not None
    assert chunk is not None
    # Карточка включает выдержку из документов — текст чанка должен туда попасть.
    assert any("40 л" in text for call in embedder.calls for text in call)

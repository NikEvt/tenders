"""Composition root сервиса эмбеддингов."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aio_pika.abc import AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from libs.shared.config import DatabaseSettings, EmbeddingSettings, RabbitSettings
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.messaging.outbox import SqlIdempotencyStore
from libs.shared.messaging.topology import connect
from services.embedding_service.application.use_cases.build_embeddings import (
    EmbedChunksUseCase,
    EmbedTenderCardUseCase,
    HandleEmbeddingEventsUseCase,
)
from services.embedding_service.infrastructure.db.embedding_repository import (
    SqlEmbeddingRepository,
)
from services.embedding_service.infrastructure.model.bge_embedder import (
    SentenceTransformerEmbedder,
)


@dataclass
class EmbeddingContainer:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    connection: AbstractRobustConnection
    idempotency: SqlIdempotencyStore
    embedder: SentenceTransformerEmbedder
    handler: HandleEmbeddingEventsUseCase


@asynccontextmanager
async def build_container(
    db: DatabaseSettings,
    rabbit: RabbitSettings,
    embedding: EmbeddingSettings,
) -> AsyncIterator[EmbeddingContainer]:
    engine = create_engine(db.async_dsn)
    session_factory = create_session_factory(engine)
    connection = await connect(rabbit.dsn)

    embedder = SentenceTransformerEmbedder(
        embedding.model, embedding.dim, device=embedding.device
    )
    # Загрузка весов занимает десятки секунд и блокирует поток — в отдельный тред,
    # иначе uvicorn не успевает ответить на health-check при старте.
    await asyncio.to_thread(embedder.load)

    repository = SqlEmbeddingRepository(session_factory)
    handler = HandleEmbeddingEventsUseCase(
        repository=repository,
        tender_use_case=EmbedTenderCardUseCase(repository, embedder, embedding.model),
        chunks_use_case=EmbedChunksUseCase(repository, embedder),
    )

    container = EmbeddingContainer(
        engine=engine,
        session_factory=session_factory,
        connection=connection,
        idempotency=SqlIdempotencyStore(session_factory),
        embedder=embedder,
        handler=handler,
    )

    try:
        yield container
    finally:
        await connection.close()
        await engine.dispose()

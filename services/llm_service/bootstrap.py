"""Composition root LLM-сервиса."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aio_pika.abc import AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from libs.shared.clients.embedding_client import HttpEmbedder
from libs.shared.config import (
    DatabaseSettings,
    EmbeddingSettings,
    LlmSettings,
    RabbitSettings,
)
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.messaging.outbox import SqlIdempotencyStore
from libs.shared.messaging.topology import connect
from services.llm_service.application.use_cases.compile_filter import CompileFilterUseCase
from services.llm_service.application.use_cases.generate_digest import GenerateDigestUseCase
from services.llm_service.application.use_cases.manage_filters import ManageFiltersUseCase
from services.llm_service.infrastructure.db.repositories import (
    SqlDigestRepository,
    SqlFilterRepository,
    SqlJobTracker,
)
from services.llm_service.infrastructure.llm.openai_client import OpenAiCompatibleLlm


@dataclass
class LlmContainer:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    connection: AbstractRobustConnection
    idempotency: SqlIdempotencyStore
    embedder: HttpEmbedder
    compile_filter: CompileFilterUseCase
    manage_filters: ManageFiltersUseCase
    generate_digest: GenerateDigestUseCase
    filters: SqlFilterRepository
    digests: SqlDigestRepository
    jobs: SqlJobTracker
    #: Модель напрямую: по ней работает `/judge`, которым пользуется движок
    #: отбора. Отбор кандидатов и вердикты живут теперь там, а здесь остаётся
    #: то, ради чего сервис и заводился, — доступ к модели.
    llm: OpenAiCompatibleLlm
    judge_reasoning_effort: str
    model_name: str


@asynccontextmanager
async def build_container(
    db: DatabaseSettings,
    rabbit: RabbitSettings,
    llm_settings: LlmSettings,
    embedding: EmbeddingSettings,
) -> AsyncIterator[LlmContainer]:
    engine = create_engine(db.async_dsn)
    session_factory = create_session_factory(engine)
    connection = await connect(rabbit.dsn)

    llm = OpenAiCompatibleLlm(llm_settings)
    # Эмбеддинги берём по HTTP: torch в образ llm-сервиса не тянется.
    embedder = HttpEmbedder(embedding.service_url, embedding.dim)

    filters = SqlFilterRepository(session_factory)
    digests = SqlDigestRepository(session_factory)
    jobs = SqlJobTracker(session_factory)
    container = LlmContainer(
        engine=engine,
        session_factory=session_factory,
        connection=connection,
        idempotency=SqlIdempotencyStore(session_factory),
        embedder=embedder,
        compile_filter=CompileFilterUseCase(llm, filters),
        manage_filters=ManageFiltersUseCase(filters),
        generate_digest=GenerateDigestUseCase(llm, digests, jobs),
        llm=llm,
        judge_reasoning_effort=llm_settings.judge_reasoning_effort,
        filters=filters,
        digests=digests,
        jobs=jobs,
        model_name=llm.model_name,
    )

    try:
        yield container
    finally:
        await embedder.aclose()
        await connection.close()
        await engine.dispose()

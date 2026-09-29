"""Composition root движка отбора."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aio_pika.abc import AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from libs.shared.config import (
    DatabaseSettings,
    LlmSettings,
    MinioSettings,
    RabbitSettings,
)
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.load_control import LoadController
from libs.shared.load_store import LoadLevelWatcher, SqlLoadLevelStore
from libs.shared.messaging.outbox import SqlIdempotencyStore
from libs.shared.messaging.topology import connect
from services.research.application.ports import TextStoragePort
from services.research.infrastructure.jobs import SqlJobTracker
from services.research.infrastructure.llm_judge import HttpModelJudge
from services.research.infrastructure.repositories import (
    SqlCorpusRepository,
    SqlCriteriaRepository,
    SqlHitRepository,
    SqlResearchRunRepository,
    SqlVerdictStore,
)
from services.research.infrastructure.storage import MinioTextStorage


@dataclass
class ResearchContainer:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    connection: AbstractRobustConnection
    idempotency: SqlIdempotencyStore

    corpus: SqlCorpusRepository
    criteria: SqlCriteriaRepository
    hits: SqlHitRepository
    runs: SqlResearchRunRepository
    verdicts: SqlVerdictStore
    jobs: SqlJobTracker
    texts: TextStoragePort
    judge: HttpModelJudge

    controller: LoadController
    load_watcher: LoadLevelWatcher


@asynccontextmanager
async def build_container(
    db: DatabaseSettings,
    rabbit: RabbitSettings,
    minio: MinioSettings,
    llm: LlmSettings,
    llm_service_url: str,
) -> AsyncIterator[ResearchContainer]:
    engine = create_engine(db.async_dsn)
    session_factory = create_session_factory(engine)
    connection = await connect(rabbit.dsn)

    controller = LoadController()

    container = ResearchContainer(
        engine=engine,
        session_factory=session_factory,
        connection=connection,
        idempotency=SqlIdempotencyStore(session_factory),
        corpus=SqlCorpusRepository(session_factory),
        criteria=SqlCriteriaRepository(session_factory),
        hits=SqlHitRepository(session_factory),
        runs=SqlResearchRunRepository(session_factory),
        verdicts=SqlVerdictStore(session_factory),
        jobs=SqlJobTracker(session_factory),
        texts=MinioTextStorage(minio),
        # Своего клиента к модели у движка нет: ключи и структурный вывод —
        # забота llm-service, дублировать их незачем.
        judge=HttpModelJudge(llm_service_url, model_name=llm.model),
        controller=controller,
        load_watcher=LoadLevelWatcher(SqlLoadLevelStore(session_factory), controller),
    )

    try:
        yield container
    finally:
        container.load_watcher.stop()
        await connection.close()
        await engine.dispose()


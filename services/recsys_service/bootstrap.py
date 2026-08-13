"""Composition root рекомендательного сервиса."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aio_pika.abc import AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from libs.shared.config import DatabaseSettings, RabbitSettings
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.messaging.outbox import SqlIdempotencyStore
from libs.shared.messaging.publisher import RabbitPublisher
from libs.shared.messaging.topology import connect
from services.recsys_service.application.use_cases.build_profile import RebuildProfileUseCase
from services.recsys_service.application.use_cases.recommend import RecommendUseCase
from services.recsys_service.infrastructure.db.repositories import (
    SqlProfileRepository,
    SqlRecommendationRepository,
)
from services.recsys_service.infrastructure.ranking.linear_ranker import LinearRanker


@dataclass
class RecsysContainer:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    connection: AbstractRobustConnection
    idempotency: SqlIdempotencyStore
    publisher: RabbitPublisher
    profiles: SqlProfileRepository
    recommendations: SqlRecommendationRepository
    rebuild_profile: RebuildProfileUseCase
    recommend: RecommendUseCase


@asynccontextmanager
async def build_container(
    db: DatabaseSettings, rabbit: RabbitSettings
) -> AsyncIterator[RecsysContainer]:
    engine = create_engine(db.async_dsn)
    session_factory = create_session_factory(engine)
    connection = await connect(rabbit.dsn)

    publisher = RabbitPublisher(connection)
    await publisher.setup()

    profiles = SqlProfileRepository(session_factory)
    recommendations = SqlRecommendationRepository(session_factory)

    container = RecsysContainer(
        engine=engine,
        session_factory=session_factory,
        connection=connection,
        idempotency=SqlIdempotencyStore(session_factory),
        publisher=publisher,
        profiles=profiles,
        recommendations=recommendations,
        rebuild_profile=RebuildProfileUseCase(profiles),
        # Ранкер подставляется здесь: замена линейной формулы на обученную модель
        # не потребует правок в use-case (OCP).
        recommend=RecommendUseCase(profiles, recommendations, LinearRanker()),
    )

    try:
        yield container
    finally:
        await connection.close()
        await engine.dispose()

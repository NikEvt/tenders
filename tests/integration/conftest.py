"""Интеграционные тесты идут против настоящего Postgres из docker compose.

Схема на pgvector, генерируемые столбцы, `ON CONFLICT ... RETURNING xmax = 0` —
всё это на sqlite не воспроизводится, поэтому подменять БД смысла нет.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.config import database_settings
from libs.shared.db.base import create_engine, create_session_factory


@pytest.fixture(scope="session")
def dsn() -> str:
    return database_settings().async_dsn


@pytest_asyncio.fixture(scope="session")
async def engine(dsn: str):
    engine = create_engine(dsn)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - зависит от окружения
        await engine.dispose()
        pytest.skip(f"Postgres недоступен ({exc}); подними его: docker compose up -d postgres")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """Сессия во внешней транзакции, которая откатывается после теста.

    Тесты не оставляют следов в базе и могут идти в любом порядке.
    """
    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False)

    async with factory() as session:
        yield session

    await transaction.rollback()
    await connection.close()

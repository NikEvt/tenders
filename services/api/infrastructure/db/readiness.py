"""Проверка готовности БД.

Отдельный порт нужен, чтобы `/health/ready` не тащил SQLAlchemy в presentation:
знание о том, чем именно проверяется живость базы, остаётся в инфраструктуре.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.application.ports.health import ReadinessPort


class SqlReadinessProbe(ReadinessPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def check(self) -> None:
        async with self._session_factory() as session:
            await session.execute(text("SELECT 1"))

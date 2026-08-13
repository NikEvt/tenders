"""Чтение статуса длительных заданий, запущенных через шлюз."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import Job
from services.api.application.ports.jobs import JobReadPort


class SqlJobRepository(JobReadPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, job_id: str) -> dict | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(Job).where(Job.id == job_id))
        if row is None:
            return None
        return {
            "job_id": row.id,
            "kind": row.kind,
            "status": row.status,
            "total": row.total,
            "processed": row.processed,
            "result": row.result,
            "error": row.error_message,
            "updated_at": row.updated_at.isoformat(),
        }

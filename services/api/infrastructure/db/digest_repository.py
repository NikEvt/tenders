"""Чтение ежедневных сводок."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.day_completeness import is_closed
from libs.shared.db.schema import DailyDigest
from services.api.application.ports.digest import DigestReadPort


class SqlDigestRepository(DigestReadPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, digest_date: date) -> dict | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(DailyDigest).where(DailyDigest.digest_date == digest_date)
            )
        if row is None:
            return None
        return {
            "digest_date": row.digest_date.isoformat(),
            "summary_md": row.summary_md,
            "sections": row.sections,
            "tender_count": row.tender_count,
            "model": row.model,
            "generated_at": row.generated_at.isoformat(),
            # Собрана ли она после окончания своего дня. Черновик за идущий
            # день описывает столько, сколько успело доехать, и выдавать его за
            # итог нельзя: сводка за 13 августа так и осталась с 400 закупками
            # из 4878, потому что этой разницы никто не различал.
            "final": is_closed(row.digest_date, row.generated_at.date()),
        }

    async def dates(self, since: date, until: date) -> list[date]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(DailyDigest.digest_date)
                .where(DailyDigest.digest_date >= since, DailyDigest.digest_date <= until)
                .order_by(DailyDigest.digest_date)
            )
        return list(rows.all())

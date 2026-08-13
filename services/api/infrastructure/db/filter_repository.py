"""Чтение сохранённых фильтров вместе со статистикой совпадений.

Читается напрямую из общей БД, а не через llm-service: это проекция для экрана,
а не бизнес-операция, и лишний сетевой хоп в сервис с таймаутом в четыре минуты
ради отрисовки списка неоправдан.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import LlmVerdict, SavedFilter
from services.api.application.ports.filters import FilterReadPort
from services.api.domain.filters import MatchCount, SavedFilterCard


class SqlFilterReadRepository(FilterReadPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list(self, history_days: int) -> list[SavedFilterCard]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(SavedFilter).order_by(SavedFilter.created_at.desc())
                )
            ).all()
            # Один запрос на все фильтры разом, а не по запросу на карточку.
            counts = await self._match_counts(session, history_days, None)

        return [_to_card(row, counts.get(row.id, [])) for row in rows]

    async def get(self, filter_id: int, history_days: int) -> SavedFilterCard | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(SavedFilter).where(SavedFilter.id == filter_id))
            if row is None:
                return None
            counts = await self._match_counts(session, history_days, filter_id)

        return _to_card(row, counts.get(filter_id, []))

    @staticmethod
    async def _match_counts(
        session: AsyncSession, history_days: int, filter_id: int | None
    ) -> dict[int, list[MatchCount]]:
        """Сколько совпадений дал фильтр по дням — материал для спарклайна.

        Считаются только положительные вердикты: отрицательные говорят о работе
        судьи, а не о находках, и в спарклайне вводили бы в заблуждение.
        """
        since = date.today() - timedelta(days=history_days - 1)
        day = func.date(LlmVerdict.created_at).label("day")

        statement = (
            select(LlmVerdict.filter_id, day, func.count().label("count"))
            .where(LlmVerdict.match.is_(True), func.date(LlmVerdict.created_at) >= since)
            .group_by(LlmVerdict.filter_id, day)
            .order_by(day)
        )
        if filter_id is not None:
            statement = statement.where(LlmVerdict.filter_id == filter_id)

        result: dict[int, list[MatchCount]] = {}
        for row in (await session.execute(statement)).all():
            result.setdefault(row.filter_id, []).append(
                MatchCount(day=row.day, count=row.count)
            )
        return result


def _to_card(row: SavedFilter, counts: list[MatchCount]) -> SavedFilterCard:
    return SavedFilterCard(
        filter_id=row.id,
        name=row.name,
        query=row.nl_query or "",
        spec=row.spec or {},
        in_digest=row.in_digest,
        notify=row.notify,
        is_active=row.is_active,
        created_at=row.created_at,
        last_run_at=row.last_run_at,
        match_counts=counts,
    )

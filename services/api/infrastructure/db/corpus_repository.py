"""Состав корпуса: разрезы по датам, регионам и ОКПД2 плюс ход обогащения.

Всё считается за один период — тот, что просили. Групповой запрос по всей
`tenders` без ограничения по датам стоит дороже и описывает не то множество,
которое видно на экране.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Row, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.sqltypes import Date as SqlDate

from libs.shared.db.schema import CrawlerRun, DocumentChunk, Tender, TenderEmbedding
from libs.shared.regions import region_name
from services.api.application.ports.corpus import CorpusStatsPort
from services.api.domain.corpus import (
    CorpusOverview,
    DayBucket,
    Distribution,
    EmbeddingProgress,
    Slice,
    TodayIngest,
)


class SqlCorpusRepository(CorpusStatsPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def overview(self, since: date, until: date, limit: int) -> CorpusOverview:
        window = _window(since, until)

        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(Tender).where(*window)
            )
            total_all_time = await session.scalar(select(func.count()).select_from(Tender))
            bounds = (
                await session.execute(
                    select(
                        func.min(cast(Tender.publish_date, SqlDate)),
                        func.max(cast(Tender.publish_date, SqlDate)),
                    )
                )
            ).first()

            by_day = (
                await session.execute(
                    select(
                        cast(Tender.publish_date, SqlDate).label("day"),
                        func.count().label("tenders"),
                    )
                    .where(*window)
                    .group_by("day")
                )
            ).all()

            crawled = {
                day
                for day in (
                    await session.scalars(
                        select(CrawlerRun.target_date).where(
                            CrawlerRun.status == "success",
                            CrawlerRun.target_date.is_not(None),
                            CrawlerRun.target_date >= since,
                            CrawlerRun.target_date <= until,
                        )
                    )
                ).all()
                if day is not None
            }

            regions = await self._distribution(
                session, window, Tender.region_code, limit, total or 0
            )
            okpd2 = await self._distribution(
                session, window, Tender.okpd2_code, limit, total or 0, label=Tender.okpd2_name
            )

        for row in regions.top:
            row.label = region_name(row.key)

        return CorpusOverview(
            since=since,
            until=until,
            total=total or 0,
            total_all_time=total_all_time or 0,
            earliest=bounds[0] if bounds else None,
            latest=bounds[1] if bounds else None,
            by_day=_days(since, until, {row.day: row.tenders for row in by_day}, crawled),
            by_region=regions,
            by_okpd2=okpd2,
        )

    async def embeddings(self) -> EmbeddingProgress:
        async with self._session_factory() as session:
            chunks_total = await session.scalar(select(func.count()).select_from(DocumentChunk))
            chunks_embedded = await session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.embedding.is_not(None))
            )
            tenders_total = await session.scalar(select(func.count()).select_from(Tender))
            tenders_embedded = await session.scalar(
                select(func.count()).select_from(TenderEmbedding)
            )

        return EmbeddingProgress(
            chunks_total=chunks_total or 0,
            chunks_embedded=chunks_embedded or 0,
            tenders_total=tenders_total or 0,
            tenders_embedded=tenders_embedded or 0,
        )

    async def today(self, day: date) -> TodayIngest:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        CrawlerRun.status,
                        func.count().label("runs"),
                        func.coalesce(func.sum(CrawlerRun.saved), 0).label("saved"),
                        func.max(CrawlerRun.started_at).label("last_run_at"),
                    )
                    .where(CrawlerRun.target_date == day)
                    .group_by(CrawlerRun.status)
                )
            ).all()

            published = await session.scalar(
                select(func.count()).select_from(Tender).where(*_window(day, day))
            )

        by_status = {row.status: row for row in rows}
        return TodayIngest(
            day=day,
            runs_succeeded=_runs(by_status, "success"),
            runs_failed=_runs(by_status, "failed"),
            runs_running=_runs(by_status, "running"),
            saved=sum(int(row.saved or 0) for row in rows),
            published_today=published or 0,
            last_run_at=max((row.last_run_at for row in rows if row.last_run_at), default=None),
        )

    async def _distribution(
        self,
        session: AsyncSession,
        window: list[ColumnElement[bool]],
        column: InstrumentedAttribute[str | None],
        limit: int,
        total: int,
        label: InstrumentedAttribute[str | None] | None = None,
    ) -> Distribution:
        """Верхушка разреза плюс хвост.

        Хвост считается вычитанием, а не вторым групповым запросом: сумма
        показанного плюс «остальные» плюс «без признака» обязана в точности
        равняться итогу, а два независимых запроса на живой базе такого
        обещания не дают.
        """
        label_column = (label if label is not None else column).label("label")
        rows = (
            await session.execute(
                select(column.label("key"), func.min(label_column), func.count().label("hits"))
                .where(*window, column.is_not(None))
                .group_by(column)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
        known = await session.scalar(
            select(func.count()).select_from(Tender).where(*window, column.is_not(None))
        )

        top = [Slice(key=row.key, label=row[1] or row.key, count=row.hits) for row in rows]
        return Distribution(
            top=top,
            others=max(0, (known or 0) - sum(item.count for item in top)),
            total=total,
            unknown=max(0, total - (known or 0)),
        )


def _window(since: date, until: date) -> list[ColumnElement[bool]]:
    """Условие «опубликовано в этом периоде».

    Полуинтервал по `timestamptz`, а не `cast(publish_date as date)`: приведение
    в предикате отключило бы `tenders_publish_date_idx`, а именно им этот запрос
    и держится.
    """
    return [
        Tender.publish_date >= datetime.combine(since, time.min),
        Tender.publish_date < datetime.combine(until + timedelta(days=1), time.min),
    ]


def _days(
    since: date, until: date, counts: dict[date, int], crawled: set[date]
) -> list[DayBucket]:
    """Ряд без пропусков.

    День, за который выгрузки не было, обязан отличаться от дня, в который
    ничего не публиковали: первое — дыра в наших данных, второе — факт о рынке.
    Выбросить его из ряда значило бы выдать первое за второе.
    """
    out: list[DayBucket] = []
    day = since
    while day <= until:
        out.append(DayBucket(day=day, count=counts.get(day, 0), crawled=day in crawled))
        day += timedelta(days=1)
    return out


def _runs(by_status: dict[str, Row[Any]], status: str) -> int:
    row = by_status.get(status)
    return int(row.runs) if row else 0

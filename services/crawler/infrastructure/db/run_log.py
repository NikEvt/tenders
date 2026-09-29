"""Журнал запусков краулера (`crawler_runs`)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import CrawlerRun
from services.crawler.application.ports import CrawlRunLogPort
from services.crawler.domain.coverage import is_final
from services.crawler.domain.models import CrawlRequest, CrawlResult


class SqlCrawlRunLog(CrawlRunLogPort):
    """Пишет запуски отдельными транзакциями.

    Намеренно не участвует в транзакции выгрузки: запись о провалившемся запуске
    должна пережить откат этой транзакции, иначе журнал покажет тишину вместо ошибки.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start(self, request: CrawlRequest) -> int:
        async with self._session_factory() as session, session.begin():
            run_id = await session.scalar(
                pg_insert(CrawlerRun)
                .values(
                    source="eis-soap",
                    region=request.region,
                    document_type=request.document_type,
                    target_date=request.target_date,
                    status="running",
                )
                .returning(CrawlerRun.id)
            )
        assert run_id is not None
        return run_id

    async def completed(self, since: date, until: date) -> set[tuple[str, str, date]]:
        """Что уже выгружено успешно **и окончательно** за период.

        Два условия, и оба обязательны.

        `status = 'success'`: провалившийся день обязан быть повторён, иначе
        дыра в покрытии станет постоянной и незаметной.

        `is_final`: успех сам по себе не означает полноту — суточный архив ЕИС
        дописывается до конца суток. Правило формулирует домен, здесь оно
        только применяется. Фильтр идёт по загруженным строкам, а не условием
        в SQL: так формулировка остаётся одна, а строк тут в худшем случае
        период × регионы, то есть тысячи.
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        CrawlerRun.region,
                        CrawlerRun.document_type,
                        CrawlerRun.target_date,
                        CrawlerRun.started_at,
                    )
                    .where(
                        CrawlerRun.status == "success",
                        CrawlerRun.target_date.is_not(None),
                        CrawlerRun.target_date >= since,
                        CrawlerRun.target_date <= until,
                    )
                    .distinct()
                )
            ).all()

        return {
            (row.region, row.document_type, row.target_date)
            for row in rows
            if row.region and row.document_type
            if is_final(row.target_date, row.started_at.date())
        }

    async def finish(self, run_id: int, result: CrawlResult) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(CrawlerRun)
                .where(CrawlerRun.id == run_id)
                .values(
                    finished_at=func.now(),
                    fetched=result.fetched,
                    saved=result.saved,
                    errors=result.errors,
                    status=result.status,
                    error_message=result.error_message,
                )
            )

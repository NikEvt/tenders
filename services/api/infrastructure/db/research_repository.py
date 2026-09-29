"""Чтение прогонов, находок и рыночных разрезов."""

from __future__ import annotations

from decimal import Decimal
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import (
    ResearchHit,
    ResearchRun,
    ResearchVerdict,
    Tender,
)
from libs.shared.regions import region_name
from services.api.application.ports.research import ResearchReadPort
from services.api.domain.research import (
    MarketBucket,
    MarketView,
    ResearchFunnel,
    ResearchHitView,
    ResearchRunCard,
    ResearchTenderRow,
)

#: Больше пяти цитат на закупку экран не показывает — и движок больше не пишет.
HITS_PER_TENDER = 5

#: Верхушка для доли: сколько самых дорогих закупок дают какую часть суммы.
TOP_N = 3

class SqlResearchRepository(ResearchReadPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def runs(self, limit: int) -> list[ResearchRunCard]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(ResearchRun).order_by(ResearchRun.started_at.desc()).limit(limit)
                )
            ).all()
        return [_to_card(row) for row in rows]

    async def run(self, run_id: int) -> ResearchRunCard | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))
        return _to_card(row) if row is not None else None

    async def tenders(
        self, run_id: int, confidence: str | None, limit: int, offset: int
    ) -> tuple[list[ResearchTenderRow], int]:
        async with self._session_factory() as session:
            version = await session.scalar(
                select(ResearchRun.criteria_version).where(ResearchRun.id == run_id)
            )
            if version is None:
                return [], 0

            # Закупки прогона — те, по которым есть находки. Вердикт
            # присоединяется по версии критериев: решение принадлежит паре
            # «закупка + критерий», а не запуску.
            base = (
                select(
                    Tender.id,
                    Tender.reg_num,
                    Tender.name,
                    Tender.price,
                    Tender.region_code,
                    Tender.customer_name,
                    Tender.customer_inn,
                    Tender.okpd2_code,
                    ResearchVerdict.confidence,
                    ResearchVerdict.reason,
                    ResearchVerdict.decided_by,
                    ResearchVerdict.score,
                )
                .join(ResearchHit, ResearchHit.tender_id == Tender.id)
                .outerjoin(
                    ResearchVerdict,
                    (ResearchVerdict.tender_id == Tender.id)
                    & (ResearchVerdict.criteria_version == version),
                )
                .where(ResearchHit.run_id == run_id)
                .distinct()
            )
            if confidence:
                base = base.where(ResearchVerdict.confidence == confidence)

            total = await session.scalar(
                select(func.count()).select_from(base.subquery())
            )
            rows = (
                await session.execute(
                    base.order_by(Tender.price.desc().nullslast(), Tender.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()

            hits = await self._hits(session, run_id, [row.id for row in rows])

        return [
            ResearchTenderRow(
                tender_id=row.id,
                reg_num=row.reg_num,
                name=row.name,
                price=row.price,
                region_code=row.region_code,
                customer_name=row.customer_name,
                customer_inn=row.customer_inn,
                okpd2_code=row.okpd2_code,
                # Вердикта может не быть: прогон оборвался, до закупки не дошли.
                # Врать «отклонено» нельзя — это разные состояния.
                confidence=row.confidence or "disputed",
                reason=row.reason,
                decided_by=row.decided_by or "rules",
                score=row.score or 0.0,
                hits=hits.get(row.id, []),
            )
            for row in rows
        ], (total or 0)

    @staticmethod
    async def _hits(
        session: AsyncSession, run_id: int, tender_ids: list[int]
    ) -> dict[int, list[ResearchHitView]]:
        if not tender_ids:
            return {}
        rows = (
            await session.scalars(
                select(ResearchHit)
                .where(ResearchHit.run_id == run_id, ResearchHit.tender_id.in_(tender_ids))
                .order_by(ResearchHit.tender_id, ResearchHit.id)
            )
        ).all()

        found: dict[int, list[ResearchHitView]] = {}
        for row in rows:
            bucket = found.setdefault(row.tender_id, [])
            if len(bucket) >= HITS_PER_TENDER:
                continue
            bucket.append(
                ResearchHitView(
                    term=row.term,
                    role=row.role,
                    quote=row.quote,
                    match_start=row.match_start,
                    match_end=row.match_end,
                    file_name=row.file_name,
                    page=row.page,
                )
            )
        return found

    async def market(self, run_id: int) -> MarketView:
        """Разрезы по подтверждённым закупкам прогона.

        Считается в базе только выборка; арифметика — здесь, потому что медиана
        и доля верхушки в SQL выражаются заметно хуже, чем читаются в Python, а
        подтверждённых закупок десятки, не миллионы.
        """
        async with self._session_factory() as session:
            version = await session.scalar(
                select(ResearchRun.criteria_version).where(ResearchRun.id == run_id)
            )
            if version is None:
                return MarketView()

            rows = (
                await session.execute(
                    select(
                        Tender.price,
                        Tender.region_code,
                        Tender.customer_name,
                        Tender.customer_inn,
                        Tender.okpd2_code,
                    )
                    .join(ResearchHit, ResearchHit.tender_id == Tender.id)
                    .join(
                        ResearchVerdict,
                        (ResearchVerdict.tender_id == Tender.id)
                        & (ResearchVerdict.criteria_version == version),
                    )
                    .where(
                        ResearchHit.run_id == run_id,
                        ResearchVerdict.confidence == "confirmed",
                    )
                    .distinct()
                )
            ).all()

        return _summarize(rows)


def _to_card(row: ResearchRun) -> ResearchRunCard:
    return ResearchRunCard(
        run_id=row.id,
        name=row.name,
        criteria_version=row.criteria_version,
        status=row.status,
        regions=list(row.regions or []),
        date_from=row.date_from,
        date_to=row.date_to,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_message=row.error_message,
        confirmed=row.tenders_confirmed,
        rejected=row.tenders_rejected,
        funnel=ResearchFunnel(
            tenders_total=row.tenders_total,
            tenders_candidate=row.tenders_candidate,
            documents_scanned=row.documents_scanned,
            documents_pending=row.documents_pending,
            hits_found=row.hits_found,
            reviewed=row.tenders_confirmed + row.tenders_rejected + row.tenders_disputed,
            confirmed_by_rules=row.tenders_confirmed,
            rejected_by_rules=row.tenders_rejected,
            disputed=row.tenders_disputed,
        ),
    )


def _summarize(rows) -> MarketView:
    if not rows:
        return MarketView()

    prices = [row.price for row in rows if row.price is not None]
    total = sum(prices, Decimal(0)) if prices else Decimal(0)

    top_share = 0.0
    if total > 0:
        top = sorted(prices, reverse=True)[:TOP_N]
        top_share = float(sum(top, Decimal(0)) / total)

    return MarketView(
        total_count=len(rows),
        priced_count=len(prices),
        total_value=total,
        median_price=Decimal(str(median(prices))) if prices else None,
        average_price=(total / len(prices)) if prices else None,
        top_share=top_share,
        by_region=_group(
            rows,
            key=lambda r: r.region_code or "—",
            label=region_name,
        ),
        # По ИНН, а не по названию: под одним именем «Центр гигиены и
        # эпидемиологии» в замере оказались четыре разных юрлица.
        by_customer=_group(
            rows,
            key=lambda r: r.customer_inn or r.customer_name or "—",
            label=lambda k: k,
            names={
                (r.customer_inn or r.customer_name or "—"): (r.customer_name or "—")
                for r in rows
            },
        ),
        by_okpd2=_group(rows, key=lambda r: (r.okpd2_code or "—")[:2], label=lambda k: k),
    )


def _group(rows, key, label, names: dict[str, str] | None = None) -> list[MarketBucket]:
    counts: dict[str, int] = {}
    totals: dict[str, Decimal] = {}
    priced: dict[str, int] = {}

    for row in rows:
        bucket = key(row)
        counts[bucket] = counts.get(bucket, 0) + 1
        if row.price is not None:
            totals[bucket] = totals.get(bucket, Decimal(0)) + row.price
            priced[bucket] = priced.get(bucket, 0) + 1

    buckets = [
        MarketBucket(
            key=bucket,
            label=(names or {}).get(bucket) or label(bucket),
            count=count,
            total=totals.get(bucket, Decimal(0)),
            average=(totals[bucket] / priced[bucket]) if priced.get(bucket) else None,
        )
        for bucket, count in counts.items()
    ]
    buckets.sort(key=lambda b: (-b.total, -b.count, b.key))
    return buckets

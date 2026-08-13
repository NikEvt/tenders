"""Агрегаты по всей выдаче: фасеты, гистограмма цены, самое узкое условие.

Считается теми же условиями, что и список (`queries.conditions`) — иначе
счётчик фасета и число «найдено» разойдутся, и верить перестанут обоим.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Select, and_, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import Tender
from services.api.application.ports.catalog import TenderFacetsPort
from services.api.domain.catalog import (
    FacetBucket,
    Facets,
    GroupBucket,
    PriceBucket,
    RestrictiveHint,
)
from services.api.domain.models import TenderFilter
from services.api.infrastructure.db.queries import (
    GROUP_LABELS,
    SORT_COLUMNS,
    conditions,
    named_conditions,
)

# Длинный хвост фасета бесполезен: в списке из 900 заказчиков ничего не найти
# глазами, а поиск по ним — отдельная задача.
FACET_LIMIT = 20
PRICE_BUCKETS = 12


class SqlFacetsRepository(TenderFacetsPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def facets(
        self, filters: TenderFilter, restrict_to: Sequence[int] | None = None
    ) -> Facets:
        where = _where(filters, restrict_to)

        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(Tender).where(and_(*where))
            )
            regions = (await session.execute(self._grouped(Tender.region_code, where))).all()
            okpd2 = (
                await session.execute(
                    self._grouped(Tender.okpd2_code, where, label=Tender.okpd2_name)
                )
            ).all()
            customers = (
                await session.execute(
                    self._grouped(Tender.customer_inn, where, label=Tender.customer_name)
                )
            ).all()
            histogram = await self._price_histogram(session, where)

        return Facets(
            total=total or 0,
            regions=_buckets(regions),
            okpd2=_buckets(okpd2),
            customers=_buckets(customers),
            price_histogram=histogram,
        )

    async def restrictive(
        self, filters: TenderFilter, restrict_to: Sequence[int] | None = None
    ) -> RestrictiveHint | None:
        """Одним запросом на условие: их единицы, а спрашивают только на пустой выдаче."""
        names = list(named_conditions(filters))
        if not names:
            return None

        async with self._session_factory() as session:
            kept_all = await session.scalar(
                select(func.count()).select_from(Tender).where(and_(*conditions(filters)))
            )
            best: RestrictiveHint | None = None
            for name in names:
                without = await session.scalar(
                    select(func.count())
                    .select_from(Tender)
                    .where(and_(*conditions(filters, without=name)))
                )
                dropped = (without or 0) - (kept_all or 0)
                if best is None or dropped > best.dropped:
                    best = RestrictiveHint(param=name, kept=without or 0, dropped=dropped)

        # Условие, которое ничего не отсекает, подсказкой не является.
        return best if best is not None and best.dropped > 0 else None

    async def groups(self, filters: TenderFilter, field: str) -> list[GroupBucket]:
        """Шапки групп: считаются по всей выдаче, одним запросом.

        Порядок тот же, что у списка (`ORDER BY <ключ группы> ASC NULLS LAST`),
        иначе шапки шли бы в одном порядке, а строки под ними — в другом.
        Ограничения на число групп здесь нет: список показывает их все, а
        `FACET_LIMIT` — про длинный хвост фильтра, не про оглавление.
        """
        column = SORT_COLUMNS[field]
        label_column = GROUP_LABELS.get(field, column)
        where = conditions(filters)

        statement = (
            select(
                column.label("key"),
                func.min(label_column).label("label"),
                func.count().label("count"),
                func.sum(Tender.price).label("total_price"),
            )
            .where(and_(*where))
            .group_by(column)
            .order_by(column.asc().nullslast())
        )

        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()

        return [
            GroupBucket(
                # Пустая категория — тоже категория: закупки без ОКПД2 обязаны
                # где-то лежать, и «—» честнее, чем их исчезновение.
                key=row.key or "",
                label=row.label or row.key or "Без категории",
                count=row.count,
                total_price=row.total_price,
            )
            for row in rows
        ]

    @staticmethod
    def _grouped(column, where: list, label=None) -> Select:
        label_column = (label if label is not None else column).label("label")
        return (
            select(
                column.label("key"),
                func.min(label_column).label("label"),
                func.count().label("count"),
            )
            .where(and_(*where), column.is_not(None))
            .group_by(column)
            .order_by(func.count().desc())
            .limit(FACET_LIMIT)
        )

    async def _price_histogram(self, session: AsyncSession, where: list) -> list[PriceBucket]:
        bounds = (
            await session.execute(
                select(func.min(Tender.price), func.max(Tender.price))
                .select_from(Tender)
                .where(and_(*where), Tender.price.is_not(None))
            )
        ).first()
        if bounds is None or bounds[0] is None:
            return []

        low, high = Decimal(bounds[0]), Decimal(bounds[1])
        if high <= low:
            # Все цены одинаковы: один столбец честнее, чем двенадцать пустых.
            count = await session.scalar(
                select(func.count()).select_from(Tender).where(and_(*where), Tender.price == low)
            )
            return [PriceBucket(price_from=low, price_to=low, count=count or 0)]

        bucket = func.width_bucket(Tender.price, low, high, PRICE_BUCKETS).label("bucket")
        rows = (
            await session.execute(
                select(bucket, func.count().label("count"))
                .where(and_(*where), Tender.price.is_not(None))
                .group_by(bucket)
                .order_by(bucket)
            )
        ).all()

        width = (high - low) / PRICE_BUCKETS
        counts = {int(r.bucket): r.count for r in rows}
        return [
            PriceBucket(
                price_from=low + width * index,
                price_to=low + width * (index + 1),
                # width_bucket отдаёт PRICE_BUCKETS+1 для самого максимума —
                # он относится к последнему столбцу, а не к отдельному.
                count=counts.get(index + 1, 0)
                + (counts.get(PRICE_BUCKETS + 1, 0) if index == PRICE_BUCKETS - 1 else 0),
            )
            for index in range(PRICE_BUCKETS)
        ]


def _buckets(rows) -> list[FacetBucket]:
    # Подпись может отсутствовать (пустое имя заказчика) — тогда показываем ключ.
    return [FacetBucket(key=r.key, label=r.label or r.key, count=r.count) for r in rows]


def _where(filters: TenderFilter, restrict_to: Sequence[int] | None) -> list:
    """Условия подсчёта.

    Если выдача получена поиском, считать надо по её идентификаторам: часть
    поиска векторная и предикатом не выражается, поэтому предикаты дали бы
    другое множество — ровно та рассинхронизация, из-за которой счётчики
    показывали ноль на непустом списке.
    """
    if restrict_to is None:
        return conditions(filters)
    if not restrict_to:
        # Пустая выдача — пустые счётчики, а не «условий нет».
        return [false()]
    return [Tender.id.in_(restrict_to)]

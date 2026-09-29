"""Разрезы рынка по подтверждённым закупкам.

Вторая задача инструмента после «найти интересующие закупки» — понять, что
вообще происходит на рынке. Для этого хватает нескольких разрезов, но считать
их надо честно.

**Медиана вместе со средним, а не вместо.** Распределение НМЦК имеет тяжёлый
правый хвост: в прогоне ХПК/БПК медиана вышла 2.91 млн при среднем 5.43 млн,
а три закупки дороже 20 млн дали треть суммы. Одно среднее описало бы рынок,
которого нет.

**Заказчики считаются по ИНН, а не по названию.** Одно и то же учреждение
пишет своё имя по-разному от закупки к закупке, и группировка по строке
рассыпала бы «Центр гигиены и эпидемиологии» на несколько разных.

Модуль чистый: ни SQL, ни форматирования — только арифметика.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

from libs.shared.regions import region_name


@dataclass(frozen=True, slots=True)
class MarketTender:
    """Подтверждённая закупка глазами рыночной сводки."""

    reg_num: str
    name: str | None = None
    price: Decimal | None = None
    region_code: str | None = None
    customer_name: str | None = None
    customer_inn: str | None = None
    okpd2_code: str | None = None


@dataclass(frozen=True, slots=True)
class Bucket:
    """Группа закупок: сколько их и на какую сумму."""

    key: str
    label: str
    count: int
    total: Decimal
    #: Средний чек по группе. `None`, если ни у одной закупки нет цены.
    average: Decimal | None


@dataclass(slots=True)
class MarketSummary:
    total_count: int = 0
    #: Закупки без цены. Отдельным числом: без него «сумма 304 млн» невозможно
    #: сопоставить с числом закупок, и непонятно, все ли учтены.
    priced_count: int = 0
    total_value: Decimal = Decimal(0)
    median_price: Decimal | None = None
    average_price: Decimal | None = None
    #: Доля суммы, которую дают самые дорогие закупки. Показывает тот самый
    #: правый хвост числом, а не на глаз.
    top_share: float = 0.0

    by_region: list[Bucket] = field(default_factory=list)
    by_customer: list[Bucket] = field(default_factory=list)
    by_okpd2: list[Bucket] = field(default_factory=list)


#: Сколько закупок считать «верхушкой» при расчёте доли.
TOP_N = 3



def summarize(tenders: Sequence[MarketTender], top_n: int = TOP_N) -> MarketSummary:
    """Сводка по подтверждённым закупкам."""
    summary = MarketSummary(total_count=len(tenders))
    if not tenders:
        return summary

    prices = [t.price for t in tenders if t.price is not None]
    summary.priced_count = len(prices)

    if prices:
        summary.total_value = sum(prices, Decimal(0))
        summary.median_price = Decimal(str(median(prices)))
        summary.average_price = summary.total_value / len(prices)

        if summary.total_value > 0:
            top = sorted(prices, reverse=True)[:top_n]
            summary.top_share = float(sum(top, Decimal(0)) / summary.total_value)

    summary.by_region = _group(
        tenders,
        key=lambda t: t.region_code or "—",
        label=region_name,
    )
    # По ИНН, а не по названию: учреждение пишет своё имя по-разному.
    summary.by_customer = _group(
        tenders,
        key=lambda t: t.customer_inn or t.customer_name or "—",
        label=lambda key: key,
        names={
            (t.customer_inn or t.customer_name or "—"): (t.customer_name or "—")
            for t in tenders
        },
    )
    summary.by_okpd2 = _group(
        tenders,
        # Группа ОКПД2 — первые две цифры: разрез по полному коду распался бы
        # на почти уникальные значения и ничего бы не показал.
        key=lambda t: (t.okpd2_code or "—")[:2],
        label=lambda key: key,
    )
    return summary


def _group(
    tenders: Sequence[MarketTender],
    key: Callable[[MarketTender], str],
    label: Callable[[str], str],
    names: dict[str, str] | None = None,
) -> list[Bucket]:
    counts: dict[str, int] = {}
    totals: dict[str, Decimal] = {}
    priced: dict[str, int] = {}

    for tender in tenders:
        bucket_key = key(tender)
        counts[bucket_key] = counts.get(bucket_key, 0) + 1
        if tender.price is not None:
            totals[bucket_key] = totals.get(bucket_key, Decimal(0)) + tender.price
            priced[bucket_key] = priced.get(bucket_key, 0) + 1

    buckets = [
        Bucket(
            key=bucket_key,
            label=(names or {}).get(bucket_key) or label(bucket_key),
            count=count,
            total=totals.get(bucket_key, Decimal(0)),
            average=(
                totals[bucket_key] / priced[bucket_key]
                if priced.get(bucket_key)
                else None
            ),
        )
        for bucket_key, count in counts.items()
    ]
    # По сумме, а не по числу: рынок интересен деньгами, а разрез по количеству
    # виден в той же строке.
    buckets.sort(key=lambda b: (-b.total, -b.count, b.key))
    return buckets

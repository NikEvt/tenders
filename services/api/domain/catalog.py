"""Агрегаты каталога: фасеты, гистограмма цены, похожие закупки."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from services.api.domain.models import TenderSummary


@dataclass(slots=True)
class FacetBucket:
    key: str
    label: str
    count: int


@dataclass(slots=True)
class PriceBucket:
    """Столбец гистограммы. Границы полуинтервальные: [from, to)."""

    price_from: Decimal
    price_to: Decimal
    count: int


@dataclass(slots=True)
class Facets:
    """Счётчики по всей выдаче, а не по текущей странице.

    Фасет, посчитанный по странице, показывает «Москва — 12» там, где в выдаче
    её 3000. Такой счётчик хуже отсутствующего: он выглядит достоверным.
    """

    total: int
    regions: list[FacetBucket] = field(default_factory=list)
    okpd2: list[FacetBucket] = field(default_factory=list)
    customers: list[FacetBucket] = field(default_factory=list)
    price_histogram: list[PriceBucket] = field(default_factory=list)


@dataclass(slots=True)
class GroupBucket:
    """Шапка группы в сгруппированном списке.

    Счётчик и сумма считаются по всей выдаче, а не по загруженной странице:
    группа в неё не помещается, и «Заказчик — 12 закупок» рядом с тремя
    видимыми строками было бы враньём, выглядящим достоверно.
    """

    key: str
    label: str
    count: int
    total_price: Decimal | None


@dataclass(slots=True)
class RestrictiveHint:
    """Условие, которое отсекает больше всех, и цена его снятия."""

    param: str
    kept: int
    dropped: int


@dataclass(slots=True)
class SimilarTender:
    tender: TenderSummary
    similarity: float
    driver: str

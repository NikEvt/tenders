"""Прогоны исследований глазами интерфейса.

Шлюз их только читает: пишет движок отбора, запускает — заявка событием. Здесь
проекция для экрана, а не бизнес-операция.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ResearchFunnel:
    """Воронка прогона.

    Ветвление, а не каскад: «принято правилами» не является подмножеством
    «отсеяно правилами», и рисовать их лестницей значило бы врать.

    Два поля здесь — знаменатели, и без них остальные числа не читаются:
    `documents_pending` («не прочитано») и `not_reached` («не дошли, модель
    легла»). Ретроспектива описывает, как их отсутствие приводит к выводу
    «здесь ничего нет» на месте, где просто не искали.
    """

    tenders_total: int = 0
    tenders_candidate: int = 0
    documents_scanned: int = 0
    documents_pending: int = 0
    hits_found: int = 0

    reviewed: int = 0
    rejected_by_rules: int = 0
    confirmed_by_rules: int = 0
    disputed: int = 0
    from_cache: int = 0
    asked_model: int = 0
    not_reached: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class ResearchRunCard:
    run_id: int
    name: str
    criteria_version: str
    status: str
    regions: list[str] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    funnel: ResearchFunnel = field(default_factory=ResearchFunnel)
    confirmed: int = 0
    rejected: int = 0


@dataclass(frozen=True, slots=True)
class ResearchHitView:
    """Цитата со смещением совпадения — то, что можно подсветить."""

    term: str
    role: str
    quote: str
    match_start: int
    match_end: int
    file_name: str | None = None
    page: int | None = None


@dataclass(frozen=True, slots=True)
class ResearchTenderRow:
    """Закупка прогона: вердикт, кем решено и чем подтверждён."""

    tender_id: int
    reg_num: str
    name: str | None
    price: Decimal | None
    region_code: str | None
    customer_name: str | None
    customer_inn: str | None
    okpd2_code: str | None
    confidence: str
    reason: str | None
    decided_by: str
    score: float
    hits: list[ResearchHitView] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MarketBucket:
    key: str
    label: str
    count: int
    total: Decimal
    average: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketView:
    """Разрезы рынка по подтверждённым закупкам прогона.

    Медиана отдаётся вместе со средним, а не вместо: у НМЦК тяжёлый правый
    хвост, и одно среднее описывает рынок, которого нет.
    """

    total_count: int = 0
    priced_count: int = 0
    total_value: Decimal = Decimal(0)
    median_price: Decimal | None = None
    average_price: Decimal | None = None
    top_share: float = 0.0
    by_region: list[MarketBucket] = field(default_factory=list)
    by_customer: list[MarketBucket] = field(default_factory=list)
    by_okpd2: list[MarketBucket] = field(default_factory=list)

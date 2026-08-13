"""Проекции профиля интересов для экрана."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(slots=True)
class RatingRecord:
    """Оценка, поставленная закупке. Основание, по которому учится профиль."""

    signal_id: int
    tender_id: int
    reg_num: str
    name: str | None
    signal: str
    created_at: datetime


@dataclass(slots=True)
class WinRecord:
    tender_id: int
    reg_num: str
    name: str | None
    won_at: date | None
    contract_price: Decimal | None
    notes: str | None


@dataclass(slots=True)
class WinsSummary:
    items: list[WinRecord]
    total_value: Decimal

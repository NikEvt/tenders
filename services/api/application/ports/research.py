"""Порт чтения исследований.

Читается напрямую из общей базы, а не через движок отбора: это проекция для
экрана, а не бизнес-операция. Тот же довод, по которому шлюз сам читает
сохранённые фильтры.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.api.domain.research import (
    MarketView,
    ResearchRunCard,
    ResearchTenderRow,
)


class ResearchReadPort(ABC):
    @abstractmethod
    async def runs(self, limit: int) -> list[ResearchRunCard]: ...

    @abstractmethod
    async def run(self, run_id: int) -> ResearchRunCard | None: ...

    @abstractmethod
    async def tenders(
        self, run_id: int, confidence: str | None, limit: int, offset: int
    ) -> tuple[list[ResearchTenderRow], int]:
        """Закупки прогона с вердиктами и цитатами.

        Возвращает страницу и общее число — постранично, потому что у прогона
        по четырём регионам закупок бывают тысячи.
        """

    @abstractmethod
    async def market(self, run_id: int) -> MarketView:
        """Разрезы рынка по подтверждённым закупкам прогона."""

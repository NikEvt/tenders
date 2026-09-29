"""Чтение исследований: прогоны, закупки, рынок.

Сценарии тонкие — вся работа в репозитории. Существуют они ради двух вещей:
проверки «прогон есть» и потолков постраничности, которые не должен назначать
ни репозиторий, ни роутер.
"""

from __future__ import annotations

from services.api.application.errors import NotFound
from services.api.application.ports.research import ResearchReadPort
from services.api.domain.research import (
    MarketView,
    ResearchRunCard,
    ResearchTenderRow,
)

#: Потолок страницы. У прогона по четырём регионам закупок бывают тысячи,
#: и отдать их одним ответом значит положить и шлюз, и вкладку браузера.
MAX_PAGE_SIZE = 200


class ListResearchRunsUseCase:
    def __init__(self, research: ResearchReadPort) -> None:
        self._research = research

    async def execute(self, limit: int) -> list[ResearchRunCard]:
        return await self._research.runs(max(1, min(limit, 200)))


class GetResearchRunUseCase:
    def __init__(self, research: ResearchReadPort) -> None:
        self._research = research

    async def execute(self, run_id: int) -> ResearchRunCard:
        found = await self._research.run(run_id)
        if found is None:
            raise NotFound("Прогон не найден", run_id=run_id)
        return found


class ListResearchTendersUseCase:
    def __init__(self, research: ResearchReadPort) -> None:
        self._research = research

    async def execute(
        self, run_id: int, confidence: str | None, page: int, page_size: int
    ) -> tuple[list[ResearchTenderRow], int]:
        if await self._research.run(run_id) is None:
            raise NotFound("Прогон не найден", run_id=run_id)

        size = max(1, min(page_size, MAX_PAGE_SIZE))
        return await self._research.tenders(
            run_id, confidence, size, max(page - 1, 0) * size
        )


class GetResearchMarketUseCase:
    def __init__(self, research: ResearchReadPort) -> None:
        self._research = research

    async def execute(self, run_id: int) -> MarketView:
        if await self._research.run(run_id) is None:
            raise NotFound("Прогон не найден", run_id=run_id)
        return await self._research.market(run_id)

"""Чтение сохранённых фильтров."""

from __future__ import annotations

from services.api.application.errors import NotFound
from services.api.application.ports.filters import FilterReadPort
from services.api.domain.filters import MATCH_HISTORY_DAYS, SavedFilterCard


class ListFiltersUseCase:
    def __init__(self, filters: FilterReadPort) -> None:
        self._filters = filters

    async def execute(self) -> list[SavedFilterCard]:
        return await self._filters.list(MATCH_HISTORY_DAYS)


class GetFilterUseCase:
    def __init__(self, filters: FilterReadPort) -> None:
        self._filters = filters

    async def execute(self, filter_id: int) -> SavedFilterCard:
        card = await self._filters.get(filter_id, MATCH_HISTORY_DAYS)
        if card is None:
            raise NotFound(f"Фильтр {filter_id} не найден", filter_id=filter_id)
        return card

"""Управление сохранёнными фильтрами.

Запись живёт здесь, а не в шлюзе: согласованность `nl_query ↔ spec ↔
llm_criteria ↔ semantic_query` держит компиляция, и смена `spec` обязана
учитывать версию промпта, которой инвалидируется кэш вердиктов. Второй писатель
в ту же таблицу дал бы две точки истины на один агрегат.
"""

from __future__ import annotations

from services.llm_service.application.ports import FilterRepositoryPort
from services.llm_service.domain.models import FilterPatch, SavedFilterView

COPY_SUFFIX = "копия"


class ManageFiltersUseCase:
    def __init__(self, repository: FilterRepositoryPort) -> None:
        self._repository = repository

    async def list(self) -> list[SavedFilterView]:
        return await self._repository.list_filters()

    async def get(self, filter_id: int) -> SavedFilterView | None:
        return await self._repository.get_filter(filter_id)

    async def update(self, filter_id: int, patch: FilterPatch) -> SavedFilterView | None:
        return await self._repository.update_filter(filter_id, patch)

    async def delete(self, filter_id: int) -> bool:
        return await self._repository.delete_filter(filter_id)

    async def duplicate(self, filter_id: int) -> SavedFilterView | None:
        """Копия сохраняется как есть, без перекомпиляции.

        Смысл дубликата — взять отлаженный фильтр и поправить одно условие.
        Перекомпиляция текста вернула бы исходный spec и стёрла правки, ради
        которых копию и делают.
        """
        source = await self._repository.get_filter(filter_id)
        if source is None:
            return None

        new_id = await self._repository.save_spec(
            f"{source.name} ({COPY_SUFFIX})", source.query, source.spec
        )
        return await self._repository.get_filter(new_id)

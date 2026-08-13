"""Порт чтения сохранённых фильтров.

Только чтение. Запись принадлежит llm-service: он компилирует спецификацию и
им же судит, а два писателя в одну таблицу дали бы две точки истины на агрегат.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.api.domain.filters import SavedFilterCard


class FilterReadPort(ABC):
    @abstractmethod
    async def list(self, history_days: int) -> list[SavedFilterCard]: ...

    @abstractmethod
    async def get(self, filter_id: int, history_days: int) -> SavedFilterCard | None: ...

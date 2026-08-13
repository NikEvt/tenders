"""Профиль интересов: чтение истории.

Разрез тот же, что у фильтров. **Чтение** истории и побед — своё, это проекция
общей БД. **Запись** — вниз, в recsys-service: ручной вес не просто строка в
JSONB, а правка, которую пересборка профиля обязана уважать. Запиши её шлюз
напрямую — ближайший сигнал молча затрёт, и это выглядело бы как «веса не
сохраняются».
"""

from __future__ import annotations

from services.api.application.ports.profile import ProfileHistoryPort
from services.api.domain.profile import RatingRecord, WinsSummary

DEFAULT_HISTORY_PAGE = 50


class ProfileHistoryUseCase:
    def __init__(self, history: ProfileHistoryPort) -> None:
        self._history = history

    async def execute(
        self, page: int, page_size: int = DEFAULT_HISTORY_PAGE
    ) -> tuple[list[RatingRecord], int]:
        return await self._history.ratings(page, page_size)


class ProfileWinsUseCase:
    def __init__(self, history: ProfileHistoryPort) -> None:
        self._history = history

    async def execute(self) -> WinsSummary:
        return await self._history.wins()

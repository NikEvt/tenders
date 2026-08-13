"""Порт чтения истории профиля.

Только чтение: сигналы и победы записывает recsys-service — он же пересобирает
по ним профиль. Второй писатель разошёлся бы с ним в трактовке.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.api.domain.profile import RatingRecord, WinsSummary


class ProfileHistoryPort(ABC):
    @abstractmethod
    async def ratings(self, page: int, page_size: int) -> tuple[list[RatingRecord], int]: ...

    @abstractmethod
    async def wins(self) -> WinsSummary: ...

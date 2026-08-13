"""Порт чтения ежедневных сводок."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class DigestReadPort(ABC):
    @abstractmethod
    async def get(self, digest_date: date) -> dict | None: ...

    @abstractmethod
    async def dates(self, since: date, until: date) -> list[date]:
        """За какие дни сводка уже есть — точки в календаре."""

"""Порт проверки готовности зависимостей шлюза."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ReadinessPort(ABC):
    @abstractmethod
    async def check(self) -> None:
        """Бросает исключение, если зависимость недоступна."""

"""Порты соседних сервисов.

Шлюз не воспроизводит их логику: компиляция фильтра живёт в llm-service,
профиль интересов — в recsys-service. Здесь только контракт обращения.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class LlmServicePort(ABC):
    @abstractmethod
    async def compile_filter(self, query: str) -> dict: ...

    @abstractmethod
    async def save_filter(self, name: str, query: str, spec: dict | None = None) -> dict:
        """Передан `spec` — сохраняется как есть, иначе текст компилируется заново."""

    @abstractmethod
    async def patch_filter(self, filter_id: int, patch: dict) -> dict: ...

    @abstractmethod
    async def delete_filter(self, filter_id: int) -> None: ...

    @abstractmethod
    async def duplicate_filter(self, filter_id: int) -> dict: ...

    @abstractmethod
    async def test_filter(self, filter_id: int, days: int) -> dict: ...

    @abstractmethod
    async def run_filter(
        self, filter_id: int, since: date | None, tender_ids: list[int]
    ) -> dict: ...

    @abstractmethod
    async def request_digest(self, digest_date: date, force: bool) -> dict: ...


class RecsysServicePort(ABC):
    @abstractmethod
    async def recommendations(self, limit: int) -> list[dict]: ...

    @abstractmethod
    async def feedback(self, tender_id: int, signal: str, reason: str | None) -> dict: ...

    @abstractmethod
    async def view(self, tender_id: int, dwell_ms: int | None) -> dict: ...

    @abstractmethod
    async def win(self, tender_id: int, payload: dict) -> dict: ...

    @abstractmethod
    async def profile(self) -> dict: ...

    @abstractmethod
    async def profile_weights(self) -> list[dict]: ...

    @abstractmethod
    async def set_profile_weight(self, facet: str, key: str, weight: float | None) -> list[dict]:
        """`weight=None` снимает ручную правку."""

    @abstractmethod
    async def ranker(self) -> dict: ...

    @abstractmethod
    async def delete_rating(self, signal_id: int) -> None: ...

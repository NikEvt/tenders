"""Порт чтения состава корпуса."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from services.api.domain.corpus import CorpusOverview, EmbeddingProgress, TodayIngest


class CorpusStatsPort(ABC):
    @abstractmethod
    async def overview(self, since: date, until: date, limit: int) -> CorpusOverview:
        """Состав корпуса за период: по дням, регионам и ОКПД2.

        `limit` ограничивает верхушку каждого разреза; остаток обязан вернуться
        числом, а не потеряться — иначе сумма показанного не сойдётся с итогом.
        """

    @abstractmethod
    async def embeddings(self) -> EmbeddingProgress: ...

    @abstractmethod
    async def today(self, day: date) -> TodayIngest: ...

"""Порты рекомендательной системы."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from services.recsys_service.domain.models import (
    Profile,
    Recommendation,
    RecommendationCandidate,
    ScoreBreakdown,
    Signal,
    WeightedSignal,
)


class ProfileRepositoryPort(ABC):
    @abstractmethod
    async def load_signals(self) -> list[WeightedSignal]: ...

    @abstractmethod
    async def load_profile(self) -> Profile: ...

    @abstractmethod
    async def save_profile(self, profile: Profile) -> None: ...

    @abstractmethod
    async def set_manual_weight(self, key: str, weight: float | None) -> Profile:
        """Ручная правка веса. `None` снимает её, возвращая вычисленное значение."""


class RecommendationRepositoryPort(ABC):
    @abstractmethod
    async def find_similar(
        self, embedding: Sequence[float], limit: int, exclude: set[int]
    ) -> list[RecommendationCandidate]: ...

    @abstractmethod
    async def find_fresh(self, limit: int, exclude: set[int]) -> list[RecommendationCandidate]: ...

    @abstractmethod
    async def already_seen(self) -> set[int]:
        """Тендеры, которые уже показывали или по которым есть явный сигнал."""

    @abstractmethod
    async def save_impressions(self, recommendations: Sequence[Recommendation]) -> None: ...

    @abstractmethod
    async def record_feedback(
        self, tender_id: int, signal: Signal, reason: str | None
    ) -> None: ...

    @abstractmethod
    async def record_view(self, tender_id: int, dwell_ms: int | None) -> None: ...

    @abstractmethod
    async def delete_feedback(self, signal_id: int) -> bool:
        """Отменяет оценку. False — такой оценки нет."""

    @abstractmethod
    async def record_win(
        self, tender_id: int, won_at, contract_price, notes: str | None
    ) -> None: ...


class RankerPort(ABC):
    """Стратегия ранжирования.

    Сегодня — прозрачная линейная формула, дающая объяснение. Когда наберётся
    достаточно фидбека, за этим же портом появится обученный ranker, и вызывающий
    код менять не придётся (OCP).
    """

    @abstractmethod
    def score(
        self, candidate: RecommendationCandidate, profile: Profile
    ) -> ScoreBreakdown: ...

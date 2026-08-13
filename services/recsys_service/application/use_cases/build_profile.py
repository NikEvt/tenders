"""Построение профиля интересов из сигналов пользователя."""

from __future__ import annotations

import math
from collections import defaultdict

from libs.shared.contracts.events import FeedbackRecorded
from libs.shared.logging import get_logger
from services.recsys_service.application.ports import ProfileRepositoryPort
from services.recsys_service.domain.models import Profile, WeightedSignal

log = get_logger(__name__)


class RebuildProfileUseCase:
    """Пересобирает профиль по всем накопленным сигналам.

    Полный пересчёт, а не инкремент: сигналов у одной компании тысячи, а не
    миллионы, зато отрицательные оценки корректно вычитаются, и профиль не
    «залипает» на давно отозванных предпочтениях.
    """

    def __init__(self, repository: ProfileRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, _: FeedbackRecorded | None = None) -> Profile:
        signals = await self._repository.load_signals()
        profile = build_profile(signals)
        await self._repository.save_profile(profile)
        log.info(
            "profile.rebuilt",
            signals=profile.signal_count,
            okpd2=len(profile.okpd2_weights),
            has_embedding=profile.embedding is not None,
        )
        return profile


def build_profile(signals: list[WeightedSignal]) -> Profile:
    profile = Profile(signal_count=len(signals))
    if not signals:
        return profile

    profile.embedding = _weighted_centroid(signals)
    profile.okpd2_weights = _normalized(_accumulate(signals, lambda s: s.okpd2_code))
    profile.customer_weights = _normalized(_accumulate(signals, lambda s: s.customer_inn))
    profile.price_stats = _price_stats(signals)
    return profile


def _weighted_centroid(signals: list[WeightedSignal]) -> list[float] | None:
    """Центроид эмбеддингов с учётом знака сигнала.

    Отрицательные веса отталкивают центроид от нежелательных закупок — это
    дешевле и понятнее, чем отдельная модель «антипредпочтений».
    """
    vectors = [(s.embedding, s.weight) for s in signals if s.embedding]
    if not vectors:
        return None

    dim = len(vectors[0][0])
    accumulator = [0.0] * dim
    total_weight = 0.0

    for embedding, weight in vectors:
        if len(embedding) != dim:
            continue
        for index, value in enumerate(embedding):
            accumulator[index] += value * weight
        total_weight += abs(weight)

    if total_weight == 0:
        return None

    norm = math.sqrt(sum(value * value for value in accumulator))
    if norm == 0:
        # Положительные и отрицательные сигналы взаимно уничтожились —
        # осмысленного направления нет.
        return None
    # Нормализуем: индексы pgvector построены под косинусную метрику.
    return [value / norm for value in accumulator]


def _accumulate(signals: list[WeightedSignal], key) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for signal in signals:
        value = key(signal)
        if value:
            totals[value] += signal.weight
    return dict(totals)


def _normalized(weights: dict[str, float]) -> dict[str, float]:
    """Приводит веса к [-1, 1] по максимальному модулю."""
    if not weights:
        return {}
    peak = max(abs(value) for value in weights.values()) or 1.0
    return {key: round(value / peak, 4) for key, value in weights.items()}


def _price_stats(signals: list[WeightedSignal]) -> dict[str, float]:
    """Квартили бюджета по положительным сигналам.

    Медиана и квартили, а не среднее: одна крупная закупка сместила бы среднее
    так, что «привычный диапазон» перестал бы соответствовать реальности.
    """
    prices = sorted(
        float(s.price) for s in signals if s.price is not None and s.weight > 0
    )
    if not prices:
        return {}

    return {
        "min": prices[0],
        "p25": _quantile(prices, 0.25),
        "median": _quantile(prices, 0.5),
        "p75": _quantile(prices, 0.75),
        "max": prices[-1],
        "count": float(len(prices)),
    }


def _quantile(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    low = math.floor(position)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = position - low
    return sorted_values[low] * (1 - fraction) + sorted_values[high] * fraction

"""Прозрачное линейное ранжирование.

Формула выбрана вместо обученной модели намеренно: на старте фидбека нет, а
объяснимость выдачи важнее долей процента качества. Веса подобраны так, чтобы
семантическая близость доминировала, но не подавляла остальные факторы полностью.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services.recsys_service.application.ports import RankerPort
from services.recsys_service.domain.models import (
    Profile,
    RecommendationCandidate,
    ScoreBreakdown,
)

WEIGHT_SIMILARITY = 1.0
WEIGHT_OKPD2 = 0.4
WEIGHT_PRICE = 0.25
WEIGHT_CUSTOMER = 0.2
WEIGHT_FRESHNESS = 0.3

# За две недели свежесть падает до нуля: закупка с истекающим сроком подачи
# полезна ровно до дедлайна.
FRESHNESS_HALFLIFE_DAYS = 14.0

# Насколько бюджет может выходить за привычный диапазон и всё ещё считаться
# «своим»: границы p25/p75 узкие, буфер не даёт отсекать пограничные закупки.
PRICE_TOLERANCE = 0.5


class LinearRanker(RankerPort):
    def score(self, candidate: RecommendationCandidate, profile: Profile) -> ScoreBreakdown:
        breakdown = ScoreBreakdown()
        breakdown.similarity = WEIGHT_SIMILARITY * candidate.similarity
        breakdown.okpd2_match = WEIGHT_OKPD2 * self._okpd2_affinity(candidate, profile)
        breakdown.price_fit = WEIGHT_PRICE * self._price_fit(candidate, profile)
        breakdown.known_customer = WEIGHT_CUSTOMER * self._customer_affinity(candidate, profile)
        breakdown.freshness = WEIGHT_FRESHNESS * self._freshness(candidate)
        return breakdown

    @staticmethod
    def _okpd2_affinity(candidate: RecommendationCandidate, profile: Profile) -> float:
        if not candidate.okpd2_code or not profile.okpd2_weights:
            return 0.0

        best = 0.0
        for code, weight in profile.okpd2_weights.items():
            if weight <= 0:
                continue
            # Совпадение по префиксу: 20.11.11 и 20.11.12 — соседние товары
            # одной группы, для пользователя это одна ниша.
            prefix = _common_prefix_len(candidate.okpd2_code, code)
            if prefix >= 5:  # «20.11» — группа
                best = max(best, weight * (1.0 if prefix >= 8 else 0.7))
        return min(best, 1.0)

    @staticmethod
    def _price_fit(candidate: RecommendationCandidate, profile: Profile) -> float:
        price_range = profile.price_range
        if price_range is None or candidate.price is None:
            return 0.0

        low, high = price_range
        price = float(candidate.price)
        if low <= price <= high:
            return 1.0

        span = max(high - low, 1.0)
        distance = (low - price) if price < low else (price - high)
        # Плавное затухание вместо обрыва: закупка чуть дороже привычной
        # всё ещё интересна.
        return max(0.0, 1.0 - distance / (span * (1 + PRICE_TOLERANCE)))

    @staticmethod
    def _customer_affinity(candidate: RecommendationCandidate, profile: Profile) -> float:
        if not candidate.customer_inn:
            return 0.0
        return max(0.0, min(profile.customer_weights.get(candidate.customer_inn, 0.0), 1.0))

    @staticmethod
    def _freshness(candidate: RecommendationCandidate) -> float:
        if candidate.publish_date is None:
            return 0.0
        published = candidate.publish_date
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - published).total_seconds() / 86400
        if age_days <= 0:
            return 1.0
        return max(0.0, 1.0 - age_days / FRESHNESS_HALFLIFE_DAYS)


def _common_prefix_len(left: str, right: str) -> int:
    length = 0
    for a, b in zip(left, right, strict=False):
        if a != b:
            break
        length += 1
    return length

"""Доменные модели рекомендательной системы."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class Signal(StrEnum):
    WON = "won"
    SHORTLIST = "shortlist"
    LIKE = "like"
    VIEW = "view"
    DISLIKE = "dislike"
    HIDE = "hide"


# Вес сигнала в профиле. Выигранный тендер — самое надёжное свидетельство
# интереса: за ним стоит поданная заявка, а не один клик. Просмотр — самый
# слабый: пользователь мог открыть карточку и сразу закрыть.
SIGNAL_WEIGHTS: dict[Signal, float] = {
    Signal.WON: 3.0,
    Signal.SHORTLIST: 2.0,
    Signal.LIKE: 1.5,
    Signal.VIEW: 0.5,
    Signal.DISLIKE: -1.0,
    Signal.HIDE: -1.5,
}

# Просмотр короче этого времени в профиль не идёт: это «открыл и закрыл».
MIN_DWELL_MS_FOR_SIGNAL = 20_000

# Доля выдачи под исследование. Без неё профиль схлопывается: система показывает
# только похожее на уже понравившееся и перестаёт находить новые ниши.
EXPLORATION_RATIO = 0.15

# Ниже этого числа сигналов профиль статистически бессмыслен — отдаём просто
# свежие активные закупки.
MIN_SIGNALS_FOR_PERSONALIZATION = 3


@dataclass(slots=True)
class WeightedSignal:
    """Сигнал с эмбеддингом тендера, к которому он относится."""

    tender_id: int
    signal: Signal
    weight: float
    embedding: list[float] | None
    okpd2_code: str | None
    price: Decimal | None
    customer_inn: str | None


@dataclass(slots=True)
class Profile:
    """Профиль интересов: центроид эмбеддингов + статистика предпочтений."""

    embedding: list[float] | None = None
    okpd2_weights: dict[str, float] = field(default_factory=dict)
    customer_weights: dict[str, float] = field(default_factory=dict)
    price_stats: dict[str, float] = field(default_factory=dict)
    signal_count: int = 0
    # Правки пользователя. Отдельно от вычисленных: пересборка обязана их
    # уважать, иначе ближайший сигнал молча затрёт ручной вес, и это выглядит
    # как «веса не сохраняются».
    manual_weights: dict[str, float] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return self.signal_count >= MIN_SIGNALS_FOR_PERSONALIZATION and self.embedding is not None

    def effective_weights(self) -> dict[str, float]:
        """Вычисленные веса, перекрытые ручными."""
        return {**self.okpd2_weights, **self.manual_weights}

    @property
    def price_range(self) -> tuple[float, float] | None:
        low = self.price_stats.get("p25")
        high = self.price_stats.get("p75")
        if low is None or high is None:
            return None
        return low, high


@dataclass(slots=True)
class ScoreBreakdown:
    """Вклад каждого фактора — основа объяснения «почему рекомендовано»."""

    similarity: float = 0.0
    okpd2_match: float = 0.0
    price_fit: float = 0.0
    known_customer: float = 0.0
    freshness: float = 0.0
    exploration: bool = False

    @property
    def total(self) -> float:
        return (
            self.similarity
            + self.okpd2_match
            + self.price_fit
            + self.known_customer
            + self.freshness
        )

    def explain(self) -> dict[str, object]:
        reasons: list[str] = []
        if self.similarity > 0.5:
            reasons.append("похоже на закупки, которые вас интересовали")
        if self.okpd2_match > 0:
            reasons.append("совпадает категория ОКПД2")
        if self.price_fit > 0:
            reasons.append("бюджет в вашем обычном диапазоне")
        if self.known_customer > 0:
            reasons.append("заказчик вам знаком")
        if self.freshness > 0.15:
            reasons.append("свежая публикация")
        if self.exploration:
            reasons.append("подборка для расширения кругозора")

        return {
            "reasons": reasons,
            "factors": {
                "similarity": round(self.similarity, 4),
                "okpd2_match": round(self.okpd2_match, 4),
                "price_fit": round(self.price_fit, 4),
                "known_customer": round(self.known_customer, 4),
                "freshness": round(self.freshness, 4),
            },
            "exploration": self.exploration,
        }


@dataclass(slots=True)
class RecommendationCandidate:
    tender_id: int
    reg_num: str
    name: str | None
    description: str | None
    price: Decimal | None
    customer_name: str | None
    customer_inn: str | None
    okpd2_code: str | None
    publish_date: datetime | None
    end_date: date | None
    similarity: float = 0.0


@dataclass(slots=True)
class Recommendation:
    candidate: RecommendationCandidate
    score: float
    breakdown: ScoreBreakdown

"""Профиль интересов, ранжирование и диверсификация выдачи."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from services.recsys_service.application.use_cases.build_profile import build_profile
from services.recsys_service.application.use_cases.recommend import (
    RecommendUseCase,
    _diversify,
)
from services.recsys_service.domain.models import (
    SIGNAL_WEIGHTS,
    Profile,
    Recommendation,
    RecommendationCandidate,
    ScoreBreakdown,
    Signal,
    WeightedSignal,
)
from services.recsys_service.infrastructure.ranking.linear_ranker import LinearRanker

DIM = 8


def unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


GAS = unit(1, 0, 0, 0, 0, 0, 0, 0)
FURNITURE = unit(0, 1, 0, 0, 0, 0, 0, 0)


def signal(
    tender_id: int,
    kind: Signal,
    embedding: list[float] | None = None,
    okpd2: str | None = "20.11.11",
    price: Decimal | None = Decimal("1000000"),
    inn: str | None = "7700000001",
) -> WeightedSignal:
    return WeightedSignal(
        tender_id=tender_id,
        signal=kind,
        weight=SIGNAL_WEIGHTS[kind],
        embedding=embedding if embedding is not None else GAS,
        okpd2_code=okpd2,
        price=price,
        customer_inn=inn,
    )


class TestProfileBuilding:
    def test_empty_signals_give_unusable_profile(self) -> None:
        profile = build_profile([])
        assert profile.signal_count == 0
        assert profile.embedding is None
        assert not profile.is_usable

    def test_centroid_points_at_liked_direction(self) -> None:
        profile = build_profile(
            [signal(1, Signal.WON), signal(2, Signal.LIKE), signal(3, Signal.SHORTLIST)]
        )
        assert profile.embedding is not None
        # Все сигналы положительные и однонаправленные — центроид совпадает с ними.
        assert profile.embedding[0] == pytest.approx(1.0, abs=1e-6)
        assert profile.is_usable

    def test_dislike_pushes_centroid_away(self) -> None:
        """Отрицательный вес должен отталкивать, а не просто игнорироваться."""
        liked_only = build_profile([signal(1, Signal.LIKE, embedding=GAS)])
        with_dislike = build_profile(
            [
                signal(1, Signal.LIKE, embedding=GAS),
                signal(2, Signal.DISLIKE, embedding=FURNITURE),
            ]
        )

        assert liked_only.embedding[1] == pytest.approx(0.0, abs=1e-6)
        assert with_dislike.embedding[1] < 0

    def test_opposing_signals_cancel_to_no_direction(self) -> None:
        profile = build_profile(
            [
                signal(1, Signal.LIKE, embedding=GAS),
                signal(2, Signal.LIKE, embedding=[-v for v in GAS]),
            ]
        )
        assert profile.embedding is None

    def test_won_outweighs_a_view(self) -> None:
        assert SIGNAL_WEIGHTS[Signal.WON] > SIGNAL_WEIGHTS[Signal.VIEW]

        profile = build_profile(
            [
                signal(1, Signal.WON, embedding=GAS, okpd2="20.11.11"),
                signal(2, Signal.VIEW, embedding=FURNITURE, okpd2="31.01.11"),
            ]
        )
        assert profile.okpd2_weights["20.11.11"] > profile.okpd2_weights["31.01.11"]
        assert profile.embedding[0] > profile.embedding[1]

    def test_price_stats_use_quartiles_not_mean(self) -> None:
        """Одна огромная закупка не должна утаскивать «привычный диапазон»."""
        signals = [
            signal(i, Signal.LIKE, price=Decimal("1000000")) for i in range(1, 10)
        ]
        signals.append(signal(99, Signal.LIKE, price=Decimal("500000000")))

        stats = build_profile(signals).price_stats
        assert stats["median"] == pytest.approx(1_000_000)
        assert stats["p75"] < 10_000_000

    def test_negative_signals_excluded_from_price_stats(self) -> None:
        stats = build_profile(
            [
                signal(1, Signal.LIKE, price=Decimal("1000000")),
                signal(2, Signal.DISLIKE, price=Decimal("999000000")),
            ]
        ).price_stats
        assert stats["max"] == pytest.approx(1_000_000)

    def test_okpd2_weights_are_normalized(self) -> None:
        profile = build_profile([signal(1, Signal.WON), signal(2, Signal.WON)])
        assert max(profile.okpd2_weights.values()) == pytest.approx(1.0)


def candidate(
    tender_id: int = 1,
    okpd2: str | None = "20.11.11",
    price: Decimal | None = Decimal("1000000"),
    inn: str | None = "7700000001",
    similarity: float = 0.8,
    age_days: float = 1.0,
    name: str = "Поставка газа",
) -> RecommendationCandidate:
    return RecommendationCandidate(
        tender_id=tender_id,
        reg_num=f"REG-{tender_id}",
        name=name,
        description=None,
        price=price,
        customer_name="ГКУ",
        customer_inn=inn,
        okpd2_code=okpd2,
        publish_date=datetime.now(UTC) - timedelta(days=age_days),
        end_date=None,
        similarity=similarity,
    )


PROFILE = Profile(
    embedding=GAS,
    okpd2_weights={"20.11.11": 1.0},
    customer_weights={"7700000001": 1.0},
    price_stats={"p25": 800_000.0, "p75": 1_500_000.0},
    signal_count=10,
)


class TestLinearRanker:
    def test_all_factors_contribute(self) -> None:
        breakdown = LinearRanker().score(candidate(), PROFILE)

        assert breakdown.similarity > 0
        assert breakdown.okpd2_match > 0
        assert breakdown.price_fit > 0
        assert breakdown.known_customer > 0
        assert breakdown.freshness > 0

    def test_matching_okpd2_beats_unrelated(self) -> None:
        match = LinearRanker().score(candidate(okpd2="20.11.11"), PROFILE)
        miss = LinearRanker().score(candidate(okpd2="31.01.11"), PROFILE)
        assert match.total > miss.total

    def test_sibling_okpd2_gets_partial_credit(self) -> None:
        """20.11.11 и 20.11.12 — соседние товары одной группы, это одна ниша."""
        sibling = LinearRanker().score(candidate(okpd2="20.11.12"), PROFILE)
        unrelated = LinearRanker().score(candidate(okpd2="31.01.11"), PROFILE)
        assert sibling.okpd2_match > 0
        assert sibling.okpd2_match > unrelated.okpd2_match

    def test_price_inside_usual_range_scores_full(self) -> None:
        inside = LinearRanker().score(candidate(price=Decimal("1000000")), PROFILE)
        far = LinearRanker().score(candidate(price=Decimal("500000000")), PROFILE)
        assert inside.price_fit > far.price_fit
        assert far.price_fit == 0.0

    def test_price_slightly_outside_decays_smoothly(self) -> None:
        """Закупка чуть дороже привычной всё ещё интересна — обрыва быть не должно."""
        slightly = LinearRanker().score(candidate(price=Decimal("1600000")), PROFILE)
        assert 0 < slightly.price_fit < LinearRanker().score(candidate(), PROFILE).price_fit

    def test_freshness_decays_with_age(self) -> None:
        fresh = LinearRanker().score(candidate(age_days=0.5), PROFILE)
        stale = LinearRanker().score(candidate(age_days=20), PROFILE)
        assert fresh.freshness > stale.freshness
        assert stale.freshness == 0.0

    def test_missing_data_does_not_crash(self) -> None:
        breakdown = LinearRanker().score(
            candidate(okpd2=None, price=None, inn=None), Profile()
        )
        assert breakdown.total >= 0

    def test_explanation_is_human_readable(self) -> None:
        explanation = LinearRanker().score(candidate(), PROFILE).explain()

        assert explanation["reasons"], "выдача без объяснения бесполезна пользователю"
        assert "similarity" in explanation["factors"]
        assert explanation["exploration"] is False

    def test_exploration_is_labelled(self) -> None:
        assert ScoreBreakdown(exploration=True).explain()["exploration"] is True


def recommendation(
    tender_id: int, inn: str | None, name: str, score: float = 1.0
) -> Recommendation:
    return Recommendation(
        candidate=candidate(tender_id=tender_id, inn=inn, name=name),
        score=score,
        breakdown=ScoreBreakdown(),
    )


class TestDiversification:
    def test_one_customer_cannot_take_over_the_feed(self) -> None:
        items = [recommendation(i, "7700000001", f"Закупка {i}") for i in range(20)]
        selected = _diversify(items, limit=20)
        assert len(selected) <= max(2, 20 // 4)

    def test_duplicate_lots_of_one_auction_are_collapsed(self) -> None:
        items = [
            recommendation(1, "7700000001", "Поставка ламп"),
            recommendation(2, "7700000001", "Поставка ламп"),
            recommendation(3, "7700000002", "Поставка мебели"),
        ]
        selected = _diversify(items, limit=10)
        assert [r.candidate.tender_id for r in selected] == [1, 3]

    def test_limit_is_respected(self) -> None:
        items = [recommendation(i, f"770000000{i}", f"Закупка {i}") for i in range(10)]
        assert len(_diversify(items, limit=3)) == 3


class StubProfiles:
    def __init__(self, profile: Profile) -> None:
        self._profile = profile

    async def load_profile(self) -> Profile:
        return self._profile

    async def load_signals(self):  # pragma: no cover
        raise NotImplementedError

    async def save_profile(self, profile):  # pragma: no cover
        raise NotImplementedError


class StubRecommendations:
    def __init__(self, similar: list, fresh: list) -> None:
        self._similar = similar
        self._fresh = fresh
        self.saved: list = []

    async def find_similar(self, embedding, limit, exclude):
        return [c for c in self._similar if c.tender_id not in exclude][:limit]

    async def find_fresh(self, limit, exclude):
        return [c for c in self._fresh if c.tender_id not in exclude][:limit]

    async def already_seen(self) -> set[int]:
        return set()

    async def save_impressions(self, recommendations) -> None:
        self.saved.extend(recommendations)

    async def record_feedback(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def record_view(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def record_win(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_cold_start_returns_fresh_tenders() -> None:
    """Без сигналов персонализировать нечего — честнее отдать свежие закупки."""
    fresh = [candidate(tender_id=i, inn=f"77000000{i}", name=f"Закупка {i}") for i in range(5)]
    repository = StubRecommendations(similar=[], fresh=fresh)

    results = await RecommendUseCase(
        StubProfiles(Profile(signal_count=0)), repository, LinearRanker()
    ).execute(limit=5)

    assert len(results) == 5
    assert repository.saved, "показанная выдача должна фиксироваться"


@pytest.mark.asyncio
async def test_personalized_feed_reserves_exploration_slots() -> None:
    """Без слотов исследования профиль схлопывается на уже понравившемся."""
    similar = [
        candidate(tender_id=i, inn=f"7700{i:04d}", name=f"Похожая закупка {i}")
        for i in range(1, 40)
    ]
    fresh = [
        candidate(tender_id=100 + i, inn=f"7800{i:04d}", name=f"Другая закупка {i}")
        for i in range(10)
    ]

    results = await RecommendUseCase(
        StubProfiles(PROFILE), StubRecommendations(similar, fresh), LinearRanker()
    ).execute(limit=20)

    exploration = [r for r in results if r.breakdown.exploration]
    assert exploration, "часть выдачи должна уходить на исследование"
    assert len(results) <= 20


@pytest.mark.asyncio
async def test_results_are_ordered_by_score() -> None:
    similar = [
        candidate(tender_id=1, inn="7700000001", name="Точное совпадение", similarity=0.95),
        candidate(
            tender_id=2,
            inn="7700000002",
            name="Слабое совпадение",
            similarity=0.2,
            okpd2="31.01.11",
            price=Decimal("400000000"),
        ),
    ]

    results = await RecommendUseCase(
        StubProfiles(PROFILE), StubRecommendations(similar, []), LinearRanker()
    ).execute(limit=4)

    assert results[0].candidate.tender_id == 1

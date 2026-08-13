"""Формирование персональных рекомендаций."""

from __future__ import annotations

from libs.shared.logging import get_logger
from services.recsys_service.application.ports import (
    ProfileRepositoryPort,
    RankerPort,
    RecommendationRepositoryPort,
)
from services.recsys_service.domain.models import (
    EXPLORATION_RATIO,
    Recommendation,
    RecommendationCandidate,
    ScoreBreakdown,
)

log = get_logger(__name__)

# Кандидатов берём с запасом: ранжирование и диверсификация переупорядочивают
# выдачу, и лучший ответ может лежать вне первой десятки ANN-поиска.
CANDIDATE_FACTOR = 6
MAX_CANDIDATES = 300

# Порог косинусной близости, выше которого две закупки считаются
# «про одно и то же». Нужен, чтобы выдача не состояла из десяти лотов одного
# аукциона, разбитого по позициям.
DUPLICATE_SIMILARITY = 0.97


class RecommendUseCase:
    """Кандидаты по профилю → ранжирование → диверсификация → объяснение."""

    def __init__(
        self,
        profiles: ProfileRepositoryPort,
        recommendations: RecommendationRepositoryPort,
        ranker: RankerPort,
        exploration_ratio: float = EXPLORATION_RATIO,
    ) -> None:
        self._profiles = profiles
        self._recommendations = recommendations
        self._ranker = ranker
        self._exploration_ratio = exploration_ratio

    async def execute(self, limit: int = 20, record: bool = True) -> list[Recommendation]:
        profile = await self._profiles.load_profile()
        seen = await self._recommendations.already_seen()

        if not profile.is_usable:
            # Холодный старт: без сигналов персонализировать нечего, отдаём
            # свежие активные закупки — это честнее случайной выдачи.
            log.info("recommend.cold_start", signals=profile.signal_count)
            fresh = await self._recommendations.find_fresh(limit, seen)
            results = [
                Recommendation(
                    candidate=candidate,
                    score=self._ranker.score(candidate, profile).total,
                    breakdown=self._ranker.score(candidate, profile),
                )
                for candidate in fresh
            ]
            if record and results:
                await self._recommendations.save_impressions(results)
            return results

        assert profile.embedding is not None
        pool_size = min(limit * CANDIDATE_FACTOR, MAX_CANDIDATES)
        candidates = await self._recommendations.find_similar(profile.embedding, pool_size, seen)

        scored = [
            Recommendation(
                candidate=candidate,
                score=(breakdown := self._ranker.score(candidate, profile)).total,
                breakdown=breakdown,
            )
            for candidate in candidates
        ]
        scored.sort(key=lambda r: r.score, reverse=True)

        exploration_slots = max(1, int(limit * self._exploration_ratio)) if limit > 4 else 0
        results = _diversify(scored, limit - exploration_slots)

        if exploration_slots:
            shown = seen | {r.candidate.tender_id for r in results}
            results.extend(await self._explore(exploration_slots, shown))

        if record and results:
            await self._recommendations.save_impressions(results)

        log.info(
            "recommend.done",
            returned=len(results),
            exploration=exploration_slots,
            pool=len(candidates),
        )
        return results

    async def _explore(self, slots: int, exclude: set[int]) -> list[Recommendation]:
        """Слоты под исследование заполняются свежими закупками вне профиля.

        Без этого система показывает только похожее на уже понравившееся и
        перестаёт находить новые ниши.
        """
        fresh = await self._recommendations.find_fresh(slots, exclude)
        return [
            Recommendation(
                candidate=candidate,
                score=0.0,
                breakdown=ScoreBreakdown(exploration=True),
            )
            for candidate in fresh
        ]


def _diversify(scored: list[Recommendation], limit: int) -> list[Recommendation]:
    """Убирает почти одинаковые закупки и не даёт одному заказчику занять выдачу."""
    selected: list[Recommendation] = []
    per_customer: dict[str, int] = {}
    max_per_customer = max(2, limit // 4)

    for item in scored:
        if len(selected) >= limit:
            break

        inn = item.candidate.customer_inn
        if inn and per_customer.get(inn, 0) >= max_per_customer:
            continue

        if any(_is_near_duplicate(item, chosen) for chosen in selected):
            continue

        selected.append(item)
        if inn:
            per_customer[inn] = per_customer.get(inn, 0) + 1

    return selected


def _is_near_duplicate(left: Recommendation, right: Recommendation) -> bool:
    """Лоты одного аукциона отличаются номером, но не сутью."""
    if abs(left.candidate.similarity - right.candidate.similarity) > 1 - DUPLICATE_SIMILARITY:
        return False
    return (
        left.candidate.customer_inn is not None
        and left.candidate.customer_inn == right.candidate.customer_inn
        and _same_subject(left.candidate, right.candidate)
    )


def _same_subject(left: RecommendationCandidate, right: RecommendationCandidate) -> bool:
    a = (left.name or "").lower().strip()
    b = (right.name or "").lower().strip()
    return bool(a) and a == b

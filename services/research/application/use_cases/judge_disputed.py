"""Разбор закупок: сначала правила, затем модель — и только по спорным.

Порядок здесь и есть экономия. На размеченном наборе правила по контексту
решают 68 закупок из 76, включая все 20 ложных срабатываний; модели достаётся
восемь. Звать её на каждую закупку значило бы платить за 76 ответов там, где
нужно восемь, и получать те же выводы.

Три свойства, без которых прогон на тысячах закупок нерабочий.

**Кэш.** Повторный прогон не тратит токенов: решение помнится по закупке вместе
с версиями критериев и промпта.

**Потолок одновременности.** Берётся из уровня нагрузки: на фоновом уровне
модель дёргают по одной закупке, на полном — по восемь.

**Остановка при отказе модели.** Лежащая модель — не свойство закупки, и
перебирать на ней очередь бессмысленно. Уже сохранённые вердикты при этом не
теряются.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from libs.shared.load_control import AdjustableSemaphore
from libs.shared.logging import get_logger
from services.research.application.ports import (
    ModelJudgePort,
    ModelUnavailable,
    TenderCandidate,
    TenderVerdict,
    VerdictCachePort,
)
from services.research.application.prompts import (
    JUDGE_SYSTEM,
    JUDGE_USER,
    render_card,
    render_hits,
)
from services.research.domain.confidence import judge_tender
from services.research.domain.criteria import Confidence, Criteria, TermRole
from services.research.domain.hits import Hit
from services.research.domain.verdict import JUDGE_PROMPT_VERSION, ModelVerdict

log = get_logger(__name__)


class _Status(StrEnum):
    """Чем кончилась попытка спросить модель об одной закупке."""

    DONE = "done"
    #: Модель ответила невнятно — это свойство закупки, соседи не виноваты.
    FAILED = "failed"
    #: До закупки не дошли: модель легла раньше.
    NOT_REACHED = "not_reached"


@dataclass(frozen=True, slots=True)
class _Attempt:
    status: _Status
    verdict: TenderVerdict | None = None


@dataclass(slots=True)
class Funnel:
    """Сколько закупок прошло каждый этап.

    Знаменатель обязателен. Ретроспектива описывает, как его отсутствие ведёт к
    ложным выводам: «в приоритетах 3 и 9 ноль находок» ничего не значило,
    потому что в них было разобрано ровно 0%. Отрицательный результат имеет
    смысл только при известном знаменателе.
    """

    total: int = 0
    #: Отсеяно правилами — без обращения к модели.
    rejected_by_rules: int = 0
    #: Подтверждено правилами — тоже без модели.
    confirmed_by_rules: int = 0
    #: Спорные: их и разбирает модель.
    disputed: int = 0
    #: Из спорных — взято из кэша.
    from_cache: int = 0
    #: Из спорных — спрошено у модели.
    asked_model: int = 0
    #: Спорные, до которых не дошли: модель легла.
    not_reached: int = 0
    failed: int = 0

    def check(self) -> bool:
        """Сумма по этапам обязана сходиться с общим числом."""
        return (
            self.rejected_by_rules + self.confirmed_by_rules + self.disputed == self.total
            and self.from_cache + self.asked_model + self.not_reached + self.failed
            == self.disputed
        )


@dataclass(slots=True)
class JudgeOutcome:
    verdicts: list[TenderVerdict] = field(default_factory=list)
    funnel: Funnel = field(default_factory=Funnel)
    #: Модель легла на середине — остаток очереди не разобран.
    interrupted: bool = False


class JudgeDisputedUseCase:
    """Controller разбора: правила, кэш, модель — в этом порядке."""

    def __init__(
        self,
        criteria: Criteria,
        model: ModelJudgePort,
        cache: VerdictCachePort | None = None,
        concurrency: int = 1,
    ) -> None:
        self._criteria = criteria
        self._model = model
        self._cache = cache
        self._limit = AdjustableSemaphore(concurrency)

    async def set_concurrency(self, concurrency: int) -> None:
        await self._limit.resize(concurrency)

    async def execute(self, candidates: Sequence[TenderCandidate]) -> JudgeOutcome:
        outcome = JudgeOutcome()
        outcome.funnel.total = len(candidates)

        disputed: list[TenderCandidate] = []
        for candidate in candidates:
            judgement = judge_tender(candidate.hits, self._criteria)
            if judgement.confidence is Confidence.DISPUTED:
                disputed.append(candidate)
                continue

            if judgement.confidence is Confidence.CONFIRMED:
                outcome.funnel.confirmed_by_rules += 1
            else:
                outcome.funnel.rejected_by_rules += 1
            outcome.verdicts.append(
                TenderVerdict(
                    tender_id=candidate.tender_id,
                    confidence=judgement.confidence,
                    reason=judgement.reason,
                    score=1.0 if judgement.confidence is Confidence.CONFIRMED else 0.0,
                    decided_by="rules",
                )
            )

        outcome.funnel.disputed = len(disputed)
        if not disputed:
            return outcome

        cached = await self._load_cache([c.tender_id for c in disputed])
        pending = []
        for candidate in disputed:
            found = cached.get(candidate.tender_id)
            if found is None:
                pending.append(candidate)
                continue
            outcome.funnel.from_cache += 1
            outcome.verdicts.append(found)

        await self._ask_model(pending, outcome)

        log.info(
            "research.judged",
            total=outcome.funnel.total,
            by_rules=outcome.funnel.confirmed_by_rules + outcome.funnel.rejected_by_rules,
            from_cache=outcome.funnel.from_cache,
            asked_model=outcome.funnel.asked_model,
            interrupted=outcome.interrupted,
        )
        return outcome

    async def _load_cache(self, tender_ids: Sequence[int]) -> dict[int, TenderVerdict]:
        if self._cache is None:
            return {}
        return await self._cache.cached(
            tender_ids, self._criteria.version, JUDGE_PROMPT_VERSION
        )

    async def _ask_model(
        self, candidates: Sequence[TenderCandidate], outcome: JudgeOutcome
    ) -> None:
        if not candidates:
            return

        stopped = asyncio.Event()

        async def judge_one(candidate: TenderCandidate) -> _Attempt:
            if stopped.is_set():
                return _Attempt(_Status.NOT_REACHED)
            async with self._limit:
                if stopped.is_set():
                    return _Attempt(_Status.NOT_REACHED)
                try:
                    return _Attempt(_Status.DONE, await self._judge(candidate))
                except ModelUnavailable as exc:
                    # Лежащая модель — не свойство закупки. Останавливаемся,
                    # чтобы не сжечь очередь одинаковыми ошибками.
                    log.error("research.model_down", error=str(exc))
                    stopped.set()
                    return _Attempt(_Status.NOT_REACHED)
                except Exception as exc:
                    log.warning(
                        "research.judge_failed",
                        tender_id=candidate.tender_id,
                        error=str(exc),
                    )
                    return _Attempt(_Status.FAILED)

        for attempt in await asyncio.gather(*(judge_one(c) for c in candidates)):
            if attempt.status is _Status.FAILED:
                outcome.funnel.failed += 1
            elif attempt.status is _Status.NOT_REACHED:
                outcome.funnel.not_reached += 1
            elif attempt.verdict is not None:
                outcome.funnel.asked_model += 1
                outcome.verdicts.append(attempt.verdict)

        outcome.interrupted = stopped.is_set()

    async def _judge(self, candidate: TenderCandidate) -> TenderVerdict:
        # В модель уходят только основные находки: вспомогательные ничего не
        # решают, а место в контексте занимают.
        hits = [hit for hit in candidate.hits if hit.role is TermRole.PRIMARY]
        hits = hits[: self._criteria.max_hits_per_document]

        verdict = await self._model.judge(
            JUDGE_SYSTEM,
            JUDGE_USER.format(
                criteria=self._criteria.name,
                card=render_card(
                    candidate.name,
                    candidate.description,
                    candidate.customer_name,
                    candidate.okpd2_code,
                ),
                hits=render_hits(hits),
            ),
        )

        evidence = verify_evidence(verdict, hits)
        result = TenderVerdict(
            tender_id=candidate.tender_id,
            confidence=Confidence.CONFIRMED if verdict.match else Confidence.REJECTED,
            reason=verdict.reasoning or "решение модели",
            score=verdict.score,
            decided_by="model",
            evidence=evidence,
        )

        if self._cache is not None:
            await self._cache.save(
                result, self._criteria.version, JUDGE_PROMPT_VERSION, self._model.model_name
            )
        return result


def verify_evidence(verdict: ModelVerdict, hits: Sequence[Hit]) -> list[dict[str, object]]:
    """Отбрасывает цитаты, которых модели не показывали.

    Модель охотно «цитирует» правдоподобный, но отсутствующий текст. Ссылка на
    источник ценна ровно тем, что по ней можно проверить вывод, поэтому
    непроверяемая ссылка хуже её отсутствия.
    """
    verified: list[dict[str, object]] = []
    for item in verdict.evidence:
        index = item.hit_number - 1
        if not 0 <= index < len(hits):
            continue

        hit = hits[index]
        quote = item.quote.strip()
        if quote and quote not in hit.quote:
            log.info("research.quote_not_found", hit_number=item.hit_number)
            continue

        verified.append(
            {
                "hit_number": item.hit_number,
                "quote": quote or hit.quote,
                "file_name": hit.file_name,
                "page": hit.page,
            }
        )
    return verified

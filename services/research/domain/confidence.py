"""Что контекст говорит о находке.

Regex находит буквы, а не смысл. Решение о том, относится ли совпадение к делу,
принимается по окружению — и в подавляющем большинстве случаев принимается
однозначно. Проверено на размеченном наборе: правила ниже отделяют 56
подтверждённых закупок от 20 отклонённых, не обращаясь к модели.

Смысл этапа не в том, чтобы заменить судью, а в том, чтобы **не звать его
попусту**. Уверенные случаи решаются здесь и бесплатно, спорные — уходят
модели с цитатами, а не с документами.

Три правила, и они применяются именно в этом порядке.

1. **Только вспомогательный термин — не находка.** Закупка, где сработало
   одно «потребление кислорода» и ни разу ХПК или БПК, отвергается сразу. Замер:
   таких закупок в наборе шесть, все шесть медицинские, и ни одной
   подтверждённой среди них нет.

2. **Окружение против.** «Кровля БПК ФКУ СИЗО-12», «цехах ХПК Мариинского
   театра», «блок питания БПК-01» — здесь аббревиатура означает организацию или
   изделие. Смотрится узкое окно вокруг совпадения: эти слова стоят вплотную, а
   на всей цитате в ±220 символов найдётся что угодно.

3. **Окружение за.** `мг/дм³`, `ПДК`, `сточные воды`, `отбор проб` — это
   показатель качества воды.

Не сработало ничего — спорно, и решать модели.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from services.research.domain.criteria import Confidence, Criteria, TermRole
from services.research.domain.hits import Hit


@dataclass(frozen=True, slots=True)
class Judgement:
    """Решение по находке или по закупке вместе с его основанием.

    Основание обязательно: вердикт без объяснения невозможно ни проверить, ни
    оспорить, а классификация в прогоне держалась именно на том, что причину
    было видно.
    """

    confidence: Confidence
    reason: str

    @property
    def needs_model(self) -> bool:
        return self.confidence is Confidence.DISPUTED


def judge_hit(hit: Hit, criteria: Criteria) -> Judgement:
    """Решение по одной находке — по её окружению."""
    for rule in criteria.context_rules:
        if rule.verdict is not Confidence.REJECTED:
            continue
        if _matches(rule.pattern, hit, rule.window):
            return Judgement(Confidence.REJECTED, rule.name)

    for rule in criteria.context_rules:
        if rule.verdict is not Confidence.CONFIRMED:
            continue
        if _matches(rule.pattern, hit, rule.window):
            return Judgement(Confidence.CONFIRMED, rule.name)

    return Judgement(Confidence.DISPUTED, "контекст не распознан")


def judge_tender(hits: Sequence[Hit], criteria: Criteria) -> Judgement:
    """Решение по закупке — по всем её находкам сразу.

    Находок у закупки несколько, и они могут расходиться: в одном документе
    «БПК» стоит рядом с ПДК, в другом — в названии здания. Достаточно одной
    уверенно подтверждённой: показатель, упомянутый хоть где-то по делу, делает
    закупку релевантной, а совпадение в названии объекта этого не отменяет.
    """
    if not hits:
        return Judgement(Confidence.REJECTED, "совпадений нет")

    if not any(hit.role is TermRole.PRIMARY for hit in hits):
        # Шесть закупок в размеченном наборе, все медицинские.
        return Judgement(
            Confidence.REJECTED, "только вспомогательный термин без ХПК/БПК"
        )

    # Вспомогательные находки в разборе не участвуют: они усиливают основные,
    # но собственного веса не имеют — иначе «потребление кислорода» в медицинском
    # ТЗ перетянуло бы решение на себя.
    primary = [hit for hit in hits if hit.role is TermRole.PRIMARY]
    judgements = [judge_hit(hit, criteria) for hit in primary]

    for judgement in judgements:
        if judgement.confidence is Confidence.CONFIRMED:
            return Judgement(Confidence.CONFIRMED, judgement.reason)

    if all(j.confidence is Confidence.REJECTED for j in judgements):
        return Judgement(Confidence.REJECTED, judgements[0].reason)

    return Judgement(Confidence.DISPUTED, "контекст не распознан")


def _matches(pattern: re.Pattern[str], hit: Hit, window: int | None) -> bool:
    """Ищет маркер в цитате целиком или в узком окне вокруг совпадения."""
    if window is None:
        return bool(pattern.search(hit.quote))

    start = max(0, hit.match_start - window)
    end = min(len(hit.quote), hit.match_end + window)
    return bool(pattern.search(hit.quote[start:end]))

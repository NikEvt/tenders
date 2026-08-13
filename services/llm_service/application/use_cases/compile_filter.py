"""Свободный текст → критерий отбора.

Модель просят выдать регулярные выражения, и она в них ошибается: незакрытая
скобка, лишний квантификатор. Такой шаблон нельзя ни применить, ни молча
выбросить — критерий с потерянным термином ищет не то, о чём просили, и
выглядит при этом рабочим. Поэтому каждый шаблон компилируется здесь же, битые
отбрасываются с записью в лог, а критерий без единого основного термина
считается непригодным и до сохранения не доходит.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from libs.shared.contracts.criteria_spec import CriteriaSpec, TermSpec
from libs.shared.logging import get_logger
from services.llm_service.application.ports import (
    FilterRepositoryPort,
    LlmPort,
    LlmUnavailable,
)
from services.llm_service.application.prompts import (
    COMPILE_FILTER_SYSTEM,
    COMPILE_FILTER_USER,
)

log = get_logger(__name__)

# Разряды, которые пользователи пишут в запросах: «до 1 млн», «от 500к».
_MULTIPLIERS = {
    "млрд": Decimal(1_000_000_000),
    "млн": Decimal(1_000_000),
    "тыс": Decimal(1_000),
    "к": Decimal(1_000),
    "кк": Decimal(1_000_000),
}
_AMOUNT = re.compile(
    r"(?P<bound>до|не\s+более|максимум|от|не\s+менее|минимум)\s+"
    r"(?P<value>\d[\d\s.,]*)\s*(?P<unit>млрд|млн|тыс|кк|к)?",
    re.IGNORECASE,
)
_UPPER_BOUNDS = {"до", "не более", "максимум"}


def parse_budget(query: str) -> tuple[Decimal | None, Decimal | None]:
    """Извлекает бюджет арифметически, не полагаясь на модель.

    Модель систематически ошибается в разрядах («1млн» → 1000000000), а бюджет —
    жёсткое условие: промах здесь сразу выбрасывает нужные закупки из выдачи.
    """
    price_min: Decimal | None = None
    price_max: Decimal | None = None

    for match in _AMOUNT.finditer(query):
        raw = match.group("value").replace(" ", "").replace("\xa0", "").replace(",", ".")
        raw = raw.rstrip(".")
        try:
            value = Decimal(raw)
        except Exception:
            continue

        unit = (match.group("unit") or "").lower()
        if unit:
            value *= _MULTIPLIERS[unit]

        bound = re.sub(r"\s+", " ", match.group("bound").lower())
        if bound in _UPPER_BOUNDS:
            price_max = value if price_max is None else min(price_max, value)
        else:
            price_min = value if price_min is None else max(price_min, value)

    return price_min, price_max


class CompileFilterUseCase:
    """Превращает «закупки с упоминанием ХПК в анализах воды» в критерий."""

    def __init__(self, llm: LlmPort, repository: FilterRepositoryPort) -> None:
        self._llm = llm
        self._repository = repository

    async def compile(self, query: str, today: date | None = None) -> CriteriaSpec:
        moment = today or date.today()

        try:
            spec = await self._llm.structured(
                system=COMPILE_FILTER_SYSTEM,
                user=COMPILE_FILTER_USER.format(query=query, today=moment.isoformat()),
                schema=CriteriaSpec,
            )
        except LlmUnavailable:
            # Деградация: без модели остаются буквальные слова запроса. Правил
            # по контексту при этом нет, поэтому спорным окажется всё — и это
            # честнее, чем выдумать правила, которых никто не просил.
            log.warning("compile_filter.llm_unavailable, откат на слова запроса")
            spec = CriteriaSpec(name=query[:60], terms=_fallback_terms(query))

        spec = _drop_broken_patterns(spec)
        if not spec.name.strip():
            spec.name = query[:60]

        log.info(
            "compile_filter.done",
            terms=[t.name for t in spec.terms],
            context_rules=len(spec.context_rules),
            okpd2=spec.okpd2_prefixes,
            usable=spec.is_usable,
        )
        return spec

    async def compile_and_save(
        self, name: str, query: str, spec: CriteriaSpec | None = None
    ) -> tuple[int, CriteriaSpec]:
        """Сохраняет критерий, компилируя текст только если спецификации нет.

        Готовый `spec` приходит из конструктора: пользователь поправил шаблон,
        добавил правило, сменил роль термина. Перекомпиляция текста откатила бы
        эти правки — то есть молча потеряла бы работу пользователя.
        """
        if spec is None:
            spec = await self.compile(query)

        if not spec.is_usable:
            # Сохранить непригодный критерий значит завести фильтр, который
            # никогда ничего не найдёт и не скажет почему.
            raise CriteriaNotUsable(
                "В критерии нет ни одного основного термина — искать нечего"
            )

        filter_id = await self._repository.save_spec(name, query, spec)
        return filter_id, spec


class CriteriaNotUsable(ValueError):
    """Критерий не найдёт ничего — сохранять его бессмысленно."""


def _drop_broken_patterns(spec: CriteriaSpec) -> CriteriaSpec:
    """Отбрасывает шаблоны, которые не компилируются.

    Молча оставить битый шаблон нельзя: движок откажется собирать критерий
    целиком, и фильтр будет падать в лог на каждом прогоне.
    """
    terms = []
    for term in spec.terms:
        if _compiles(term.pattern):
            terms.append(term)
        else:
            log.warning("compile_filter.bad_term_pattern", term=term.name)

    rules = []
    for rule in spec.context_rules:
        if _compiles(rule.pattern):
            rules.append(rule)
        else:
            log.warning("compile_filter.bad_rule_pattern", rule=rule.name)

    card = spec.card_pattern
    if card and not _compiles(card):
        log.warning("compile_filter.bad_card_pattern")
        card = None

    return spec.model_copy(update={"terms": terms, "context_rules": rules,
                                   "card_pattern": card})


def _compiles(pattern: str) -> bool:
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _fallback_terms(query: str) -> list[TermSpec]:
    """Буквальные слова запроса как термины — режим без модели."""
    return [
        TermSpec(name=word, pattern=re.escape(word) + r"\w*", role="primary")
        for word in _fallback_keywords(query)[:5]
    ]


def _fallback_keywords(query: str) -> list[str]:
    """Простейшая токенизация на случай недоступности модели."""
    stop = {"и", "или", "для", "в", "на", "с", "по", "до", "от", "руб", "рублей", "закупки"}
    words = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", query)
    return [w for w in words if w.lower() not in stop][:10]

"""Компиляция свободного текста в критерий отбора.

Формат сменился: раньше модель выдавала ключевые слова и критерий для судьи,
теперь — термины регулярными выражениями, роли и правила по контексту. Причина
в замере: точность держится на правилах по контексту, а вывести их из списка
слов невозможно.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import BaseModel

from libs.shared.contracts.criteria_spec import CriteriaSpec, StructuralSpec, TermSpec
from services.llm_service.application.ports import LlmPort, LlmUnavailable
from services.llm_service.application.use_cases.compile_filter import (
    CompileFilterUseCase,
    parse_budget,
)


class ScriptedLlm(LlmPort):
    """Отдаёт заранее заданный объект или падает — сеть в тестах не нужна."""

    def __init__(self, response: BaseModel | None = None, fail: bool = False) -> None:
        self._response = response
        self._fail = fail
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "scripted"

    async def complete(self, system, user, max_tokens=2000, reasoning_effort=None) -> str:
        if self._fail:
            raise LlmUnavailable("модель недоступна")
        return "текст"

    async def structured(self, system, user, schema, max_tokens=2000, reasoning_effort=None):
        self.calls += 1
        if self._fail:
            raise LlmUnavailable("модель недоступна")
        assert self._response is not None
        return self._response


class StubFilterRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, CriteriaSpec]] = []

    async def save_compiled(self, name: str, nl_query: str, spec: CriteriaSpec) -> int:
        self.saved.append((name, nl_query, spec))
        return len(self.saved)

    async def save_spec(self, name: str, nl_query: str, spec: CriteriaSpec) -> int:
        return await self.save_compiled(name, nl_query, spec)

    async def get_spec(self, filter_id: int):  # pragma: no cover - не нужен в этих тестах
        raise NotImplementedError

    async def active_filters(self):  # pragma: no cover
        raise NotImplementedError

    async def cached_verdict_tender_ids(self, filter_id, prompt_version):  # pragma: no cover
        raise NotImplementedError

    async def save_verdict(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


class TestParseBudget:
    """Бюджет разбирается арифметически: модель систематически путает разряды."""

    @pytest.mark.parametrize(
        ("query", "expected_max"),
        [
            ("бюджет закупки до 1млн руб", Decimal(1_000_000)),
            ("до 1 млн рублей", Decimal(1_000_000)),
            ("не более 500 тыс", Decimal(500_000)),
            ("максимум 2,5 млн", Decimal(2_500_000)),
            ("до 300к", Decimal(300_000)),
            ("до 1 500 000 руб", Decimal(1_500_000)),
            ("до 1млрд", Decimal(1_000_000_000)),
        ],
    )
    def test_upper_bound(self, query: str, expected_max: Decimal) -> None:
        _, price_max = parse_budget(query)
        assert price_max == expected_max

    @pytest.mark.parametrize(
        ("query", "expected_min"),
        [
            ("от 500 тыс рублей", Decimal(500_000)),
            ("не менее 2 млн", Decimal(2_000_000)),
            ("минимум 100000", Decimal(100_000)),
        ],
    )
    def test_lower_bound(self, query: str, expected_min: Decimal) -> None:
        price_min, _ = parse_budget(query)
        assert price_min == expected_min

    def test_range(self) -> None:
        price_min, price_max = parse_budget("от 500 тыс до 3 млн рублей")
        assert price_min == Decimal(500_000)
        assert price_max == Decimal(3_000_000)

    def test_no_budget_mentioned(self) -> None:
        assert parse_budget("найти тендеры на ХПК") == (None, None)

    def test_narrowest_bound_wins(self) -> None:
        _, price_max = parse_budget("до 5 млн, но лучше до 1 млн")
        assert price_max == Decimal(1_000_000)


@pytest.mark.asyncio
async def test_gas_query_compiles_to_terms_and_rules() -> None:
    llm = ScriptedLlm(
        CriteriaSpec(
            name="Газ в баллонах",
            terms=[
                TermSpec(name="газ", pattern=r"газ\w*"),
                TermSpec(name="баллон", pattern=r"баллон\w*", role="supporting"),
            ],
            context_rules=[],
            okpd2_prefixes=["20.11"],
            structural=StructuralSpec(price_max=Decimal(1_000_000)),
        )
    )

    spec = await CompileFilterUseCase(llm, StubFilterRepository()).compile(
        "поставка газа в баллонах, бюджет закупки до 1млн руб"
    )

    assert [t.name for t in spec.terms] == ["газ", "баллон"]
    assert spec.terms[1].role == "supporting"
    assert spec.okpd2_prefixes == ["20.11"]
    assert spec.is_usable


@pytest.mark.asyncio
async def test_broken_pattern_is_dropped_not_kept() -> None:
    """Битый шаблон уронил бы сборку критерия на каждом прогоне."""
    llm = ScriptedLlm(
        CriteriaSpec(
            name="x",
            terms=[
                TermSpec(name="хороший", pattern=r"ХПК"),
                TermSpec(name="битый", pattern="([a"),
            ],
        )
    )

    spec = await CompileFilterUseCase(llm, StubFilterRepository()).compile("хпк")

    assert [t.name for t in spec.terms] == ["хороший"]


@pytest.mark.asyncio
async def test_falls_back_to_query_words_when_model_is_down() -> None:
    """Без модели критерий беднее, но рабочий: правил по контексту нет, спорным
    окажется всё — и это честнее, чем выдумать правила, которых не просили."""
    use_case = CompileFilterUseCase(ScriptedLlm(fail=True), StubFilterRepository())

    spec = await use_case.compile("поставка газа в баллонах")

    assert spec.is_usable
    assert spec.context_rules == []
    assert any("газ" in term.name for term in spec.terms)


@pytest.mark.asyncio
async def test_name_defaults_to_the_query() -> None:
    llm = ScriptedLlm(CriteriaSpec(terms=[TermSpec(name="газ", pattern="газ")]))
    spec = await CompileFilterUseCase(llm, StubFilterRepository()).compile("поставка газа")
    assert spec.name == "поставка газа"


@pytest.mark.asyncio
async def test_compile_and_save_persists_the_criteria() -> None:
    repository = StubFilterRepository()
    llm = ScriptedLlm(
        CriteriaSpec(name="Газ", terms=[TermSpec(name="газ", pattern=r"газ\w*")])
    )

    filter_id, _ = await CompileFilterUseCase(llm, repository).compile_and_save(
        "Газ в баллонах", "поставка газа"
    )

    assert filter_id == 1
    assert repository.saved[0][0] == "Газ в баллонах"
    assert [t.name for t in repository.saved[0][2].terms] == ["газ"]


@pytest.mark.asyncio
async def test_today_is_passed_to_the_model() -> None:
    llm = ScriptedLlm(CriteriaSpec(terms=[TermSpec(name="т", pattern="т")]))
    await CompileFilterUseCase(llm, StubFilterRepository()).compile(
        "закупки за прошлую неделю", today=date(2026, 8, 7)
    )
    assert llm.calls == 1

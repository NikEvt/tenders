"""Цепочка «компиляция → сохранение → движок отбора» не должна расходиться.

Она уже расходилась: `/filters/compile` отдавал один формат, движок принимал
другой, и фильтр, собранный в интерфейсе, молча ничего не находил. Задание при
этом оставалось в `running` навсегда.

Здесь два сторожа: формат совпадает, и непригодный критерий останавливают до
того, как он превратится в вечно идущий прогон.
"""

from __future__ import annotations

import pytest

from libs.shared.contracts.criteria_spec import ContextRuleSpec, CriteriaSpec, TermSpec
from services.llm_service.application.use_cases.compile_filter import (
    CriteriaNotUsable,
    _drop_broken_patterns,
    _fallback_terms,
)
from services.research.domain.criteria import CriteriaError, criteria_from_spec
from services.research.domain.hits import find_hits


def water_spec() -> CriteriaSpec:
    return CriteriaSpec(
        name="ХПК в воде",
        terms=[
            TermSpec(name="ХПК", pattern=r"(?<![А-Яа-яA-Za-z])[ХX][Пп][КK]"),
            TermSpec(
                name="потребление кислорода",
                pattern=r"потреблени\w*\s+кислород\w*",
                role="supporting",
            ),
        ],
        context_rules=[
            ContextRuleSpec(
                name="название объекта",
                pattern="кровл|здани|театр",
                verdict="rejected",
                window=60,
            ),
            ContextRuleSpec(
                name="химия воды", pattern=r"мг\s*/\s*дм|ПДК|сточн", verdict="confirmed"
            ),
        ],
        card_pattern="вод|сточн|лаборатор",
        okpd2_prefixes=["36.", "37."],
        version="v1",
    )


class TestFormatsMatch:
    def test_compiled_spec_is_accepted_by_the_engine(self) -> None:
        """То, что разошлось однажды и сделало фильтры нерабочими."""
        criteria = criteria_from_spec(water_spec().model_dump(mode="json"))

        assert [term.name for term in criteria.terms] == ["ХПК", "потребление кислорода"]
        assert criteria.card_pattern is not None
        assert criteria.okpd2_prefixes == ("36.", "37.")

    def test_roles_survive_the_round_trip(self) -> None:
        """Роль решает судьбу закупки — потерять её значит изменить результат."""
        criteria = criteria_from_spec(water_spec().model_dump(mode="json"))
        assert [str(term.role) for term in criteria.terms] == ["primary", "supporting"]

    def test_context_rule_window_survives(self) -> None:
        criteria = criteria_from_spec(water_spec().model_dump(mode="json"))
        rejecting = next(r for r in criteria.context_rules if r.name == "название объекта")
        assert rejecting.window == 60

    def test_compiled_criteria_actually_finds_things(self) -> None:
        """Сквозная проверка: спецификация → критерий → находка."""
        criteria = criteria_from_spec(water_spec().model_dump(mode="json"))
        hits = find_hits("Показатель ХПК не более 30 мг/дм3", criteria)

        assert [hit.term for hit in hits] == ["ХПК"]


class TestUnusableCriteriaIsRefused:
    def test_spec_without_primary_terms_is_not_usable(self) -> None:
        spec = CriteriaSpec(
            name="только вспомогательный",
            terms=[TermSpec(name="х", pattern="х", role="supporting")],
        )
        assert spec.is_usable is False

    def test_empty_spec_is_not_usable(self) -> None:
        assert CriteriaSpec(name="пусто").is_usable is False

    def test_engine_refuses_a_criteria_without_terms(self) -> None:
        with pytest.raises(CriteriaError, match="без терминов"):
            criteria_from_spec({"name": "пусто", "terms": []})


class TestBrokenPatternsAreDropped:
    def test_broken_term_is_removed(self) -> None:
        """Битый шаблон нельзя ни применить, ни оставить: движок откажется весь."""
        spec = CriteriaSpec(
            name="x",
            terms=[
                TermSpec(name="хороший", pattern=r"ХПК"),
                TermSpec(name="битый", pattern="([a"),
            ],
        )
        cleaned = _drop_broken_patterns(spec)

        assert [term.name for term in cleaned.terms] == ["хороший"]
        assert cleaned.is_usable

    def test_broken_rule_is_removed_but_terms_stay(self) -> None:
        spec = CriteriaSpec(
            name="x",
            terms=[TermSpec(name="т", pattern="ХПК")],
            context_rules=[ContextRuleSpec(name="битое", pattern="([a")],
        )
        cleaned = _drop_broken_patterns(spec)

        assert cleaned.context_rules == []
        assert len(cleaned.terms) == 1

    def test_broken_card_pattern_falls_back_to_none(self) -> None:
        """Предфильтр — не обязательное поле: без него просто читают больше."""
        spec = CriteriaSpec(
            name="x", terms=[TermSpec(name="т", pattern="ХПК")], card_pattern="([a"
        )
        assert _drop_broken_patterns(spec).card_pattern is None

    def test_everything_broken_leaves_an_unusable_spec(self) -> None:
        """И это правильно: пустой критерий обязан быть отвергнут, а не сохранён."""
        spec = CriteriaSpec(name="x", terms=[TermSpec(name="т", pattern="([a")])
        assert _drop_broken_patterns(spec).is_usable is False


class TestDegradedCompilation:
    def test_fallback_builds_usable_terms_from_the_query(self) -> None:
        """Без модели остаются слова запроса — искать хоть что-то можно."""
        terms = _fallback_terms("поставка реагентов для лаборатории")

        assert terms
        assert all(term.role == "primary" for term in terms)
        criteria = criteria_from_spec(
            CriteriaSpec(name="x", terms=terms).model_dump(mode="json")
        )
        assert find_hits("поставка реагентов", criteria)

    def test_fallback_escapes_regex_metacharacters(self) -> None:
        """Слово из запроса — литерал, а не шаблон: «(» не должна ломать критерий."""
        terms = _fallback_terms("анализ (проб) воды")
        for term in terms:
            criteria_from_spec(
                CriteriaSpec(name="x", terms=[term]).model_dump(mode="json")
            )


class TestSaveGuard:
    async def test_saving_an_unusable_criteria_raises(self) -> None:
        """Фильтр, который никогда ничего не найдёт, заводить нельзя."""
        from services.llm_service.application.use_cases.compile_filter import (
            CompileFilterUseCase,
        )

        class Repo:
            def __init__(self) -> None:
                self.saved: list[CriteriaSpec] = []

            async def save_spec(self, name: str, nl_query: str, spec: CriteriaSpec) -> int:
                self.saved.append(spec)
                return 1

        repo = Repo()
        use_case = CompileFilterUseCase(llm=None, repository=repo)  # type: ignore[arg-type]

        with pytest.raises(CriteriaNotUsable):
            await use_case.compile_and_save("пустой", "запрос", CriteriaSpec(name="x"))

        assert repo.saved == []

"""Критерий из сохранённой спецификации.

Спецификация приходит от человека, а значит бывает неполной и битой. Правило
одно: критерий либо собирается целиком, либо не собирается вовсе. Искать
«примерно то» хуже, чем не искать: результат будет выглядеть настоящим.
"""

from __future__ import annotations

import pytest

from services.research.domain.criteria import (
    BUILTIN,
    OXYGEN_DEMAND_CRITERIA,
    Confidence,
    CriteriaError,
    TermRole,
    criteria_from_spec,
)


class TestBuiltin:
    def test_known_criteria_is_returned_as_is(self) -> None:
        """Проверенный на размеченном наборе критерий не пересобирают."""
        assert criteria_from_spec({"builtin": "ХПК/БПК"}) is OXYGEN_DEMAND_CRITERIA

    def test_unknown_builtin_is_refused(self) -> None:
        with pytest.raises(CriteriaError, match="неизвестный"):
            criteria_from_spec({"builtin": "ХПК/БПК v2"})

    def test_registry_contains_the_oxygen_criteria(self) -> None:
        assert BUILTIN["ХПК/БПК"].version == "хпк-бпк-v2"


class TestTerms:
    def test_terms_are_compiled(self) -> None:
        criteria = criteria_from_spec(
            {
                "name": "кислород",
                "terms": [
                    {"name": "кислород", "pattern": r"кислород\w*"},
                    {
                        "name": "баллон",
                        "pattern": r"баллон\w*",
                        "role": "supporting",
                    },
                ],
            }
        )

        assert [t.name for t in criteria.terms] == ["кислород", "баллон"]
        assert criteria.terms[1].role is TermRole.SUPPORTING
        assert [t.name for t in criteria.primary_terms] == ["кислород"]

    def test_criteria_without_terms_is_refused(self) -> None:
        """Критерий без терминов ничего не найдёт и молчать об этом нельзя."""
        with pytest.raises(CriteriaError, match="без терминов"):
            criteria_from_spec({"name": "пустой", "terms": []})

    def test_term_without_a_pattern_is_refused(self) -> None:
        with pytest.raises(CriteriaError, match="имя и шаблон"):
            criteria_from_spec({"name": "x", "terms": [{"name": "кислород"}]})

    def test_broken_pattern_is_refused_with_its_name(self) -> None:
        """Ошибка должна называть термин: иначе её негде искать."""
        with pytest.raises(CriteriaError, match="кислород"):
            criteria_from_spec(
                {"name": "x", "terms": [{"name": "кислород", "pattern": "([a"}]}
            )


class TestContextRules:
    def test_rules_are_compiled_with_their_window(self) -> None:
        criteria = criteria_from_spec(
            {
                "name": "x",
                "terms": [{"name": "т", "pattern": "т"}],
                "context_rules": [
                    {
                        "name": "название объекта",
                        "pattern": "кровл|здани",
                        "verdict": "rejected",
                        "window": 60,
                    }
                ],
            }
        )

        rule = criteria.context_rules[0]
        assert rule.verdict is Confidence.REJECTED
        assert rule.window == 60

    def test_broken_rule_pattern_is_refused(self) -> None:
        with pytest.raises(CriteriaError):
            criteria_from_spec(
                {
                    "name": "x",
                    "terms": [{"name": "т", "pattern": "т"}],
                    "context_rules": [{"name": "плохое", "pattern": "([a"}],
                }
            )


class TestDefaults:
    def test_sensible_defaults_are_applied(self) -> None:
        criteria = criteria_from_spec(
            {"name": "x", "terms": [{"name": "т", "pattern": "т"}]}
        )

        assert criteria.quote_radius == 220
        assert criteria.max_hits_per_document == 5
        assert criteria.card_pattern is None
        assert criteria.okpd2_prefixes == ()

    def test_prefilter_and_okpd2_are_carried_through(self) -> None:
        criteria = criteria_from_spec(
            {
                "name": "x",
                "terms": [{"name": "т", "pattern": "т"}],
                "card_pattern": "вод|сточн",
                "okpd2_prefixes": ["36.", "37."],
            }
        )

        assert criteria.card_pattern is not None
        assert criteria.okpd2_prefixes == ("36.", "37.")

    def test_version_defaults_but_can_be_set(self) -> None:
        """Версия — часть ключа кэша: без неё правка шаблона не обесценит вердикты."""
        base = {"name": "x", "terms": [{"name": "т", "pattern": "т"}]}
        assert criteria_from_spec(base).version == "v1"
        assert criteria_from_spec({**base, "version": "v7"}).version == "v7"

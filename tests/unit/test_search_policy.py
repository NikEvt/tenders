"""Отсечка по близости.

Абсолютный порог отвечает на «похоже ли это хоть на что-то», относительный — на
«похоже ли настолько же, насколько лучшее совпадение этого запроса». Второй
нужен потому, что длинный описательный запрос лежит ближе ко всему подряд: у
семантического запроса фильтра «ХПК» медиана близости по корпусу совпала с
порогом, и сквозь него проходила половина базы.
"""

from __future__ import annotations

import pytest

from libs.shared.search_policy import (
    DEFAULT_RELATIVE_FLOOR,
    DEFAULT_SEMANTIC_FLOOR,
    cut_tail,
    relative_floor,
    semantic_floor,
)


def test_tail_is_cut_relative_to_the_best_match() -> None:
    """Настоящий случай фильтра «ХПК»: лидер 0.697, хвост около порога."""
    scored = [(1, 0.697), (2, 0.66), (3, 0.52), (4, 0.481)]

    assert cut_tail(scored, 0.9) == [1, 2]


def test_short_query_keeps_its_neighbours() -> None:
    """У короткого запроса совпадения плотные — отсечка не должна их резать."""
    scored = [(1, 0.565), (2, 0.564), (3, 0.540)]

    assert cut_tail(scored, 0.9) == [1, 2, 3]


def test_empty_input_gives_empty_output() -> None:
    assert cut_tail([], 0.9) == []


def test_non_positive_best_disables_the_cut() -> None:
    """Отрицательная близость — вырожденный случай; делить на неё нельзя."""
    assert cut_tail([(1, 0.0), (2, -0.2)], 0.9) == [1, 2]


@pytest.mark.parametrize("raw", ["", "не число", "5", "-3"])
def test_absolute_floor_ignores_nonsense(monkeypatch, raw) -> None:
    """Опечатка в конфиге не должна тихо отключать отсечку."""
    monkeypatch.setenv("SEMANTIC_SIMILARITY_FLOOR", raw)
    assert semantic_floor() == DEFAULT_SEMANTIC_FLOOR


@pytest.mark.parametrize("raw", ["", "не число", "0", "1.5"])
def test_relative_floor_ignores_nonsense(monkeypatch, raw) -> None:
    monkeypatch.setenv("SEMANTIC_RELATIVE_FLOOR", raw)
    assert relative_floor() == DEFAULT_RELATIVE_FLOOR


def test_floors_are_tunable_per_consumer(monkeypatch) -> None:
    """У поиска и у судьи разная цена ошибки — значения могут разойтись."""
    monkeypatch.setenv("JUDGE_SIMILARITY_FLOOR", "0.55")
    assert semantic_floor("JUDGE_SIMILARITY_FLOOR") == 0.55
    assert semantic_floor() == DEFAULT_SEMANTIC_FLOOR

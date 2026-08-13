"""Карточка сохранённого фильтра — проекция для списка и страницы фильтра."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Сколько дней показывает спарклайн «сколько совпало».
MATCH_HISTORY_DAYS = 7


@dataclass(slots=True)
class MatchCount:
    day: date
    count: int


@dataclass(slots=True)
class SavedFilterCard:
    filter_id: int
    name: str
    # Исходный текст, из которого скомпилирован spec. Хранится ради истории:
    # по нему видно, что человек имел в виду, даже если spec потом правили.
    query: str
    # Форма spec принадлежит llm-service — шлюз её не интерпретирует и не
    # валидирует, а передаёт как есть. Импортировать её оттуда нельзя: сервисы
    # не зависят друг от друга напрямую.
    spec: dict
    in_digest: bool
    notify: bool
    is_active: bool
    created_at: datetime
    last_run_at: datetime | None = None
    match_counts: list[MatchCount] = field(default_factory=list)

"""Фрагменты документов: границы чанков и результаты поиска по ним."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

SearchMode = Literal["lexical", "semantic", "rrf"]
SEARCH_MODES: tuple[SearchMode, ...] = ("lexical", "semantic", "rrf")


@dataclass(slots=True)
class ChunkOutline:
    """Где чанк лежит в тексте документа.

    `char_start`/`char_end` могут быть None у документов, нарезанных до
    появления смещений: там подсветить цитату нечем, и клиент об этом узнаёт
    из самого ответа, а не догадывается.
    """

    chunk_id: int
    ordinal: int
    char_start: int | None
    char_end: int | None
    page: int | None


@dataclass(slots=True)
class FragmentScores:
    lexical: float | None = None
    vector: float | None = None
    rrf: float = 0.0


@dataclass(slots=True)
class Fragment:
    """Найденный фрагмент документа — единица выдачи поиска по документации."""

    chunk_id: int
    document_id: int
    tender_id: int
    reg_num: str
    tender_name: str | None
    tender_price: Decimal | None
    document_name: str | None
    text: str
    char_start: int | None
    char_end: int | None
    scores: FragmentScores
    # Смещения совпадений внутри `text`, а не внутри документа: подсвечивать
    # надо в том куске, который показан на карточке.
    highlights: list[tuple[int, int]] = field(default_factory=list)


@dataclass(slots=True)
class FragmentPage:
    items: list[Fragment]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class TextLocation:
    """Где искать текст документа.

    Ровно одно из полей заполнено. Два варианта существуют, пока идёт перенос
    текстов в объектное хранилище: у перенесённых документов есть `key`, у
    оставшихся — `inline`. После миграции 0007, снимающей `content`, второй
    вариант исчезнет вместе с полем.
    """

    key: str | None = None
    inline: str | None = None

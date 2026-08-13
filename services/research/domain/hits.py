"""Находка — совпадение вместе с контекстом, в котором оно случилось.

Голое совпадение бесполезно: «БПК» встречается и в показателе качества воды, и
в названии банно-прачечного комбината. Решает окружение, поэтому наружу уходит
не позиция в файле, а цитата ±220 символов.

**Позиция совпадения внутри цитаты хранится отдельно.** В прогоне ХПК/БПК её не
было, и это стоило нескольких неверных выводов: при разборе печатались первые
155 символов цитаты, то есть только левый контекст, а само слово оставалось за
кадром. Со смещением цитату можно показать с подсветкой — и человеку, и модели.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.research.domain.criteria import Criteria, TermPattern, TermRole


@dataclass(frozen=True, slots=True)
class Hit:
    """Одно упоминание с контекстом."""

    term: str
    role: TermRole
    quote: str
    #: Границы совпадения внутри `quote`.
    match_start: int
    match_end: int
    file_name: str | None = None
    page: int | None = None
    #: Позиция совпадения в исходном тексте — чтобы находки не двоились.
    source_offset: int = 0

    @property
    def matched(self) -> str:
        return self.quote[self.match_start : self.match_end]

    def highlighted(self, opening: str = ">>>", closing: str = "<<<") -> str:
        """Цитата с выделенным совпадением.

        Ровно то, чего не хватало при ручной классификации: без подсветки
        превью показывает левый контекст и создаёт впечатление, не имеющее
        отношения к находке.
        """
        return (
            f"{self.quote[: self.match_start]}{opening}"
            f"{self.matched}{closing}{self.quote[self.match_end :]}"
        )


def _collapse(text: str) -> tuple[str, list[int]]:
    """Схлопывает пробельные серии, запоминая исходную позицию каждого символа.

    Текст из PDF приходит с переносами посреди предложения и колонками,
    склеенными пробелами; без нормализации цитата нечитаема. Карта позиций
    нужна, чтобы смещение совпадения осталось верным после схлопывания.
    """
    out: list[str] = []
    positions: list[int] = []
    in_space = False

    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                out.append(" ")
                positions.append(index)
                in_space = True
            continue
        out.append(char)
        positions.append(index)
        in_space = False

    positions.append(len(text))
    return "".join(out), positions


def find_hits(
    text: str,
    criteria: Criteria,
    file_name: str | None = None,
    page: int | None = None,
) -> list[Hit]:
    """Все упоминания терминов критерия в тексте.

    Совпадения разных шаблонов на одном месте схлопываются: «ХПК» внутри
    «химическое потребление кислорода» — одна находка, а не две, иначе один и
    тот же фрагмент дал бы две цитаты и удвоил вес.
    """
    if not text:
        return []

    collapsed, positions = _collapse(text)
    if not collapsed:
        return []

    found: list[tuple[int, TermPattern, int, int]] = []
    seen: list[tuple[int, int]] = []

    for term in criteria.terms:
        for match in term.pattern.finditer(collapsed):
            start, end = match.span()
            if any(start < seen_end and seen_start < end for seen_start, seen_end in seen):
                continue
            seen.append((start, end))
            found.append((start, term, start, end))

    found.sort(key=lambda item: item[0])

    radius = criteria.quote_radius
    hits: list[Hit] = []
    for _, term, start, end in found[: criteria.max_hits_per_document]:
        quote_start = max(0, start - radius)
        quote_end = min(len(collapsed), end + radius)
        hits.append(
            Hit(
                term=term.name,
                role=term.role,
                quote=collapsed[quote_start:quote_end],
                match_start=start - quote_start,
                match_end=end - quote_start,
                file_name=file_name,
                page=page,
                # Позиция в исходном тексте, а не в схлопнутом: по ней находку
                # можно найти в документе.
                source_offset=positions[start],
            )
        )
    return hits


def is_card_candidate(
    name: str | None,
    description: str | None,
    okpd2_codes: tuple[str, ...] | list[str],
    okpd2_names: tuple[str, ...] | list[str],
    criteria: Criteria,
) -> bool:
    """Стоит ли вообще качать документы этой закупки.

    Предфильтр намеренно широкий: пропущенная закупка не вернётся, а лишняя
    стоит одного скачивания. В прогоне он сузил 150 тыс. извещений до 31 тыс.
    """
    if criteria.card_pattern is not None:
        card = " ".join(filter(None, [name, description, *okpd2_names]))
        if criteria.card_pattern.search(card):
            return True
    return any(code.startswith(criteria.okpd2_prefixes) for code in okpd2_codes)

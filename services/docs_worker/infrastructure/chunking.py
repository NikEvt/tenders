"""Нарезка документа на чанки с привязкой к странице и к месту в тексте.

Резать нужно **тот же текст**, который уходит в `document_texts.content`, а не
страницы по отдельности. Иначе текст чанка перестаёт быть подстрокой документа:
между страницами теряется разделитель, а нормализация пробелов на склейках
сдвигает всё остальное. Тогда цитату из вердикта уже не показать в документе —
её негде подсветить.

Здесь чанк — это срез `content[char_start:char_end]`, дословно.
"""

from __future__ import annotations

import re
from bisect import bisect_right

from services.docs_worker.application.ports import ChunkerPort
from services.docs_worker.domain.models import Chunk, ExtractedText

# ~800 токенов при оценке 3 символа/токен. Крупнее — чанк перестаёт быть точным
# ответом на запрос; мельче — теряется контекст пункта ТЗ.
DEFAULT_CHUNK_CHARS = 2400
DEFAULT_OVERLAP_CHARS = 300

# Границы предложений и пунктов («1.2.3.», «4)») — по ним резать безопаснее всего.
_BOUNDARY = re.compile(r"(?<=[.!?;:])\s+|\n{2,}|(?=\n\s*\d+[.)]\s)")

# Разделитель страниц в собранном тексте — см. ExtractedText.content.
PAGE_SEPARATOR = "\n\n"


class RecursiveChunker(ChunkerPort):
    """Режет по границам абзацев и предложений, не разрывая слова."""

    def __init__(
        self,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ) -> None:
        if overlap_chars >= chunk_chars:
            raise ValueError("overlap должен быть меньше размера чанка")
        self._chunk_chars = chunk_chars
        self._overlap_chars = overlap_chars

    def split(self, text: ExtractedText) -> list[Chunk]:
        content = text.content
        if not content.strip():
            return []

        starts, numbers = _page_index(text)
        cuts = _cut_positions(content)

        chunks: list[Chunk] = []
        start = 0
        while start < len(content):
            end = self._next_cut(content, cuts, start)
            span = _trim(content, start, end)
            if span is not None:
                begin, finish = span
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        text=content[begin:finish],
                        char_start=begin,
                        char_end=finish,
                        page_from=_page_at(starts, numbers, begin),
                        page_to=_page_at(starts, numbers, finish - 1),
                    )
                )
            if end >= len(content):
                break
            # Хвост предыдущего чанка переходит в следующий: требование,
            # разорванное границей, иначе не найдётся ни одним из соседей.
            start = max(end - self._overlap_chars, start + 1)

        return chunks

    def _next_cut(self, content: str, cuts: list[int], start: int) -> int:
        limit = start + self._chunk_chars
        if limit >= len(content):
            return len(content)

        # Самая дальняя граница, укладывающаяся в размер чанка.
        position = bisect_right(cuts, limit) - 1
        if position >= 0 and cuts[position] > start:
            return cuts[position]

        # Сверхдлинный фрагмент без знаков препинания (таблица, простыня кодов
        # ОКПД2) режем по жёсткой границе — иначе он не влезет ни в один чанк.
        return limit


def _cut_positions(content: str) -> list[int]:
    """Позиции, по которым резать безопасно. Разделитель уходит в левый чанк."""
    return [match.end() for match in _BOUNDARY.finditer(content) if match.end() > 0]


def _trim(content: str, start: int, end: int) -> tuple[int, int] | None:
    """Сжимает срез до непробельного содержимого, сохраняя смещения точными."""
    while start < end and content[start].isspace():
        start += 1
    while end > start and content[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _page_index(text: ExtractedText) -> tuple[list[int], list[int]]:
    """Начальные смещения страниц в собранном тексте и их номера.

    Пустые страницы в `content` не попадают — не попадают и сюда, иначе
    привязка чанка к странице съедет.
    """
    starts: list[int] = []
    numbers: list[int] = []
    offset = 0
    for page in text.pages:
        if not page.text.strip():
            continue
        if starts:
            offset += len(PAGE_SEPARATOR)
        starts.append(offset)
        numbers.append(page.number)
        offset += len(page.text)
    return starts, numbers


def _page_at(starts: list[int], numbers: list[int], offset: int) -> int | None:
    if not starts:
        return None
    return numbers[max(0, bisect_right(starts, offset) - 1)]

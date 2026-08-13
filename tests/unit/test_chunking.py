"""Нарезка документов на чанки."""

from __future__ import annotations

from services.docs_worker.domain.models import ExtractedPage, ExtractedText
from services.docs_worker.infrastructure.chunking import RecursiveChunker


def text_of(*pages: str) -> ExtractedText:
    return ExtractedText(
        pages=[ExtractedPage(number=i, text=p) for i, p in enumerate(pages, start=1)]
    )


def test_short_document_is_a_single_chunk() -> None:
    chunks = RecursiveChunker().split(text_of("Поставка газа в баллонах."))
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].page_from == 1
    assert chunks[0].page_to == 1


def test_long_document_is_split_and_indexed() -> None:
    sentence = "Поставщик обязан обеспечить доставку товара до склада заказчика. "
    chunker = RecursiveChunker(chunk_chars=400, overlap_chars=50)

    chunks = chunker.split(text_of(sentence * 40))

    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.text.strip() for c in chunks)


def test_chunks_carry_page_range_for_citation() -> None:
    """Без диапазона страниц LLM не сможет сослаться на источник вердикта."""
    chunker = RecursiveChunker(chunk_chars=200, overlap_chars=0)
    chunks = chunker.split(text_of("А" * 180 + ".", "Б" * 180 + ".", "В" * 180 + "."))

    assert all(c.page_from is not None and c.page_to is not None for c in chunks)
    assert min(c.page_from for c in chunks) == 1
    assert max(c.page_to for c in chunks) == 3


def test_overlap_preserves_requirements_split_by_a_boundary() -> None:
    chunker = RecursiveChunker(chunk_chars=120, overlap_chars=40)
    body = "Первое требование. Второе требование. Третье требование. Четвёртое требование. "
    chunks = chunker.split(text_of(body * 3))

    assert len(chunks) > 1
    # Хвост предыдущего чанка должен пересекаться с началом следующего.
    tail = chunks[0].text[-20:]
    assert any(tail[:10] in c.text for c in chunks[1:])


def test_text_without_punctuation_is_still_bounded() -> None:
    """Простыня из кодов ОКПД2 без знаков препинания не должна давать чанк-гигант."""
    chunker = RecursiveChunker(chunk_chars=100, overlap_chars=0)
    chunks = chunker.split(text_of("27.40.15.150 " * 200))

    assert len(chunks) > 1
    assert all(len(c.text) <= 200 for c in chunks)


def test_empty_pages_are_ignored() -> None:
    chunks = RecursiveChunker().split(text_of("", "   ", "Реальный текст."))
    assert len(chunks) == 1
    assert chunks[0].page_from == 3


def test_empty_document_yields_no_chunks() -> None:
    assert RecursiveChunker().split(ExtractedText()) == []


def test_token_estimate_is_positive() -> None:
    chunks = RecursiveChunker().split(text_of("Поставка газа."))
    assert chunks[0].token_estimate > 0


# ─── Смещения ─────────────────────────────────────────────────────────────────


def test_chunk_text_is_a_verbatim_slice_of_the_document() -> None:
    """Свойство, ради которого всё затевалось: цитату можно найти в документе.

    Если оно нарушится, `[Показать источник]` в ИИ-вердикте будет подсвечивать
    не то место — а это хуже, чем не подсвечивать ничего.
    """
    document = text_of(
        "Первое требование. Второе требование.  Третье   требование.",
        "Мебель должна выдерживать обработку хлоргексидином.",
    )
    content = document.content

    for chunk in RecursiveChunker(chunk_chars=60, overlap_chars=10).split(document):
        assert chunk.char_start is not None and chunk.char_end is not None
        assert content[chunk.char_start : chunk.char_end] == chunk.text


def test_offsets_hold_on_a_long_document() -> None:
    sentence = "Поставщик обязан обеспечить доставку товара до склада заказчика. "
    document = text_of(sentence * 40, sentence * 40)
    content = document.content

    chunks = RecursiveChunker(chunk_chars=400, overlap_chars=50).split(document)

    assert len(chunks) > 4
    assert all(content[c.char_start : c.char_end] == c.text for c in chunks)
    # Чанки идут по тексту вперёд и не выходят за его пределы.
    assert [c.char_start for c in chunks] == sorted(c.char_start for c in chunks)
    assert max(c.char_end for c in chunks) <= len(content)


def test_offsets_survive_hard_cuts_without_punctuation() -> None:
    document = text_of("27.40.15.150 " * 200)
    content = document.content

    chunks = RecursiveChunker(chunk_chars=100, overlap_chars=0).split(document)

    assert len(chunks) > 1
    assert all(content[c.char_start : c.char_end] == c.text for c in chunks)


def test_offsets_cross_the_page_separator_correctly() -> None:
    """Между страницами в тексте стоит пустая строка — её нельзя терять."""
    document = text_of("Конец первой страницы", "Начало второй страницы")
    content = document.content

    chunks = RecursiveChunker(chunk_chars=1000, overlap_chars=0).split(document)

    assert len(chunks) == 1
    assert content[chunks[0].char_start : chunks[0].char_end] == chunks[0].text
    assert "\n\n" in chunks[0].text
    assert chunks[0].page_from == 1 and chunks[0].page_to == 2


def test_pages_are_attributed_by_offset() -> None:
    document = text_of("А" * 180 + ".", "Б" * 180 + ".", "В" * 180 + ".")
    chunks = RecursiveChunker(chunk_chars=200, overlap_chars=0).split(document)

    for chunk in chunks:
        # Номер страницы должен соответствовать содержимому чанка, а не порядку.
        letters = {"А": 1, "Б": 2, "В": 3}
        present = {letters[ch] for ch in chunk.text if ch in letters}
        assert present <= set(range(chunk.page_from, chunk.page_to + 1))

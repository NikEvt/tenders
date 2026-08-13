"""Выравнивание старых чанков по тексту документа."""

from __future__ import annotations

from services.docs_worker.backfill_offsets import align


def test_exact_substring_is_found() -> None:
    content = "Первое требование. Второе требование."
    assert align(content, "Второе требование.") == (19, 37)


def test_whitespace_differences_do_not_break_alignment() -> None:
    """Старый чанкер нормализовал пробелы — точный поиск здесь вернул бы −1."""
    content = "Мебель  должна\nвыдерживать   обработку хлоргексидином."
    chunk = "Мебель должна выдерживать обработку хлоргексидином."

    span = align(content, chunk)

    assert span is not None
    start, end = span
    # Границы указывают на настоящий текст, а не на нормализованную копию.
    assert content[start:end].startswith("Мебель")
    assert content[start:end].endswith("хлоргексидином.")


def test_page_separator_lost_by_the_old_chunker_is_tolerated() -> None:
    content = "Конец первой страницы\n\nНачало второй"
    chunk = "Конец первой страницы Начало второй"

    assert align(content, chunk) == (0, len(content))


def test_repeated_text_resolves_forward_not_to_the_first_hit() -> None:
    """«Приложение №1» встречается трижды — чанк должен лечь на своё место."""
    content = "Приложение №1. А. Приложение №1. Б. Приложение №1. В."
    first = align(content, "Приложение №1.")
    assert first == (0, 14)

    second = align(content, "Приложение №1.", search_from=first[1])
    assert second is not None and second[0] > first[0]


def test_text_absent_from_the_document_is_reported() -> None:
    assert align("Поставка газа.", "Совершенно другой текст") is None


def test_blank_chunk_is_reported() -> None:
    assert align("Поставка газа.", "   ") is None

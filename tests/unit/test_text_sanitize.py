"""Белый список символов XML.

Тест существует потому, что чёрный список однажды не сработал: U+FFFE не
является управляющим символом и в него не попадал, а openpyxl на нём падал —
вместе с прогоном, шедшим к тому моменту полчаса.
"""

from __future__ import annotations

import pytest

from libs.shared.text_sanitize import MAX_CELL_CHARS, cell, sanitize


class TestForbiddenCharacters:
    def test_the_character_that_killed_the_run(self) -> None:
        """U+FFFE — так развалился мягкий перенос в текстовом слое PDF."""
        assert sanitize("аммоний￾ион") == "аммонийион"

    @pytest.mark.parametrize("code", [0xFFFE, 0xFFFF])
    def test_noncharacters_are_removed(self, code: int) -> None:
        assert sanitize(f"до{chr(code)}после") == "допосле"

    @pytest.mark.parametrize("code", [0xD800, 0xDC00, 0xDFFF])
    def test_surrogates_from_broken_cmaps_are_removed(self, code: int) -> None:
        """Битые CMap приносят одиночные суррогаты — XML их не допускает.

        Записываются через `chr`, а не литералом: одиночный суррогат в исходнике
        не выражается, ради того и существует диапазон D800–DFFF.
        """
        assert sanitize(f"текст{chr(code)}") == "текст"

    @pytest.mark.parametrize("code", [0x00, 0x01, 0x08, 0x0B, 0x0C, 0x1F])
    def test_control_characters_are_removed(self, code: int) -> None:
        assert sanitize(f"а{chr(code)}б") == "аб"

    def test_removal_does_not_glue_words_with_a_space(self) -> None:
        """Замена на пробел склеила бы слова там, где символ был мусором."""
        assert " " not in sanitize("аммоний￾ион")


class TestAllowedCharacters:
    @pytest.mark.parametrize("char", ["\t", "\n", "\r"])
    def test_whitespace_of_the_xml_spec_survives(self, char: str) -> None:
        assert sanitize(f"а{char}б") == f"а{char}б"

    def test_cyrillic_and_symbols_survive(self) -> None:
        text = "ХПК ≤ 30 мг/дм³, БПК₅ — норма"
        assert sanitize(text) == text

    def test_emoji_beyond_the_basic_plane_survive(self) -> None:
        """[#x10000-#x10FFFF] спецификацией разрешён."""
        assert sanitize("проба 🧪") == "проба 🧪"

    def test_clean_text_is_returned_unchanged(self) -> None:
        text = "обычная строка"
        assert sanitize(text) is text


class TestCell:
    def test_numbers_keep_their_type(self) -> None:
        """Иначе в отчёте не отсортировать столбец с ценой."""
        assert cell(304_000_000) == 304_000_000
        assert cell(2.5) == 2.5
        assert cell(None) is None

    def test_long_text_is_cut_visibly(self) -> None:
        """Молча укоротить — значит соврать о содержимом ячейки."""
        result = cell("а" * (MAX_CELL_CHARS + 500))

        assert isinstance(result, str)
        assert len(result) == MAX_CELL_CHARS
        assert result.endswith("…")

    def test_text_is_sanitized_on_the_way_to_the_cell(self) -> None:
        assert cell("аммоний￾ион") == "аммонийион"

    def test_text_at_the_limit_is_untouched(self) -> None:
        text = "б" * MAX_CELL_CHARS
        assert cell(text) == text

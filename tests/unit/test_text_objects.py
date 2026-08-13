"""Соглашение об именовании объектов с текстом.

Ключ считается от содержимого, и на этом держится дедупликация: типовой проект
контракта, приложенный к тысячам извещений, обязан занимать в хранилище одно
место.
"""

from __future__ import annotations

from libs.shared.text_objects import (
    TEXT_PREFIX,
    decode_text,
    encode_text,
    text_digest,
    text_key,
)


class TestKeyIsDerivedFromContent:
    def test_identical_text_gives_identical_key(self) -> None:
        """То, ради чего ключ вообще считается от содержимого."""
        first = "Определение ХПК по методике ПНД Ф 14.1:2.100-97"
        second = "Определение ХПК по методике ПНД Ф 14.1:2.100-97"
        assert text_key(text_digest(first)) == text_key(text_digest(second))

    def test_different_text_gives_different_key(self) -> None:
        assert text_key(text_digest("ХПК")) != text_key(text_digest("БПК"))

    def test_key_is_sharded_by_prefix(self) -> None:
        """Сотни тысяч объектов в одном «каталоге» делают листинг бакета долгим."""
        digest = text_digest("проба")
        key = text_key(digest)

        assert key == f"{TEXT_PREFIX}/{digest[:2]}/{digest}.txt"
        assert key.count("/") == 2

    def test_whitespace_matters(self) -> None:
        """Дедупликация побайтовая: нормализацией занимается извлечение, не ключ."""
        assert text_digest("ХПК") != text_digest("ХПК ")


class TestRoundTrip:
    def test_cyrillic_survives(self) -> None:
        content = "Биохимическое потребление кислорода, мг/дм³"
        assert decode_text(encode_text(content)) == content

    def test_broken_bytes_do_not_lose_the_document(self) -> None:
        """OCR приносит обрывки суррогатов — терять из-за них весь текст незачем."""
        restored = decode_text("ХПК".encode() + b"\xff\xfe" + "БПК".encode())

        assert "ХПК" in restored
        assert "БПК" in restored

    def test_empty_text_is_representable(self) -> None:
        assert decode_text(encode_text("")) == ""
        assert text_key(text_digest("")).endswith(".txt")

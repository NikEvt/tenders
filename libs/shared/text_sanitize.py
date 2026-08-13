"""Подготовка распознанного текста к выгрузке в xlsx.

xlsx — это XML, и openpyxl падает на символах, которых спецификация XML не
допускает. В прогоне ХПК/БПК на этом умер контейнер, проработавший полчаса:

    ValueError: All strings must be XML compatible: Unicode or ASCII,
                no NULL bytes or control characters

Виноват был U+FFFE — так развалился мягкий перенос в текстовом слое PDF
(«аммоний￾ион»). Первая попытка чинить **чёрным** списком управляющих
символов не помогла: U+FFFE в него не попадал, потому что управляющим не
является. Список работает только белый.

Разрешено ровно то, что допускает продукция `Char` спецификации XML 1.0:

    #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]

Отсюда бесплатно закрываются и суррогаты из битых CMap (D800–DFFF), и U+FFFF.

Проблема общая для любого экспорта распознанного текста, а не частная для
одного скрипта, — поэтому модуль живёт в `libs.shared`.
"""

from __future__ import annotations

#: Верхняя граница длины ячейки в xlsx. Превышение openpyxl не прощает.
MAX_CELL_CHARS = 32_000

#: Чем заменяется недопустимый символ. Пустая строка, а не пробел: подстановка
#: пробела склеивала бы слова там, где символ был мусором внутри слова.
REPLACEMENT = ""


def _is_xml_char(char: str) -> bool:
    code = ord(char)
    return (
        code in (0x09, 0x0A, 0x0D)
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def sanitize(value: str) -> str:
    """Оставляет только символы, допустимые в XML.

    Быстрый путь на случай, когда чистить нечего: подавляющее большинство
    строк проходит проверку целиком, и пересобирать их посимвольно незачем.
    """
    if all(_is_xml_char(char) for char in value):
        return value
    return "".join(char if _is_xml_char(char) else REPLACEMENT for char in value)


def cell(value: object) -> object:
    """Значение, пригодное для ячейки xlsx.

    Числа и даты отдаются как есть — openpyxl обязан видеть их типами, иначе
    в отчёте не отсортировать столбец с ценой. Чистится только текст, и он же
    подрезается по длине.
    """
    if not isinstance(value, str):
        return value

    cleaned = sanitize(value)
    if len(cleaned) > MAX_CELL_CHARS:
        # Обрыв виден в ячейке: молча укоротить — значит соврать о содержимом.
        return cleaned[: MAX_CELL_CHARS - 1] + "…"
    return cleaned

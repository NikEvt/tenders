"""Порядок и постраничность выдачи каталога.

Два режима сосуществуют намеренно. Offset нужен нумерованной пагинации и
переходу на произвольную страницу. Курсор нужен бесконечной прокрутке: пока
пользователь листает, краулер продолжает вставлять извещения, и на offset-е
выдача «съезжает» — часть строк показывается дважды, часть пропадает.

Порядок задаётся списком ключей, а не одним полем: группировка по категории —
это тот же запрос, где ключ группы стоит первым (`okpd:asc,price:desc`).
Собирать группы на клиенте из уже разбитой на страницы выдачи нельзя — группа
не помещается в страницу.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from services.api.domain.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

SortField = Literal[
    "relevance",
    "price",
    "deadline",
    "published",
    "okpd",
    "customer",
    "region",
]
SORT_FIELDS: tuple[SortField, ...] = (
    "relevance",
    "price",
    "deadline",
    "published",
    "okpd",
    "customer",
    "region",
)

#: Тип значения ключа — от него зависит разбор курсора.
type SortValue = datetime | Decimal | str | None

_VALUE_KIND: dict[SortField, str] = {
    "relevance": "datetime",
    "published": "datetime",
    "deadline": "datetime",
    "price": "decimal",
    "okpd": "text",
    "customer": "text",
    "region": "text",
}

# Версия формата курсора: если раскладка ключа изменится, старые курсоры из
# открытых вкладок должны честно отвергаться, а не разбираться неправильно.
# 2 — переход от одного ключа к списку ключей.
CURSOR_VERSION = 2


@dataclass(frozen=True, slots=True)
class SortKey:
    field: SortField = "published"
    ascending: bool = False


@dataclass(frozen=True, slots=True)
class SortSpec:
    """Главный ключ порядка и, при группировке, следующие за ним.

    Главный вынесен в отдельные поля, а не спрятан в кортеж: почти весь код
    спрашивает именно про него («это релевантность?»), а список ключей нужен
    только сборке ORDER BY и курсору.
    """

    field: SortField = "published"
    ascending: bool = False
    rest: tuple[SortKey, ...] = ()

    @property
    def keys(self) -> tuple[SortKey, ...]:
        return (SortKey(self.field, self.ascending), *self.rest)

    @property
    def is_relevance(self) -> bool:
        """Релевантность существует только у поиска.

        В каталоге сортировать по ней нечем: у строк нет оценки, и выдача
        идёт по дате публикации.
        """
        return self.field == "relevance"


@dataclass(frozen=True, slots=True)
class Cursor:
    """Позиция последней отданной строки: значения всех ключей и её id.

    Значения плюс id, а не один id: ключи сортировки не уникальны, и без
    доборного ключа строки с одинаковой ценой перескакивали бы друг через
    друга. На полях с малым числом значений — регион, ОКПД2 — без добора
    страница просто дублирует и теряет строки.
    """

    sort: SortSpec
    values: tuple[SortValue, ...]
    tender_id: int


@dataclass(frozen=True, slots=True)
class PageRequest:
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0
    cursor: Cursor | None = None
    sort: SortSpec = field(default_factory=SortSpec)

    @property
    def page(self) -> int | None:
        """Номер страницы имеет смысл только в offset-режиме."""
        if self.cursor is not None:
            return None
        return self.offset // self.limit if self.limit else 0


class BadCursor(ValueError):
    """Курсор нечитаем или снят при другой сортировке."""


def _keys_payload(sort: SortSpec) -> list[list[object]]:
    return [[key.field, key.ascending] for key in sort.keys]


def encode_cursor(cursor: Cursor) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "k": _keys_payload(cursor.sort),
        "s": [_encode_value(value) for value in cursor.values],
        "i": cursor.tender_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(raw: str, expected: SortSpec) -> Cursor:
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error) as exc:
        raise BadCursor("Курсор нечитаем") from exc

    if payload.get("v") != CURSOR_VERSION:
        raise BadCursor("Курсор снят в старом формате")
    if payload.get("k") != _keys_payload(expected):
        # Иначе догрузка пришила бы к списку строки, отсортированные иначе.
        raise BadCursor("Курсор снят при другой сортировке")

    encoded = payload.get("s")
    if not isinstance(encoded, list) or len(encoded) != len(expected.keys):
        raise BadCursor("Курсор повреждён")

    try:
        return Cursor(
            sort=expected,
            values=tuple(
                _decode_value(value, key.field)
                for value, key in zip(encoded, expected.keys, strict=True)
            ),
            tender_id=int(payload["i"]),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise BadCursor("Курсор повреждён") from exc


def _encode_value(value: SortValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _decode_value(raw: object, field_name: SortField) -> SortValue:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise BadCursor("Курсор повреждён")

    kind = _VALUE_KIND[field_name]
    if kind == "decimal":
        return Decimal(raw)
    if kind == "text":
        return raw
    return datetime.fromisoformat(raw)


def normalized_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))

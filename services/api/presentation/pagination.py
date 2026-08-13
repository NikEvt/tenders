"""Разбор параметров постраничности из строки запроса.

Два режима принимаются одним набором параметров: `page`/`page_size` — старый
offset, `cursor`/`limit` — курсор. Курсор побеждает, если пришёл: смешивать их
в одном запросе бессмысленно.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query

from services.api.application.errors import InvalidRequest
from services.api.domain.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from services.api.domain.pagination import (
    SORT_FIELDS,
    BadCursor,
    PageRequest,
    SortKey,
    SortSpec,
    decode_cursor,
)

# Значения по умолчанию — модульные синглтоны: вызов в сигнатуре ruff запрещает
# (B008), а объявлять их внутри функции FastAPI не умеет.
_LIMIT = Query(default=None, ge=1, le=MAX_PAGE_SIZE, description="Размер страницы курсором")
_SORT = Query(
    default="published",
    description=(
        "Порядок выдачи. Одно поле (`price`) или список ключей с направлениями "
        "(`okpd:asc,price:desc`). Добор по `id` сервер дописывает сам."
    ),
)

_DIRECTIONS = {"asc": True, "desc": False}

#: Клиент дописывает добор к своей строке сортировки; сервер ставит его сам,
#: поэтому такой ключ здесь молча пропускается, а не считается ошибкой.
_SERVER_OWNED = "id"


def _parse_sort(raw: str, order: str) -> SortSpec:
    keys: list[SortKey] = []
    seen: set[str] = set()

    for part in (piece.strip() for piece in raw.split(",")):
        if not part:
            continue

        name, _, direction = part.partition(":")
        name = name.strip()
        direction = direction.strip()

        if name == _SERVER_OWNED:
            continue
        if name not in SORT_FIELDS:
            raise InvalidRequest(f"Неизвестная сортировка: {name}")
        if direction and direction not in _DIRECTIONS:
            raise InvalidRequest(f"Неизвестное направление сортировки: {direction}")
        if name in seen:
            # Второй ключ по тому же полю ничего не решает.
            continue

        # Направление без двоеточия берётся из `order` — так работал прежний
        # контракт `?sort=price&order=asc`, и ссылки с ним обязаны открываться.
        ascending = _DIRECTIONS[direction] if direction else order == "asc"
        keys.append(SortKey(field=name, ascending=ascending))
        seen.add(name)

    if not keys:
        raise InvalidRequest("Пустая сортировка")

    head = keys[0]
    return SortSpec(field=head.field, ascending=head.ascending, rest=tuple(keys[1:]))


def page_params(
    page: int = Query(default=0, ge=0, description="Номер страницы (offset-режим)"),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(
        default=None,
        description="Курсор последней строки. Задан — `page` игнорируется, `page` в ответе null",
    ),
    limit: int | None = _LIMIT,
    sort: str = _SORT,
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> PageRequest:
    spec = _parse_sort(sort, order)
    size = limit if limit is not None else page_size

    if cursor is None:
        return PageRequest(limit=size, offset=page * size, sort=spec)

    try:
        decoded = decode_cursor(cursor, spec)
    except BadCursor as exc:
        # 422, а не 500: курсор приходит от клиента и может устареть.
        raise InvalidRequest(str(exc)) from exc
    return PageRequest(limit=size, cursor=decoded, sort=spec)


PageParams = Annotated[PageRequest, Depends(page_params)]

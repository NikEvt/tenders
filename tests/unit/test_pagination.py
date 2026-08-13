"""Разбор порядка выдачи и курсора.

Курсор — единственное место, где клиент возвращает нам наш собственный
внутренний порядок. Ошибка здесь не падает, а тихо дублирует или теряет
строки на третьей странице, поэтому проверяется отдельно от базы.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from services.api.application.errors import InvalidRequest
from services.api.domain.pagination import (
    BadCursor,
    Cursor,
    SortKey,
    SortSpec,
    decode_cursor,
    encode_cursor,
)
from services.api.presentation.pagination import _parse_sort


class TestSortParsing:
    def test_single_field_keeps_the_old_contract(self) -> None:
        # `?sort=price&order=asc` — ссылки с прежним контрактом обязаны работать.
        spec = _parse_sort("price", "asc")
        assert spec.field == "price"
        assert spec.ascending is True
        assert spec.rest == ()

    def test_direction_in_the_key_beats_the_order_parameter(self) -> None:
        spec = _parse_sort("price:desc", "asc")
        assert spec.ascending is False

    def test_multi_key_keeps_order(self) -> None:
        spec = _parse_sort("okpd:asc,price:desc", "desc")
        assert [(k.field, k.ascending) for k in spec.keys] == [
            ("okpd", True),
            ("price", False),
        ]

    def test_category_fields_are_sortable(self) -> None:
        for field in ("okpd", "customer", "region"):
            assert _parse_sort(f"{field}:asc", "desc").field == field

    def test_client_side_tie_break_is_ignored(self) -> None:
        # Клиент дописывает `id:asc` к своей строке; добор ставит сервер сам.
        spec = _parse_sort("price:desc,id:asc", "desc")
        assert [k.field for k in spec.keys] == ["price"]

    def test_repeated_field_collapses(self) -> None:
        spec = _parse_sort("price:asc,price:desc", "desc")
        assert [k.field for k in spec.keys] == ["price"]
        assert spec.ascending is True

    def test_unknown_field_is_a_client_error(self) -> None:
        with pytest.raises(InvalidRequest):
            _parse_sort("выдумка", "desc")

    def test_unknown_direction_is_a_client_error(self) -> None:
        with pytest.raises(InvalidRequest):
            _parse_sort("price:вверх", "desc")

    def test_empty_sort_is_a_client_error(self) -> None:
        with pytest.raises(InvalidRequest):
            _parse_sort("  ,  ", "desc")


class TestCursor:
    def test_round_trip_single_key(self) -> None:
        sort = SortSpec(field="price", ascending=True)
        cursor = Cursor(sort=sort, values=(Decimal("1000.50"),), tender_id=7)

        restored = decode_cursor(encode_cursor(cursor), sort)
        assert restored == cursor

    def test_round_trip_multi_key(self) -> None:
        sort = SortSpec(
            field="okpd",
            ascending=True,
            rest=(SortKey(field="published", ascending=False),),
        )
        cursor = Cursor(
            sort=sort,
            values=("32.50.13", datetime(2026, 8, 6, 9, 0)),
            tender_id=42,
        )

        assert decode_cursor(encode_cursor(cursor), sort) == cursor

    def test_null_value_survives_the_round_trip(self) -> None:
        # У закупки может не быть ОКПД2 — такие строки лежат в хвосте, и
        # курсор обязан уметь стоять на них.
        sort = SortSpec(field="okpd", ascending=True)
        cursor = Cursor(sort=sort, values=(None,), tender_id=3)

        assert decode_cursor(encode_cursor(cursor), sort).values == (None,)

    def test_cursor_taken_under_another_sort_is_rejected(self) -> None:
        taken = Cursor(sort=SortSpec(field="price"), values=(Decimal("1"),), tender_id=1)
        raw = encode_cursor(taken)

        with pytest.raises(BadCursor):
            decode_cursor(raw, SortSpec(field="published"))

    def test_cursor_taken_under_a_shorter_key_list_is_rejected(self) -> None:
        # Иначе догрузка пришила бы к списку строки другого порядка.
        one = SortSpec(field="okpd", ascending=True)
        two = SortSpec(field="okpd", ascending=True, rest=(SortKey("price", False),))
        raw = encode_cursor(Cursor(sort=one, values=("32.50",), tender_id=1))

        with pytest.raises(BadCursor):
            decode_cursor(raw, two)

    def test_cursor_of_the_old_format_is_rejected_honestly(self) -> None:
        import base64
        import json

        old = base64.urlsafe_b64encode(
            json.dumps({"v": 1, "f": "price", "a": False, "k": "1", "i": 1}).encode()
        ).decode()

        with pytest.raises(BadCursor, match="старом формате"):
            decode_cursor(old, SortSpec(field="price"))

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(BadCursor):
            decode_cursor("не-курсор", SortSpec())

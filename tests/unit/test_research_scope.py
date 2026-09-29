"""Как охват прогона превращается в условия выборки.

Проверяется через скомпилированный SQL: `_period` — единственное место, где
воля пользователя («прогнать по этим регионам за этот срок») встречается с
умолчаниями критерия, и разойтись они не имеют права.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from libs.shared.db.schema import Tender
from services.research.domain.criteria import Structural
from services.research.infrastructure.repositories import _period


def _sql(*conditions) -> str:
    statement = select(Tender.id).where(*conditions)
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestRegions:
    def test_the_chosen_regions_win_over_the_criteria(self) -> None:
        """Объединение молча расширило бы прогон за пределы запрошенного."""
        sql = _sql(*_period(["78"], None, None, Structural(regions=["77"])))

        assert "'78'" in sql
        assert "'77'" not in sql

    def test_the_criteria_regions_are_the_default(self) -> None:
        sql = _sql(*_period(None, None, None, Structural(regions=["77"])))

        assert "'77'" in sql

    def test_no_regions_anywhere_means_the_whole_corpus(self) -> None:
        sql = _sql(*_period(None, None, None, Structural()))

        assert "region_code" not in sql


class TestPeriod:
    def test_both_ends_become_conditions(self) -> None:
        sql = _sql(*_period(None, date(2026, 7, 1), date(2026, 7, 31), None))

        assert "publish_date >=" in sql
        assert "publish_date <" in sql

    def test_the_last_day_is_included_whole(self) -> None:
        """`until` — включительно: иначе последний день выпадал бы молча."""
        sql = _sql(*_period(None, None, date(2026, 7, 31), None))

        assert "2026-08-01" in sql

    def test_an_open_period_is_allowed(self) -> None:
        sql = _sql(*_period(None, date(2026, 7, 1), None, None))

        assert "publish_date >=" in sql
        assert "publish_date <" not in sql.replace("publish_date >=", "")


class TestStructuralConditions:
    def test_price_and_customers_come_from_the_criteria(self) -> None:
        sql = _sql(
            *_period(
                None,
                None,
                None,
                Structural(customer_inns=["7718690579"], price_min=1000),
            )
        )

        assert "7718690579" in sql
        assert "price >=" in sql

    def test_an_empty_scope_still_yields_a_valid_query(self) -> None:
        """Пустой набор условий обязан оставаться корректным SQL."""
        assert "SELECT" in _sql(*_period(None, None, None, None))

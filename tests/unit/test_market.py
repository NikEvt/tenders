"""Разрезы рынка.

Главная проверка — сверка с цифрами, опубликованными в ретроспективе: сводка
считается по тому же набору и обязана дать те же числа.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from services.research.domain.market import MarketTender, summarize

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def millions(value: Decimal | None) -> float:
    return round(float(value) / 1e6, 1) if value is not None else 0.0


@pytest.fixture(scope="module")
def confirmed() -> list[MarketTender]:
    golden = json.loads((FIXTURES / "hpk_golden.json").read_text(encoding="utf-8"))
    return [
        MarketTender(
            reg_num=tender["reg_num"],
            name=tender["name"],
            price=Decimal(str(tender["price"])) if tender["price"] is not None else None,
            region_code=tender["region"],
            customer_name=tender["customer_name"],
            customer_inn=tender["customer_inn"],
            okpd2_code=(tender["okpd2_codes"] or [None])[0],
        )
        for tender in golden["tenders"]
        if tender["label"] == "confirmed"
    ]


class TestAgainstThePublishedNumbers:
    def test_totals_match_the_retrospective(self, confirmed) -> None:
        """56 закупок на 304.0 млн ₽ — то, что ушло заказчику."""
        summary = summarize(confirmed)

        assert summary.total_count == 56
        assert summary.priced_count == 56
        assert millions(summary.total_value) == 304.0

    def test_median_and_mean_show_the_tail(self, confirmed) -> None:
        """Медиана 2.91 при среднем 5.43 — распределение с тяжёлым хвостом.

        Одно среднее описало бы рынок, которого нет: половина закупок вдвое
        дешевле «средней».
        """
        summary = summarize(confirmed)

        assert millions(summary.median_price) == 2.9
        assert millions(summary.average_price) == 5.4
        assert summary.median_price < summary.average_price

    def test_three_biggest_give_a_third_of_the_money(self, confirmed) -> None:
        assert summarize(confirmed).top_share == pytest.approx(0.33, abs=0.05)

    @pytest.mark.parametrize(
        ("region", "count", "total", "average"),
        [
            ("Московская область", 21, 186.2, 8.9),
            ("Москва", 29, 101.3, 3.5),
            ("Санкт-Петербург", 6, 16.5, 2.8),
        ],
    )
    def test_regions_match(
        self, confirmed, region: str, count: int, total: float, average: float
    ) -> None:
        """Подмосковье обгоняет Москву по деньгам вдвое при меньшем числе закупок."""
        bucket = next(b for b in summarize(confirmed).by_region if b.label == region)

        assert bucket.count == count
        assert millions(bucket.total) == total
        assert millions(bucket.average) == average

    def test_regions_are_ordered_by_money(self, confirmed) -> None:
        labels = [b.label for b in summarize(confirmed).by_region]
        assert labels[:3] == ["Московская область", "Москва", "Санкт-Петербург"]


class TestCustomerGrouping:
    def test_customers_are_grouped_by_inn(self, confirmed) -> None:
        """По ИНН, а не по названию — и это меняет ответ.

        Под именем «Центр гигиены и эпидемиологии» в наборе скрываются восемь
        закупок **четырёх разных юрлиц**. Группировка по строке слила бы их в
        одну строку отчёта и показала бы заказчика, которого не существует.
        """
        summary = summarize(confirmed)
        hygiene = [
            bucket
            for bucket in summary.by_customer
            if "ГИГИЕН" in bucket.label.upper()
        ]

        assert len(hygiene) >= 3
        assert sum(b.count for b in hygiene) == 8
        # Самый крупный — тот, что в ретроспективе описан как «четыре закупки в МО».
        assert max(b.count for b in hygiene) == 4

    def test_label_keeps_a_readable_name(self, confirmed) -> None:
        """Ключ — ИНН, но в отчёте человек должен видеть название."""
        summary = summarize(confirmed)
        assert all(not bucket.label.isdigit() for bucket in summary.by_customer[:5])


class TestEdgeCases:
    def test_empty_set_is_not_an_error(self) -> None:
        summary = summarize([])

        assert summary.total_count == 0
        assert summary.total_value == Decimal(0)
        assert summary.median_price is None
        assert summary.by_region == []

    def test_tenders_without_price_are_counted_separately(self) -> None:
        """Иначе «сумма 10 млн при 5 закупках» невозможно сопоставить."""
        summary = summarize(
            [
                MarketTender(reg_num="A", price=Decimal("1000000"), region_code="77"),
                MarketTender(reg_num="B", price=None, region_code="77"),
            ]
        )

        assert summary.total_count == 2
        assert summary.priced_count == 1
        assert summary.total_value == Decimal("1000000")

    def test_all_prices_missing_leaves_statistics_empty(self) -> None:
        summary = summarize([MarketTender(reg_num="A"), MarketTender(reg_num="B")])

        assert summary.total_count == 2
        assert summary.median_price is None
        assert summary.average_price is None
        assert summary.top_share == 0.0

    def test_unknown_region_gets_a_placeholder(self) -> None:
        summary = summarize([MarketTender(reg_num="A", region_code=None)])
        assert summary.by_region[0].label == "—"

    def test_okpd2_is_grouped_by_its_first_two_digits(self) -> None:
        """Разрез по полному коду распался бы на почти уникальные значения."""
        summary = summarize(
            [
                MarketTender(reg_num="A", okpd2_code="71.20.11", price=Decimal(1)),
                MarketTender(reg_num="B", okpd2_code="71.20.19", price=Decimal(1)),
            ]
        )

        assert len(summary.by_okpd2) == 1
        assert summary.by_okpd2[0].count == 2

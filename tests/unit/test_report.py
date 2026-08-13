"""Отчёт: атомарная подмена и невозможность уронить им прогон."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from services.research.application.ports import TenderVerdict
from services.research.domain.criteria import Confidence
from services.research.domain.market import MarketTender
from services.research.infrastructure.report import (
    ReportRow,
    build_report,
    safe_report,
)


def row(
    reg_num: str,
    confidence: Confidence = Confidence.CONFIRMED,
    quote: str = "норматив по показателю БПК5",
    price: str = "1000000",
) -> ReportRow:
    return ReportRow(
        verdict=TenderVerdict(
            tender_id=abs(hash(reg_num)) % 10_000,
            confidence=confidence,
            reason="химия воды",
            decided_by="rules",
        ),
        tender=MarketTender(
            reg_num=reg_num,
            name="Анализ сточных вод",
            price=Decimal(price),
            region_code="50",
            customer_name="Водоканал",
            customer_inn="5000000001",
            okpd2_code="71.20.11",
        ),
        quote=quote,
        file_name="ТЗ.docx",
    )


def sheets(path: Path) -> dict[str, list[list]]:
    book = openpyxl.load_workbook(path)
    return {name: list(book[name].iter_rows(values_only=True)) for name in book.sheetnames}


class TestContents:
    def test_verdicts_are_split_across_sheets(self, tmp_path: Path) -> None:
        path = tmp_path / "отчёт.xlsx"
        build_report(
            path,
            [row("A"), row("B", Confidence.REJECTED), row("C")],
        )

        data = sheets(path)
        assert len(data["Подтверждённые"]) == 3  # шапка + две закупки
        assert len(data["Отклонённые"]) == 2

    def test_market_sheet_summarises_only_confirmed(self, tmp_path: Path) -> None:
        """Отклонённые в рыночную сводку попадать не должны."""
        path = tmp_path / "отчёт.xlsx"
        build_report(
            path,
            [
                row("A", price="1000000"),
                row("B", Confidence.REJECTED, price="99000000"),
            ],
        )

        totals = next(
            line for line in sheets(path)["Рынок"] if line[2] == "закупок"
        )
        assert totals[3] == 1
        assert totals[4] == 1_000_000

    def test_price_stays_a_number(self, tmp_path: Path) -> None:
        """Иначе столбец с ценой в отчёте не отсортировать."""
        path = tmp_path / "отчёт.xlsx"
        build_report(path, [row("A", price="2500000")])

        line = sheets(path)["Подтверждённые"][1]
        assert line[3] == 2_500_000
        assert isinstance(line[3], int | float)

    def test_link_to_the_notice_is_built(self, tmp_path: Path) -> None:
        path = tmp_path / "отчёт.xlsx"
        build_report(path, [row("0848300046026000323")])

        assert "0848300046026000323" in sheets(path)["Подтверждённые"][1][0]


class TestIllegalCharacters:
    def test_the_character_that_killed_the_run_does_not_kill_the_report(
        self, tmp_path: Path
    ) -> None:
        """U+FFFE из текстового слоя PDF — тот самый случай."""
        path = tmp_path / "отчёт.xlsx"
        build_report(path, [row("A", quote="аммоний￾ион, БПК5")])

        assert "аммонийион" in sheets(path)["Подтверждённые"][1][12]

    def test_surrogates_do_not_break_the_export(self, tmp_path: Path) -> None:
        path = tmp_path / "отчёт.xlsx"
        build_report(path, [row("A", quote=f"текст{chr(0xD800)} и БПК")])

        assert path.exists()


class TestAtomicSwap:
    def test_previous_report_survives_a_failed_build(self, tmp_path: Path) -> None:
        """Открытый отчёт не должен оказаться обрезанным на середине записи."""
        path = tmp_path / "отчёт.xlsx"
        build_report(path, [row("A")])
        before = path.read_bytes()

        # Тип исключения здесь неважен: openpyxl бросает своё. Проверяется то,
        # что прежний файл цел, чем бы сборка ни кончилась.
        with pytest.raises(ValueError):
            build_report(path, [_exploding_row()])

        assert path.read_bytes() == before

    def test_no_temporary_files_are_left_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "отчёт.xlsx"
        with pytest.raises(ValueError):
            build_report(path, [_exploding_row()])

        assert list(tmp_path.iterdir()) == []

    def test_report_is_rewritten_in_place(self, tmp_path: Path) -> None:
        path = tmp_path / "отчёт.xlsx"
        build_report(path, [row("A")])
        build_report(path, [row("A"), row("B")])

        assert len(sheets(path)["Подтверждённые"]) == 3


class TestSafeReport:
    def test_failure_costs_a_log_line_not_the_run(self, tmp_path: Path) -> None:
        """Вспомогательное действие не имеет права стоить основного."""
        assert safe_report(tmp_path / "отчёт.xlsx", [_exploding_row()]) is False

    def test_success_is_reported_as_such(self, tmp_path: Path) -> None:
        assert safe_report(tmp_path / "отчёт.xlsx", [row("A")]) is True

    def test_unwritable_path_does_not_raise(self, tmp_path: Path) -> None:
        target = tmp_path / "файл"
        target.write_text("не каталог")

        assert safe_report(target / "внутри.xlsx", [row("A")]) is False


class _Exploding:
    """Значение, которое openpyxl записать не сможет.

    Ровно то, обо что споткнулся отчёт в прогоне: объект, не приводимый к типу
    ячейки. Сюда же попадали бы недопустимые символы, если бы их не чистили.
    """


def _exploding_row() -> ReportRow:
    broken = row("BOOM")
    return ReportRow(
        verdict=broken.verdict,
        tender=MarketTender(reg_num="BOOM", name=_Exploding()),  # type: ignore[arg-type]
        quote="",
    )

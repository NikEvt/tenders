"""Справочник субъектов: полнота и совпадение с закоммиченным TypeScript."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.shared.config import EisSettings
from libs.shared.regions import (
    RUSSIAN_REGIONS,
    UNKNOWN_REGION,
    is_known_region,
    normalize_region_code,
    region_name,
)
from scripts.gen_regions_ts import TARGET, render


class TestTheList:
    def test_all_eighty_five_subjects_are_there(self) -> None:
        """Частичная вставка ужала бы пикер молча — пусть падает громко."""
        assert len(RUSSIAN_REGIONS) == 85

    def test_codes_are_two_digits(self) -> None:
        assert all(len(code) == 2 and code.isdigit() for code in RUSSIAN_REGIONS)

    def test_names_are_unique(self) -> None:
        assert len(set(RUSSIAN_REGIONS.values())) == len(RUSSIAN_REGIONS)


class TestNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("77", "77"), ("077", "77"), ("7", "07"), (" 50 ", "50"), ("00", "00")],
    )
    def test_codes_come_in_all_shapes(self, raw: str, expected: str) -> None:
        """ЕИС шлёт то `77`, то `077`, то `7`."""
        assert normalize_region_code(raw) == expected

    def test_unrecognizable_values_pass_through(self) -> None:
        """Столбец свободный: молча испортить незнакомое хуже, чем не узнать."""
        assert normalize_region_code("ABC") == "ABC"
        assert normalize_region_code(None) is None
        assert normalize_region_code("") is None


class TestNaming:
    def test_known_codes_get_their_name(self) -> None:
        assert region_name("77") == "Москва"
        assert region_name("077") == "Москва"

    def test_unknown_codes_keep_the_code_visible(self) -> None:
        """Незнакомый код — обычное дело, а не сбой: он должен остаться виден."""
        assert region_name("99") == "Регион 99"

    def test_the_placeholder_survives_a_round_trip(self) -> None:
        """Разрезы группируют закупки без региона под этим же ключом."""
        assert region_name(None) == UNKNOWN_REGION
        assert region_name(UNKNOWN_REGION) == UNKNOWN_REGION

    def test_membership_is_checked_after_normalization(self) -> None:
        assert is_known_region("077")
        assert not is_known_region("99")
        assert not is_known_region(None)


class TestTheGeneratedCopy:
    def test_committed_typescript_matches_the_source(self) -> None:
        """Разошедшаяся копия — то, ради чего справочник и сводили в одно место.

        Если тест упал: `.venv/bin/python -m scripts.gen_regions_ts`.
        """
        committed = Path(TARGET).read_text(encoding="utf-8")
        assert committed == render()


class TestCrawlerScope:
    """`EIS_REGIONS=all` разворачивается по тому же справочнику."""

    def test_the_sentinel_expands_to_every_subject(self, monkeypatch) -> None:
        monkeypatch.setenv("EIS_REGIONS", "all")
        assert len(EisSettings().region_list) == len(RUSSIAN_REGIONS)

    def test_the_sentinel_is_case_insensitive(self, monkeypatch) -> None:
        monkeypatch.setenv("EIS_REGIONS", " ALL ")
        assert len(EisSettings().region_list) == 85

    def test_an_explicit_list_still_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("EIS_REGIONS", "77, 78")
        assert EisSettings().region_list == ["77", "78"]

    def test_an_empty_setting_yields_nothing(self, monkeypatch) -> None:
        """Пусто — значит пусто: молча качать всю страну нельзя."""
        monkeypatch.setenv("EIS_REGIONS", "")
        assert EisSettings().region_list == []

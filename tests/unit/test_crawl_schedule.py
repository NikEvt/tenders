"""Дневной проход краулера: какое окно он заказывает.

Своего сценария у расписания больше нет — оно зовёт тот же
`CrawlPeriodUseCase`, что и заявка событием. Проверять поэтому надо ровно одно:
границы окна. Всё остальное про выгрузку периода покрыто `test_crawl_period.py`
и покрыто там же, где живёт.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

import pytest

from services.crawler.presentation.cli import _window, parse_args

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def _args(days_back: int = 1) -> argparse.Namespace:
    return argparse.Namespace(date=None, days_back=days_back)


class TestWindow:
    def test_default_is_yesterday_alone(self) -> None:
        """ЕИС отдаёт выгрузку за завершившийся день, поэтому не сегодня."""
        assert _window(_args()) == (YESTERDAY, YESTERDAY)

    def test_days_back_extends_backwards(self) -> None:
        """`--days-back 3` — вчера и два дня до него, а не три дня вперёд."""
        date_from, date_to = _window(_args(days_back=3))

        assert date_to == YESTERDAY
        assert date_from == YESTERDAY - timedelta(days=2)
        assert (date_to - date_from).days == 2

    def test_explicit_date_wins(self) -> None:
        target = date(2026, 7, 1)
        assert _window(argparse.Namespace(date=target, days_back=1)) == (target, target)

    def test_explicit_date_with_depth(self) -> None:
        target = date(2026, 7, 10)
        assert _window(argparse.Namespace(date=target, days_back=4)) == (
            date(2026, 7, 7),
            target,
        )

    @pytest.mark.parametrize("depth", [0, -5])
    def test_nonsensical_depth_still_gives_one_day(self, depth: int) -> None:
        """Ноль дней назад — это один день, а не пустое окно."""
        date_from, date_to = _window(_args(days_back=depth))
        assert date_from == date_to == YESTERDAY

    def test_window_never_runs_backwards(self) -> None:
        date_from, date_to = _window(_args(days_back=7))
        assert date_from <= date_to


class TestArgs:
    def test_defaults_match_the_daily_pass(self) -> None:
        args = parse_args([])

        assert args.date is None
        assert args.days_back == 1
        assert args.once is False
        assert args.since is None

    def test_regions_accumulate(self) -> None:
        assert parse_args(["--region", "77", "--region", "78"]).region == ["77", "78"]

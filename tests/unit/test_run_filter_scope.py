"""Охват прогона: что принимает запрос и что уезжает в событие.

Движок умел регионы и сроки всегда — `ResearchRequested` их нёс, воркер
прокидывал, `research_runs` хранил. Не доезжали они ровно на двух HTTP-переходах,
поэтому тесты здесь про границу, а не про отбор.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from libs.shared.contracts.events import ResearchRequested
from services.api.presentation.schemas import RunFilterIn
from services.llm_service.presentation.app import RunFilterRequest


class TestTheRequestShape:
    def test_regions_and_period_are_accepted(self) -> None:
        request = RunFilterRequest(
            since=date(2026, 7, 1), until=date(2026, 7, 31), regions=["77", "78"]
        )

        assert request.regions == ["77", "78"]
        assert request.until == date(2026, 7, 31)

    def test_scope_is_optional(self) -> None:
        """Пустой охват — весь корпус: прежнее поведение не должно ломаться."""
        request = RunFilterRequest()

        assert request.regions == []
        assert request.since is None and request.until is None

    def test_the_gateway_mirrors_the_same_fields(self) -> None:
        """Схема шлюза и схема сервиса обязаны совпадать полями."""
        assert set(RunFilterIn.model_fields) == set(RunFilterRequest.model_fields)

    def test_the_dead_parameter_is_gone(self) -> None:
        """`tender_ids` принимался, пересылался и не читался никогда."""
        assert "tender_ids" not in RunFilterRequest.model_fields
        assert "tender_ids" not in RunFilterIn.model_fields

    def test_a_malformed_region_is_refused_by_the_type(self) -> None:
        with pytest.raises(ValidationError):
            RunFilterRequest(regions="77")  # type: ignore[arg-type]


class TestTheEventCarriesTheScope:
    def test_everything_survives_the_hop(self) -> None:
        event = ResearchRequested(
            filter_id=1,
            job_id="6f1b1e9c-0000-4000-8000-000000000000",
            regions=["77"],
            since=date(2026, 7, 1),
            until=date(2026, 7, 31),
        )

        assert event.regions == ["77"]
        assert event.since == date(2026, 7, 1)
        assert event.until == date(2026, 7, 31)

    def test_a_test_run_is_marked_as_such(self) -> None:
        """`dry_run` гасит запись вердиктов — без него тест пачкает каталог."""
        event = ResearchRequested(
            filter_id=1, job_id="6f1b1e9c-0000-4000-8000-000000000000", dry_run=True
        )

        assert event.dry_run is True

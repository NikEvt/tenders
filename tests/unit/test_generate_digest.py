"""Сборка сводки и то, что о ней узнаёт экран.

Сборка идёт минутами — до девяти последовательных обращений к модели. Пока
задание не заводилось, `POST /digest/{date}` возвращал идентификатор строки,
которой не существует: экран опрашивал её и ждал завершения, которое не
наступало никогда. Поэтому тесты здесь настолько же про учёт задания,
насколько про саму сводку.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from libs.shared.contracts.events import DigestRequested
from services.llm_service.application.ports import LlmUnavailable
from services.llm_service.application.use_cases.generate_digest import (
    MAX_CLUSTERS,
    PHASE_COLLECT,
    PHASE_SUMMARIZE,
    GenerateDigestUseCase,
)
from services.llm_service.domain.models import DigestInput, DigestScope, TenderCandidate

DIGEST_DATE = date(2026, 8, 13)


class FakeLlm:
    def __init__(self, fails: bool = False) -> None:
        self.calls = 0
        self.fails = fails

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def complete(self, system, user, max_tokens=2000, reasoning_effort=None) -> str:
        self.calls += 1
        if self.fails:
            raise LlmUnavailable("модель легла")
        return "текст"

    async def structured(self, *args, **kwargs):  # pragma: no cover - не нужен сводке
        raise NotImplementedError


class FakeDigests:
    def __init__(
        self,
        existing: bool = False,
        clusters: int = 2,
        total: int = 5,
        built_at: datetime | None = None,
        scope: DigestScope | None = None,
    ) -> None:
        # `existing` теперь означает «есть окончательная сводка»: собранная на
        # следующий день после своего. Черновик задаётся через `built_at`.
        self.built = built_at or (
            datetime.combine(DIGEST_DATE + timedelta(days=1), time(9, 0), tzinfo=UTC)
            if existing
            else None
        )
        self.clusters = clusters
        self.total = total
        self.scope = scope or DigestScope()
        self.saved: list[tuple] = []
        self.collect_calls = 0

    async def built_at(self, digest_date: date) -> datetime | None:
        return self.built

    async def collect(self, digest_date: date) -> DigestInput:
        self.collect_calls += 1
        return DigestInput(
            digest_date=digest_date,
            total=self.total,
            total_price=Decimal(100),
            top_by_price=[],
            clusters={
                f"Категория {i}": [_candidate(i)] for i in range(self.clusters)
            },
            deadline_changes=[],
            new_customers=[],
            scope=self.scope,
        )

    async def save(
        self, digest_date, summary_md, sections, tender_count, model, prompt_version
    ) -> None:
        self.saved.append((digest_date, tender_count))
        self.last_summary = summary_md
        self.last_sections = sections


class FakeJobs:
    def __init__(self, breaks: bool = False) -> None:
        self.started: list[tuple[str, str, int]] = []
        self.phases: list[str | None] = []
        self.reported: list[int] = []
        self.finished: list[dict] = []
        self.failed: list[str] = []
        self.breaks = breaks

    async def start(
        self, job_id: str, kind: str, total: int, phase: str | None = None
    ) -> None:
        if self.breaks:
            raise RuntimeError("база недоступна")
        self.started.append((job_id, kind, total))
        self.phases.append(phase)

    async def progress(self, job_id: str, processed: int) -> None:
        if self.breaks:
            raise RuntimeError("база недоступна")
        self.reported.append(processed)

    async def finish(self, job_id: str, result: dict) -> None:
        self.finished.append(result)

    async def fail(self, job_id: str, error: str) -> None:
        self.failed.append(error)


def _candidate(i: int) -> TenderCandidate:
    return TenderCandidate(
        tender_id=i,
        reg_num=f"REG-{i}",
        name=f"Закупка {i}",
        description=None,
        price=Decimal(10),
        customer_name="Заказчик",
        okpd2_code="32.50",
        end_date=None,
    )


def _event(force: bool = False) -> DigestRequested:
    return DigestRequested(digest_date=DIGEST_DATE, force=force)


class TestTheJobAlwaysEnds:
    """Незавершённое задание — вечный волчок на экране. Хуже любой ошибки."""

    @pytest.mark.asyncio
    async def test_a_normal_build_finishes(self) -> None:
        jobs = FakeJobs()
        digests = FakeDigests()
        await GenerateDigestUseCase(FakeLlm(), digests, jobs).execute(_event())

        assert digests.saved == [(DIGEST_DATE, 5)]
        assert jobs.finished[-1]["tender_count"] == 5
        assert jobs.failed == []

    @pytest.mark.asyncio
    async def test_an_existing_digest_still_finishes(self) -> None:
        """Короткое замыкание на `exists` возвращалось молча — экран ждал вечно."""
        jobs = FakeJobs()
        digests = FakeDigests(existing=True)

        await GenerateDigestUseCase(FakeLlm(), digests, jobs).execute(_event())

        assert digests.collect_calls == 0
        assert jobs.finished[-1]["skipped"] is True

    @pytest.mark.asyncio
    async def test_an_empty_day_still_finishes(self) -> None:
        jobs = FakeJobs()
        digests = FakeDigests(total=0)

        await GenerateDigestUseCase(FakeLlm(), digests, jobs).execute(_event())

        assert jobs.finished[-1]["tender_count"] == 0

    @pytest.mark.asyncio
    async def test_force_rebuilds_over_an_existing_digest(self) -> None:
        digests = FakeDigests(existing=True)
        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(_event(force=True))

        assert digests.collect_calls == 1
        assert digests.saved == [(DIGEST_DATE, 5)]

    @pytest.mark.asyncio
    async def test_a_failure_is_reported_and_still_raised(self) -> None:
        """Ошибка обязана доехать до экрана и всё равно уйти наверх — к повторам."""
        jobs = FakeJobs()

        class Broken(FakeDigests):
            async def collect(self, digest_date):
                raise RuntimeError("постгрес прилёг")

        with pytest.raises(RuntimeError):
            await GenerateDigestUseCase(FakeLlm(), Broken(), jobs).execute(_event())

        assert "постгрес прилёг" in jobs.failed[0]
        assert jobs.finished == []


class TestProgress:
    @pytest.mark.asyncio
    async def test_total_counts_every_call_to_the_model(self) -> None:
        """Резюме по категориям плюс сведение — столько шагов и показывает полоса."""
        jobs = FakeJobs()
        await GenerateDigestUseCase(FakeLlm(), FakeDigests(clusters=3), jobs).execute(_event())

        assert jobs.started[-1][2] == 4

    @pytest.mark.asyncio
    async def test_total_is_capped_by_the_cluster_limit(self) -> None:
        jobs = FakeJobs()
        await GenerateDigestUseCase(
            FakeLlm(), FakeDigests(clusters=MAX_CLUSTERS + 5), jobs
        ).execute(_event())

        assert jobs.started[-1][2] == MAX_CLUSTERS + 1

    @pytest.mark.asyncio
    async def test_progress_climbs(self) -> None:
        jobs = FakeJobs()
        await GenerateDigestUseCase(FakeLlm(), FakeDigests(clusters=3), jobs).execute(_event())

        assert jobs.reported == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_the_phase_changes_when_the_work_becomes_countable(self) -> None:
        """Сбор идёт без знаменателя, резюме — со знаменателем. Это разные фазы.

        Без имён экран показывал бы одно «идёт» на обе и не мог бы объяснить,
        почему полоса появилась не сразу.
        """
        jobs = FakeJobs()
        await GenerateDigestUseCase(FakeLlm(), FakeDigests(clusters=3), jobs).execute(_event())

        assert jobs.phases == [PHASE_COLLECT, PHASE_SUMMARIZE]

    @pytest.mark.asyncio
    async def test_the_first_phase_admits_it_does_not_know_the_volume(self) -> None:
        """`total = 0` — «объём ещё не считали», и наружу это уходит как «неизвестно».

        Ноль в этом месте заставил бы клиента показать «0 %» там, где считать
        пока нечего, то есть выдумать число.
        """
        jobs = FakeJobs()
        await GenerateDigestUseCase(FakeLlm(), FakeDigests(clusters=3), jobs).execute(_event())

        assert jobs.started[0][2] == 0


class TestAuxiliaryFailuresDoNotSinkTheDigest:
    """Инвариант 5: вспомогательное не роняет основное."""

    @pytest.mark.asyncio
    async def test_a_broken_tracker_still_lets_the_digest_through(self) -> None:
        digests = FakeDigests()
        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs(breaks=True)).execute(_event())

        assert digests.saved == [(DIGEST_DATE, 5)]

    @pytest.mark.asyncio
    async def test_a_fallen_model_degrades_but_saves(self) -> None:
        digests = FakeDigests()
        await GenerateDigestUseCase(FakeLlm(fails=True), digests, FakeJobs()).execute(_event())

        assert digests.saved == [(DIGEST_DATE, 5)]


class TestWithoutATracker:
    @pytest.mark.asyncio
    async def test_the_use_case_works_unwired(self) -> None:
        """Порт необязателен: сводка не должна зависеть от учёта заданий."""
        digests = FakeDigests()
        await GenerateDigestUseCase(FakeLlm(), digests).execute(_event())

        assert digests.saved == [(DIGEST_DATE, 5)]


@pytest.mark.asyncio
async def test_the_job_id_is_the_event_id() -> None:
    """`POST /digest/{date}` возвращает идентификатор события — по нему и опрашивают.

    Совпадение обязательно: разойдись они, экран опрашивал бы чужой ключ.
    """
    jobs = FakeJobs()
    event = _event()

    await GenerateDigestUseCase(FakeLlm(), FakeDigests(), jobs).execute(event)

    assert jobs.started[0][0] == str(event.event_id)
    assert jobs.started[0][1] == "digest"


class TestDraftVersusFinal:
    """Сводка за идущий день — черновик, и замораживать его нельзя.

    Прежний `exists` знал только факт наличия. Из-за этого сводка за 13 августа
    навсегда осталась с четырьмястами закупками из 4878: собрали её раньше, чем
    доехали данные, а пересобрать было некому.
    """

    @pytest.mark.asyncio
    async def test_a_digest_built_after_its_day_is_never_rebuilt(self) -> None:
        digests = FakeDigests(
            built_at=datetime.combine(
                DIGEST_DATE + timedelta(days=1), time(9, 0), tzinfo=UTC
            )
        )

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(_event())

        assert digests.collect_calls == 0

    @pytest.mark.asyncio
    async def test_a_stale_draft_is_rebuilt(self) -> None:
        """Черновик, собранный в середине своего дня, обязан пересобираться."""
        digests = FakeDigests(
            built_at=datetime.combine(DIGEST_DATE, time(11, 52), tzinfo=UTC)
        )

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(_event())

        assert digests.collect_calls == 1

    @pytest.mark.asyncio
    async def test_a_fresh_draft_is_left_alone(self) -> None:
        """Но не на каждый рестарт: сборка — это до девяти обращений к модели."""
        today = date.today()
        digests = FakeDigests(built_at=datetime.now(UTC) - timedelta(minutes=5))

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(
            DigestRequested(digest_date=today)
        )

        assert digests.collect_calls == 0

    @pytest.mark.asyncio
    async def test_force_rebuilds_a_final_digest(self) -> None:
        digests = FakeDigests(
            built_at=datetime.combine(
                DIGEST_DATE + timedelta(days=1), time(9, 0), tzinfo=UTC
            )
        )

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(
            _event(force=True)
        )

        assert digests.collect_calls == 1


class TestScopeIsStated:
    """Область отбора — часть материала, а не пометка.

    «За день 16 закупок» означает совершенно разное, когда это весь день и
    когда это отбор по двум фильтрам.
    """

    @pytest.mark.asyncio
    async def test_the_scope_travels_with_the_digest(self) -> None:
        digests = FakeDigests(scope=DigestScope(filters=["газовые смеси"]))

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(_event())

        assert digests.last_sections["scope"]["filters"] == ["газовые смеси"]
        assert digests.last_sections["scope"]["filtered"] is True

    @pytest.mark.asyncio
    async def test_an_empty_day_without_filters_talks_about_the_market(self) -> None:
        digests = FakeDigests(total=0)

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(_event())

        assert "новых закупок не найдено" in digests.last_summary

    @pytest.mark.asyncio
    async def test_an_empty_day_with_filters_talks_about_the_filters(self) -> None:
        """«Ничего не опубликовали» и «ничего не прошло отбор» — разные вещи."""
        digests = FakeDigests(total=0, scope=DigestScope(filters=["газовые смеси"]))

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(_event())

        assert "не прошла отбор" in digests.last_summary
        assert "газовые смеси" in digests.last_summary

    @pytest.mark.asyncio
    async def test_an_unrun_filter_is_named_out_loud(self) -> None:
        """Фильтр без прогонов не приносит закупок — это несделанная работа,
        а не вывод о рынке, и сводка обязана сказать это прямо."""
        digests = FakeDigests(
            total=0,
            scope=DigestScope(filters=["баллоны"], unrun_filters=["баллоны"]),
        )

        await GenerateDigestUseCase(FakeLlm(), digests, FakeJobs()).execute(_event())

        assert "ни разу не запускались" in digests.last_summary

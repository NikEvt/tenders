"""Таблица заданий: то, по чему рисуется шкала ожидания.

Таблица общая для трёх сервисов — пишут в неё движок отбора, llm-сервис и
краулер, а читает шлюз. Кода они друг у друга не берут (сервисы не импортируют
друг друга), поэтому договор держится только на самой таблице. Здесь он и
проверяется: писатель из одного сервиса, читатель из другого.

Требует Postgres, как и остальные интеграционные тесты.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from libs.shared.db.schema import Job
from services.api.infrastructure.db.job_repository import SqlJobRepository
from services.research.infrastructure.jobs import SqlJobTracker

PREFIX = "TEST-JOB-"


@pytest.fixture
async def jobs(session_factory):
    yield SqlJobRepository(session_factory)
    async with session_factory() as session, session.begin():
        await session.execute(delete(Job).where(Job.id.like(f"{PREFIX}%")))


async def _put_job(session_factory, suffix: str, **values) -> str:
    job_id = f"{PREFIX}{suffix}"
    async with session_factory() as session, session.begin():
        session.add(Job(id=job_id, kind="research", status="running", **values))
    return job_id


@pytest.mark.asyncio
async def test_job_carries_its_phase_and_start(session_factory, jobs) -> None:
    job_id = await _put_job(
        session_factory, "JUDGE", phase="судья читает документы", total=8, processed=3
    )

    view = await jobs.get(job_id)

    assert view is not None
    assert view.phase == "судья читает документы"
    assert (view.processed, view.total) == (3, 8)
    assert view.created_at is not None


@pytest.mark.asyncio
async def test_an_uncounted_job_reports_unknown_not_zero(session_factory, jobs) -> None:
    """`total = 0` в базе означает «объём ещё не считали».

    Наружу это обязано уходить как «неизвестно»: ноль заставил бы экран
    показать «0 %» там, где знаменателя не существует, — то есть выдумать
    число. Именно так начинается сборка сводки: `start` зовут до того, как
    объём работы известен.
    """
    job_id = await _put_job(session_factory, "FRESH", total=0, processed=0)

    view = await jobs.get(job_id)

    assert view is not None
    assert view.total is None


@pytest.mark.asyncio
async def test_a_new_phase_starts_its_own_count(session_factory, jobs) -> None:
    """Перевод в следующую фазу обнуляет счётчик: у неё свой знаменатель.

    Оставить прежнее число значило бы стартовать шкалу второй фазы с чужого
    места — например, с «180 из 12».
    """
    job_id = await _put_job(
        session_factory, "PHASES", phase="обход корпуса", total=180, processed=180
    )

    await SqlJobTracker(session_factory).start(
        job_id, "research", 12, "судья читает документы"
    )

    view = await jobs.get(job_id)
    assert view is not None
    assert (view.phase, view.total, view.processed) == ("судья читает документы", 12, 0)


@pytest.mark.asyncio
async def test_a_job_without_a_phase_is_still_readable(session_factory, jobs) -> None:
    """Задания, начатые до появления колонки, читаются без фазы, а не падают."""
    job_id = await _put_job(session_factory, "LEGACY", total=5, processed=5)

    view = await jobs.get(job_id)

    assert view is not None
    assert view.phase is None

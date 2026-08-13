"""Сводка за день и статус длительного задания.

Оба сценария об одном: отсутствие строки — это 404 с внятным текстом, а не
пустой ответ, по которому клиенту нечего показать пользователю.
"""

from __future__ import annotations

from datetime import date

from services.api.application.errors import InvalidRequest, NotFound
from services.api.application.ports.digest import DigestReadPort
from services.api.application.ports.jobs import JobReadPort


class GetDigestUseCase:
    def __init__(self, digests: DigestReadPort) -> None:
        self._digests = digests

    async def execute(self, digest_date: date) -> dict:
        found = await self._digests.get(digest_date)
        if found is None:
            raise NotFound(
                f"Сводка за {digest_date.isoformat()} ещё не сформирована",
                digest_date=digest_date.isoformat(),
            )
        return found


class ListDigestDatesUseCase:
    """За какие дни сводки есть — точки в календаре, а не перебор 404-ми."""

    def __init__(self, digests: DigestReadPort) -> None:
        self._digests = digests

    async def execute(self, since: date, until: date) -> list[date]:
        if until < since:
            raise InvalidRequest("Конец периода раньше начала")
        return await self._digests.dates(since, until)


class GetJobUseCase:
    def __init__(self, jobs: JobReadPort) -> None:
        self._jobs = jobs

    async def execute(self, job_id: str) -> dict:
        job = await self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"Задание {job_id} не найдено", job_id=job_id)
        return job

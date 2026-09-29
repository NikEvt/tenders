"""Порт чтения статуса длительных заданий."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.api.domain.jobs import JobView


class JobReadPort(ABC):
    @abstractmethod
    async def get(self, job_id: str) -> JobView | None: ...

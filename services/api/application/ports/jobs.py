"""Порт чтения статуса длительных заданий."""

from __future__ import annotations

from abc import ABC, abstractmethod


class JobReadPort(ABC):
    @abstractmethod
    async def get(self, job_id: str) -> dict | None: ...

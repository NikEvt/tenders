"""Порты раздела «Мониторинг» и настроек."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.api.domain.monitoring import (
    CrawlerRunView,
    PipelineFunnel,
    QueuesSnapshot,
    ServiceHealth,
    TenderEvent,
)


class ServiceProbePort(ABC):
    @abstractmethod
    async def probe_all(self) -> list[ServiceHealth]:
        """Опрашивает все сервисы разом.

        Отказ одного даёт `status: down` в его плитке, а не ошибку всего
        ответа: иначе упавший сервис прятал бы состояние остальных именно
        тогда, когда на экран смотрят.
        """


class QueueAdminPort(ABC):
    @abstractmethod
    async def snapshot(self) -> QueuesSnapshot: ...

    @abstractmethod
    async def requeue_dead_letter(self, message_id: str) -> bool:
        """Возвращает сообщение из dead-letter в работу. False — не найдено."""


class CrawlerRunReadPort(ABC):
    @abstractmethod
    async def recent(self, limit: int) -> list[CrawlerRunView]: ...


class DocumentPipelinePort(ABC):
    @abstractmethod
    async def funnel(self) -> PipelineFunnel: ...


class EventTrailPort(ABC):
    @abstractmethod
    async def for_tender(self, tender_id: int) -> list[TenderEvent]: ...


class AppStatePort(ABC):
    """Состояние интерфейса. Единственное, куда шлюз пишет сам."""

    @abstractmethod
    async def get(self, key: str) -> dict | None: ...

    @abstractmethod
    async def set(self, key: str, value: dict) -> None: ...

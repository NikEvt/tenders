"""Сценарии раздела «Мониторинг» и настроек."""

from __future__ import annotations

from datetime import UTC, datetime

from services.api.application.errors import NotFound
from services.api.application.ports.catalog import TenderCatalogPort
from services.api.application.ports.monitoring import (
    AppStatePort,
    CrawlerRunReadPort,
    DocumentPipelinePort,
    EventTrailPort,
    QueueAdminPort,
    ServiceProbePort,
)
from services.api.application.ports.settings import RuntimeSettingsPort
from services.api.domain.monitoring import (
    CrawlerRunView,
    PipelineFunnel,
    QueuesSnapshot,
    ServiceHealth,
    TenderEvent,
)
from services.api.domain.settings import TOKEN_ROTATED_KEY, EffectiveSettings


class CollectHealthUseCase:
    def __init__(self, probe: ServiceProbePort) -> None:
        self._probe = probe

    async def execute(self) -> list[ServiceHealth]:
        return await self._probe.probe_all()


class InspectQueuesUseCase:
    def __init__(self, queues: QueueAdminPort) -> None:
        self._queues = queues

    async def execute(self) -> QueuesSnapshot:
        return await self._queues.snapshot()


class RetryDeadLetterUseCase:
    def __init__(self, queues: QueueAdminPort) -> None:
        self._queues = queues

    async def execute(self, message_id: str) -> None:
        if not await self._queues.requeue_dead_letter(message_id):
            raise NotFound(
                f"Сообщение {message_id} не найдено среди недоставленных",
                message_id=message_id,
            )


class CrawlerRunsUseCase:
    def __init__(self, runs: CrawlerRunReadPort) -> None:
        self._runs = runs

    async def execute(self, limit: int) -> list[CrawlerRunView]:
        return await self._runs.recent(limit)


class DocumentPipelineUseCase:
    def __init__(self, pipeline: DocumentPipelinePort) -> None:
        self._pipeline = pipeline

    async def execute(self) -> PipelineFunnel:
        return await self._pipeline.funnel()


class TenderEventsUseCase:
    """След закупки: что публиковалось, что дошло, что застряло."""

    def __init__(self, catalog: TenderCatalogPort, events: EventTrailPort) -> None:
        self._catalog = catalog
        self._events = events

    async def execute(self, reg_num: str) -> list[TenderEvent]:
        tender_id = await self._catalog.tender_id(reg_num)
        if tender_id is None:
            raise NotFound(f"Закупка {reg_num} не найдена", reg_num=reg_num)
        return await self._events.for_tender(tender_id)


class ReadSettingsUseCase:
    """Действующие настройки плюс отметка о ротации токена.

    Сами настройки приходят из окружения, а отметка — единственное, что
    интерфейс когда-либо записывал, поэтому она хранится отдельно.
    """

    def __init__(self, settings: RuntimeSettingsPort, state: AppStatePort) -> None:
        self._settings = settings
        self._state = state

    async def execute(self) -> EffectiveSettings:
        effective = self._settings.effective()
        stored = await self._state.get(TOKEN_ROTATED_KEY)
        if stored and isinstance(stored.get("at"), str):
            effective.eis_token.rotated_at = datetime.fromisoformat(stored["at"])
        return effective


class ConfirmTokenRotationUseCase:
    """Отметка «токен перевыпущен».

    Сам токен приходит из окружения и шлюзу неподвластен — записывается только
    факт и время, чтобы на экране было видно, когда это делали в последний раз.
    """

    def __init__(self, state: AppStatePort) -> None:
        self._state = state

    async def execute(self) -> None:
        await self._state.set(TOKEN_ROTATED_KEY, {"at": datetime.now(UTC).isoformat()})

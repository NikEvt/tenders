"""Реестр портов — то, что presentation видит вместо контейнера.

Протокол, а не класс: `bootstrap.ApiContainer` удовлетворяет ему структурно,
и presentation получает доступ к реализациям, ни разу их не импортировав.
Строка `_: Ports = container` в composition root ловит расхождение статически,
а не в рантайме на первом запросе.
"""

from __future__ import annotations

from typing import Protocol

from libs.shared.contracts.ports import ObjectStoragePort
from services.api.application.ports.catalog import (
    TenderCatalogPort,
    TenderFacetsPort,
    TenderSearchPort,
    TenderSimilarityPort,
)
from services.api.application.ports.digest import DigestReadPort
from services.api.application.ports.documents import DocumentReadPort, FragmentSearchPort
from services.api.application.ports.downstream import LlmServicePort, RecsysServicePort
from services.api.application.ports.filters import FilterReadPort
from services.api.application.ports.health import ReadinessPort
from services.api.application.ports.jobs import JobReadPort
from services.api.application.ports.monitoring import (
    AppStatePort,
    CrawlerRunReadPort,
    DocumentPipelinePort,
    EventTrailPort,
    QueueAdminPort,
    ServiceProbePort,
)
from services.api.application.ports.profile import ProfileHistoryPort
from services.api.application.ports.settings import RuntimeSettingsPort


class Ports(Protocol):
    catalog: TenderCatalogPort
    search: TenderSearchPort
    facets: TenderFacetsPort
    similarity: TenderSimilarityPort
    documents: DocumentReadPort
    fragments: FragmentSearchPort
    digest: DigestReadPort
    filters: FilterReadPort
    jobs: JobReadPort
    readiness: ReadinessPort
    probe: ServiceProbePort
    queues: QueueAdminPort
    crawler_runs: CrawlerRunReadPort
    pipeline: DocumentPipelinePort
    events: EventTrailPort
    app_state: AppStatePort
    profile_history: ProfileHistoryPort
    runtime_settings: RuntimeSettingsPort
    storage: ObjectStoragePort
    llm: LlmServicePort
    recsys: RecsysServicePort

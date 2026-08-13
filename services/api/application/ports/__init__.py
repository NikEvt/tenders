"""Порты API-шлюза.

Один порт — один агрегат. Раньше здесь жил `TenderReadPort` на семь методов про
каталог, документы, сводки и задания разом: любой потребитель тащил в тесты всё
сразу. Разрез по агрегатам оставляет каждому use case ровно те методы, которыми
он пользуется.
"""

from services.api.application.errors import DownstreamUnavailable
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
from services.api.application.ports.registry import Ports
from services.api.application.ports.settings import RuntimeSettingsPort

__all__ = [
    "AppStatePort",
    "CrawlerRunReadPort",
    "DigestReadPort",
    "DocumentPipelinePort",
    "DocumentReadPort",
    "DownstreamUnavailable",
    "EventTrailPort",
    "FilterReadPort",
    "FragmentSearchPort",
    "JobReadPort",
    "LlmServicePort",
    "Ports",
    "ProfileHistoryPort",
    "QueueAdminPort",
    "ReadinessPort",
    "RecsysServicePort",
    "RuntimeSettingsPort",
    "ServiceProbePort",
    "TenderCatalogPort",
    "TenderFacetsPort",
    "TenderSearchPort",
    "TenderSimilarityPort",
]

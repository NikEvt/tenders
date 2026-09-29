"""Зависимости хендлеров.

Хендлер получает порт, а не контейнер: подпись говорит, что именно ему нужно,
и тест подменяет ровно это. Импорты здесь — только fastapi и application:
presentation не должен знать ни одной реализации.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from libs.shared.contracts.ports import ObjectStoragePort
from services.api.application.errors import ServiceNotReady
from services.api.application.ports import (
    CrawlPublisherPort,
    DigestReadPort,
    DocumentReadPort,
    FilterReadPort,
    FragmentSearchPort,
    JobReadPort,
    LlmServicePort,
    Ports,
    ProfileHistoryPort,
    ReadinessPort,
    RecsysServicePort,
    TenderCatalogPort,
    TenderSearchPort,
)
from services.api.application.use_cases.browse_catalog import (
    CatalogFacetsUseCase,
    CatalogGroupsUseCase,
    SimilarTendersUseCase,
)
from services.api.application.use_cases.load_level import (
    ReadLoadLevelUseCase,
    SetLoadLevelUseCase,
)
from services.api.application.use_cases.monitoring import (
    CollectHealthUseCase,
    ConfirmTokenRotationUseCase,
    CrawlerRunsUseCase,
    DocumentPipelineUseCase,
    InspectQueuesUseCase,
    ReadSettingsUseCase,
    RetryDeadLetterUseCase,
    TenderEventsUseCase,
)
from services.api.application.use_cases.read_catalog import GetTenderUseCase
from services.api.application.use_cases.read_corpus import (
    CorpusOverviewUseCase,
    CorpusProcessingUseCase,
)
from services.api.application.use_cases.read_documents import (
    IssueDownloadLinkUseCase,
    ListDocumentChunksUseCase,
    ReadDocumentTextUseCase,
    SearchFragmentsUseCase,
)
from services.api.application.use_cases.read_filters import (
    GetFilterUseCase,
    ListFiltersUseCase,
)
from services.api.application.use_cases.read_profile import (
    ProfileHistoryUseCase,
    ProfileWinsUseCase,
)
from services.api.application.use_cases.read_research import (
    GetResearchMarketUseCase,
    GetResearchRunUseCase,
    ListResearchRunsUseCase,
    ListResearchTendersUseCase,
)
from services.api.application.use_cases.read_status import (
    GetDigestUseCase,
    GetJobUseCase,
    ListDigestDatesUseCase,
)


def get_ports(request: Request) -> Ports:
    """Контейнер живёт в состоянии приложения, а не в глобальной переменной модуля.

    Тесты подменяют его целиком одним `dependency_overrides[get_ports]`.
    """
    ports: Ports | None = getattr(request.app.state, "ports", None)
    if ports is None:
        raise ServiceNotReady("Сервис ещё не готов")
    return ports


PortsDep = Annotated[Ports, Depends(get_ports)]


def provide_catalog(ports: PortsDep) -> TenderCatalogPort:
    return ports.catalog


def provide_search(ports: PortsDep) -> TenderSearchPort:
    return ports.search


def provide_documents(ports: PortsDep) -> DocumentReadPort:
    return ports.documents


def provide_digest(ports: PortsDep) -> DigestReadPort:
    return ports.digest


def provide_jobs(ports: PortsDep) -> JobReadPort:
    return ports.jobs


def provide_readiness(ports: PortsDep) -> ReadinessPort:
    return ports.readiness


def provide_storage(ports: PortsDep) -> ObjectStoragePort:
    return ports.storage


def provide_llm(ports: PortsDep) -> LlmServicePort:
    return ports.llm


def provide_recsys(ports: PortsDep) -> RecsysServicePort:
    return ports.recsys


def provide_crawl(ports: PortsDep) -> CrawlPublisherPort:
    return ports.crawl


CatalogDep = Annotated[TenderCatalogPort, Depends(provide_catalog)]
SearchDep = Annotated[TenderSearchPort, Depends(provide_search)]
DocumentsDep = Annotated[DocumentReadPort, Depends(provide_documents)]
DigestDep = Annotated[DigestReadPort, Depends(provide_digest)]
JobsDep = Annotated[JobReadPort, Depends(provide_jobs)]
ReadinessDep = Annotated[ReadinessPort, Depends(provide_readiness)]
StorageDep = Annotated[ObjectStoragePort, Depends(provide_storage)]
LlmDep = Annotated[LlmServicePort, Depends(provide_llm)]
RecsysDep = Annotated[RecsysServicePort, Depends(provide_recsys)]
CrawlDep = Annotated[CrawlPublisherPort, Depends(provide_crawl)]


# ─── Сценарии ─────────────────────────────────────────────────────────────────
# Собираются на запрос: это присваивание полей, соединения при этом не трогаются.


def provide_get_tender(ports: PortsDep) -> GetTenderUseCase:
    return GetTenderUseCase(ports.catalog)


def provide_download_link(ports: PortsDep) -> IssueDownloadLinkUseCase:
    return IssueDownloadLinkUseCase(ports.documents)


def provide_document_text(ports: PortsDep) -> ReadDocumentTextUseCase:
    return ReadDocumentTextUseCase(ports.documents, ports.storage)


def provide_get_digest(ports: PortsDep) -> GetDigestUseCase:
    return GetDigestUseCase(ports.digest)


def provide_get_job(ports: PortsDep) -> GetJobUseCase:
    return GetJobUseCase(ports.jobs)


GetTender = Annotated[GetTenderUseCase, Depends(provide_get_tender)]
DownloadLink = Annotated[IssueDownloadLinkUseCase, Depends(provide_download_link)]
DocumentText = Annotated[ReadDocumentTextUseCase, Depends(provide_document_text)]
GetDigest = Annotated[GetDigestUseCase, Depends(provide_get_digest)]
GetJob = Annotated[GetJobUseCase, Depends(provide_get_job)]


def provide_catalog_facets(ports: PortsDep) -> CatalogFacetsUseCase:
    return CatalogFacetsUseCase(ports.facets, ports.search)


def provide_catalog_groups(ports: PortsDep) -> CatalogGroupsUseCase:
    return CatalogGroupsUseCase(ports.facets)


def provide_similar(ports: PortsDep) -> SimilarTendersUseCase:
    return SimilarTendersUseCase(ports.catalog, ports.similarity)


def provide_digest_dates(ports: PortsDep) -> ListDigestDatesUseCase:
    return ListDigestDatesUseCase(ports.digest)


CatalogFacets = Annotated[CatalogFacetsUseCase, Depends(provide_catalog_facets)]
CatalogGroups = Annotated[CatalogGroupsUseCase, Depends(provide_catalog_groups)]
Similar = Annotated[SimilarTendersUseCase, Depends(provide_similar)]
DigestDates = Annotated[ListDigestDatesUseCase, Depends(provide_digest_dates)]


def provide_filters(ports: PortsDep) -> FilterReadPort:
    return ports.filters


def provide_list_filters(ports: PortsDep) -> ListFiltersUseCase:
    return ListFiltersUseCase(ports.filters)


def provide_get_filter(ports: PortsDep) -> GetFilterUseCase:
    return GetFilterUseCase(ports.filters)


FiltersDep = Annotated[FilterReadPort, Depends(provide_filters)]
ListFilters = Annotated[ListFiltersUseCase, Depends(provide_list_filters)]
GetFilter = Annotated[GetFilterUseCase, Depends(provide_get_filter)]


def provide_document_chunks(ports: PortsDep) -> ListDocumentChunksUseCase:
    return ListDocumentChunksUseCase(ports.documents)


def provide_search_fragments(ports: PortsDep) -> SearchFragmentsUseCase:
    return SearchFragmentsUseCase(ports.fragments)


def provide_fragments(ports: PortsDep) -> FragmentSearchPort:
    return ports.fragments


DocumentChunks = Annotated[ListDocumentChunksUseCase, Depends(provide_document_chunks)]
SearchFragments = Annotated[SearchFragmentsUseCase, Depends(provide_search_fragments)]
FragmentsDep = Annotated[FragmentSearchPort, Depends(provide_fragments)]


# ─── Мониторинг и настройки ───────────────────────────────────────────────────


def provide_collect_health(ports: PortsDep) -> CollectHealthUseCase:
    return CollectHealthUseCase(ports.probe)


def provide_inspect_queues(ports: PortsDep) -> InspectQueuesUseCase:
    return InspectQueuesUseCase(ports.queues)


def provide_retry_dead_letter(ports: PortsDep) -> RetryDeadLetterUseCase:
    return RetryDeadLetterUseCase(ports.queues)


def provide_crawler_runs(ports: PortsDep) -> CrawlerRunsUseCase:
    return CrawlerRunsUseCase(ports.crawler_runs)


def provide_document_pipeline(ports: PortsDep) -> DocumentPipelineUseCase:
    return DocumentPipelineUseCase(ports.pipeline)


def provide_corpus_overview(ports: PortsDep) -> CorpusOverviewUseCase:
    return CorpusOverviewUseCase(ports.corpus)


def provide_corpus_processing(ports: PortsDep) -> CorpusProcessingUseCase:
    # Три порта, а не один запрос: воронку документов считает мониторинг, а
    # глубину очереди — брокер. Второго источника тех же чисел здесь нет.
    return CorpusProcessingUseCase(ports.corpus, ports.pipeline, ports.queues)


def provide_tender_events(ports: PortsDep) -> TenderEventsUseCase:
    return TenderEventsUseCase(ports.catalog, ports.events)


def provide_read_settings(ports: PortsDep) -> ReadSettingsUseCase:
    return ReadSettingsUseCase(ports.runtime_settings, ports.app_state)


def provide_confirm_rotation(ports: PortsDep) -> ConfirmTokenRotationUseCase:
    return ConfirmTokenRotationUseCase(ports.app_state)


def provide_read_load_level(ports: PortsDep) -> ReadLoadLevelUseCase:
    return ReadLoadLevelUseCase(ports.app_state)


def provide_set_load_level(ports: PortsDep) -> SetLoadLevelUseCase:
    return SetLoadLevelUseCase(ports.app_state)


def provide_list_research_runs(ports: PortsDep) -> ListResearchRunsUseCase:
    return ListResearchRunsUseCase(ports.research)


def provide_get_research_run(ports: PortsDep) -> GetResearchRunUseCase:
    return GetResearchRunUseCase(ports.research)


def provide_list_research_tenders(ports: PortsDep) -> ListResearchTendersUseCase:
    return ListResearchTendersUseCase(ports.research)


def provide_get_research_market(ports: PortsDep) -> GetResearchMarketUseCase:
    return GetResearchMarketUseCase(ports.research)


ListResearchRuns = Annotated[ListResearchRunsUseCase, Depends(provide_list_research_runs)]
GetResearchRun = Annotated[GetResearchRunUseCase, Depends(provide_get_research_run)]
ListResearchTenders = Annotated[
    ListResearchTendersUseCase, Depends(provide_list_research_tenders)
]
GetResearchMarket = Annotated[
    GetResearchMarketUseCase, Depends(provide_get_research_market)
]

ReadLoadLevel = Annotated[ReadLoadLevelUseCase, Depends(provide_read_load_level)]
SetLoadLevel = Annotated[SetLoadLevelUseCase, Depends(provide_set_load_level)]


CollectHealth = Annotated[CollectHealthUseCase, Depends(provide_collect_health)]
InspectQueues = Annotated[InspectQueuesUseCase, Depends(provide_inspect_queues)]
RetryDeadLetter = Annotated[RetryDeadLetterUseCase, Depends(provide_retry_dead_letter)]
CrawlerRuns = Annotated[CrawlerRunsUseCase, Depends(provide_crawler_runs)]
DocumentPipeline = Annotated[DocumentPipelineUseCase, Depends(provide_document_pipeline)]
CorpusOverview = Annotated[CorpusOverviewUseCase, Depends(provide_corpus_overview)]
CorpusProcessing = Annotated[CorpusProcessingUseCase, Depends(provide_corpus_processing)]
TenderEvents = Annotated[TenderEventsUseCase, Depends(provide_tender_events)]
ReadSettings = Annotated[ReadSettingsUseCase, Depends(provide_read_settings)]
ConfirmTokenRotation = Annotated[
    ConfirmTokenRotationUseCase, Depends(provide_confirm_rotation)
]


def provide_profile_history(ports: PortsDep) -> ProfileHistoryUseCase:
    return ProfileHistoryUseCase(ports.profile_history)


def provide_profile_wins(ports: PortsDep) -> ProfileWinsUseCase:
    return ProfileWinsUseCase(ports.profile_history)


def provide_profile_history_port(ports: PortsDep) -> ProfileHistoryPort:
    return ports.profile_history


ProfileHistory = Annotated[ProfileHistoryUseCase, Depends(provide_profile_history)]
ProfileWins = Annotated[ProfileWinsUseCase, Depends(provide_profile_wins)]
ProfileHistoryDep = Annotated[ProfileHistoryPort, Depends(provide_profile_history_port)]

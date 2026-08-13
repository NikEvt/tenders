"""Composition root API-шлюза.

Единственное место, где порты связываются с реализациями. Поля контейнера
объявлены портами, а не классами: остальной код видит контракт, а не конкретный
SQL или HTTP-клиент.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from libs.shared.clients.embedding_client import HttpEmbedder
from libs.shared.config import (
    DatabaseSettings,
    EisSettings,
    EmbeddingSettings,
    LlmSettings,
    MinioSettings,
    RabbitSettings,
    eis_settings,
    rabbit_settings,
)
from libs.shared.config import llm_settings as llm_config
from libs.shared.contracts.ports import ObjectStoragePort
from libs.shared.db.base import create_engine, create_session_factory
from services.api.application.ports import (
    AppStatePort,
    CrawlerRunReadPort,
    DigestReadPort,
    DocumentPipelinePort,
    DocumentReadPort,
    EventTrailPort,
    FilterReadPort,
    FragmentSearchPort,
    JobReadPort,
    LlmServicePort,
    Ports,
    ProfileHistoryPort,
    QueueAdminPort,
    ReadinessPort,
    RecsysServicePort,
    RuntimeSettingsPort,
    ServiceProbePort,
    TenderCatalogPort,
    TenderFacetsPort,
    TenderSearchPort,
    TenderSimilarityPort,
)
from services.api.infrastructure.clients.downstream import HttpLlmService, HttpRecsysService
from services.api.infrastructure.clients.rabbit_management import RabbitManagementClient
from services.api.infrastructure.clients.service_probe import HttpServiceProbe
from services.api.infrastructure.db.catalog_repository import SqlCatalogRepository
from services.api.infrastructure.db.digest_repository import SqlDigestRepository
from services.api.infrastructure.db.document_repository import SqlDocumentRepository
from services.api.infrastructure.db.facets_repository import SqlFacetsRepository
from services.api.infrastructure.db.filter_repository import SqlFilterReadRepository
from services.api.infrastructure.db.fragment_repository import SqlFragmentRepository
from services.api.infrastructure.db.job_repository import SqlJobRepository
from services.api.infrastructure.db.monitoring_repository import (
    SqlAppStateRepository,
    SqlCrawlerRunRepository,
    SqlDocumentPipelineRepository,
    SqlEventTrailRepository,
)
from services.api.infrastructure.db.profile_repository import SqlProfileHistoryRepository
from services.api.infrastructure.db.readiness import SqlReadinessProbe
from services.api.infrastructure.db.search_repository import SqlSearchRepository
from services.api.infrastructure.db.similarity_repository import SqlSimilarityRepository
from services.api.infrastructure.settings.env_settings import EnvRuntimeSettings
from services.api.infrastructure.storage.minio_storage import MinioReadStorage


@dataclass
class ApiContainer:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
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


@asynccontextmanager
async def build_container(
    db: DatabaseSettings,
    minio: MinioSettings,
    embedding: EmbeddingSettings,
    llm_url: str,
    recsys_url: str,
    rabbit: RabbitSettings | None = None,
    eis: EisSettings | None = None,
    llm_settings: LlmSettings | None = None,
) -> AsyncIterator[ApiContainer]:
    engine = create_engine(db.async_dsn)
    session_factory = create_session_factory(engine)

    embedder = HttpEmbedder(embedding.service_url, embedding.dim)
    llm = HttpLlmService(llm_url)
    recsys = HttpRecsysService(recsys_url)
    catalog = SqlCatalogRepository(session_factory)

    rabbit = rabbit or rabbit_settings()
    probe = HttpServiceProbe(
        {
            "api": "http://localhost:8000",
            "embedding-service": embedding.service_url,
            "llm-service": llm_url,
            "recsys-service": recsys_url,
        }
    )
    queues = RabbitManagementClient(
        f"http://{rabbit.host}:{os.getenv('RABBITMQ_MANAGEMENT_PORT', '15672')}",
        rabbit.user,
        rabbit.password.get_secret_value(),
    )

    container = ApiContainer(
        engine=engine,
        session_factory=session_factory,
        catalog=catalog,
        search=SqlSearchRepository(session_factory, catalog, embedder),
        facets=SqlFacetsRepository(session_factory),
        similarity=SqlSimilarityRepository(session_factory),
        documents=SqlDocumentRepository(session_factory),
        fragments=SqlFragmentRepository(session_factory, embedder),
        digest=SqlDigestRepository(session_factory),
        filters=SqlFilterReadRepository(session_factory),
        jobs=SqlJobRepository(session_factory),
        readiness=SqlReadinessProbe(session_factory),
        probe=probe,
        queues=queues,
        crawler_runs=SqlCrawlerRunRepository(session_factory),
        pipeline=SqlDocumentPipelineRepository(session_factory),
        events=SqlEventTrailRepository(session_factory),
        app_state=SqlAppStateRepository(session_factory),
        profile_history=SqlProfileHistoryRepository(session_factory),
        runtime_settings=EnvRuntimeSettings(
            llm_settings or llm_config(), eis or eis_settings(), embedding
        ),
        storage=MinioReadStorage(minio),
        llm=llm,
        recsys=recsys,
    )

    # Статическая сверка контейнера с реестром портов: если поле переименовали
    # или потеряли, mypy скажет об этом здесь, а не рантайм на первом запросе.
    _: Ports = container

    try:
        yield container
    finally:
        await probe.aclose()
        await queues.aclose()
        await embedder.aclose()
        await llm.aclose()
        await recsys.aclose()
        await engine.dispose()

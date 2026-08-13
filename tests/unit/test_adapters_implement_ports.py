"""Каждый адаптер реализует свой порт целиком.

Незакрытый абстрактный метод виден только при создании объекта — то есть при
старте сервиса, в проде. Так уже случилось: метод дописался в конец файла,
попал в соседний класс, и recsys-service падал в lifespan с
`Can't instantiate abstract class`. Этот тест ловит такое до сборки образа.
"""

from __future__ import annotations

import pytest

from services.api.infrastructure.clients.downstream import HttpLlmService, HttpRecsysService
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
from services.docs_worker.infrastructure.extraction.pool import ProcessPoolExtraction
from services.llm_service.infrastructure.db.repositories import (
    SqlDigestRepository as LlmDigestRepository,
)
from services.llm_service.infrastructure.db.repositories import (
    SqlFilterRepository,
    SqlJobTracker,
)
from services.recsys_service.infrastructure.db.repositories import (
    SqlProfileRepository,
    SqlRecommendationRepository,
)

# Конструкторы принимают фабрику сессий или URL — для проверки достаточно
# заглушки: объект создаётся, к базе не ходит.
ADAPTERS = [
    lambda: SqlCatalogRepository(None),
    lambda: SqlSearchRepository(None, SqlCatalogRepository(None)),
    lambda: SqlFacetsRepository(None),
    lambda: SqlSimilarityRepository(None),
    lambda: SqlDocumentRepository(None),
    lambda: SqlFragmentRepository(None),
    lambda: SqlDigestRepository(None),
    lambda: SqlJobRepository(None),
    lambda: SqlFilterReadRepository(None),
    lambda: SqlReadinessProbe(None),
    lambda: SqlCrawlerRunRepository(None),
    lambda: SqlDocumentPipelineRepository(None),
    lambda: SqlEventTrailRepository(None),
    lambda: SqlAppStateRepository(None),
    lambda: SqlProfileHistoryRepository(None),
    lambda: HttpLlmService("http://llm"),
    lambda: HttpRecsysService("http://recsys"),
    lambda: SqlFilterRepository(None),
    lambda: LlmDigestRepository(None),
    lambda: SqlJobTracker(None),
    lambda: SqlProfileRepository(None),
    lambda: SqlRecommendationRepository(None),
    # Пул процессов не поднимается при создании — только при первом разборе,
    # поэтому здесь он ничего не стоит.
    lambda: ProcessPoolExtraction(workers=1),
]


@pytest.mark.parametrize("build", ADAPTERS, ids=lambda b: b().__class__.__name__)
def test_adapter_is_instantiable(build) -> None:
    assert build() is not None

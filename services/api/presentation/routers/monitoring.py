"""Раздел «Мониторинг».

Браузеру нельзя ходить на шесть портов напрямую — это и CORS, и сеть, и
секреты брокера. Всё состояние собирает шлюз.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from services.api.presentation.deps import (
    CollectHealth,
    CrawlerRuns,
    DocumentPipeline,
    InspectQueues,
    RetryDeadLetter,
)
from services.api.presentation.schemas import (
    CrawlerRunsOut,
    DocumentPipelineOut,
    HealthOut,
    QueuesOut,
)

router = APIRouter(tags=["Мониторинг"], prefix="/monitoring")


@router.get("/health", response_model=HealthOut)
async def services_health(use_case: CollectHealth) -> HealthOut:
    """Состояние сервисов одним ответом.

    Сервис, который не ответил, помечается `down` — это факт о нём, а не
    ошибка страницы: иначе упавший прятал бы состояние остальных именно тогда,
    когда на экран и смотрят.
    """
    return HealthOut.of(await use_case.execute())


@router.get("/queues", response_model=QueuesOut)
async def queues(use_case: InspectQueues) -> QueuesOut:
    """Глубины очередей, лестница повторов и недоставленные сообщения."""
    return QueuesOut.of(await use_case.execute())


@router.post("/queues/dead-letters/{message_id}/retry", status_code=202)
async def retry_dead_letter(message_id: str, use_case: RetryDeadLetter) -> Response:
    await use_case.execute(message_id)
    return Response(status_code=202)


@router.get("/crawler/runs", response_model=CrawlerRunsOut)
async def crawler_runs(
    use_case: CrawlerRuns, limit: int = Query(default=60, ge=1, le=500)
) -> CrawlerRunsOut:
    return CrawlerRunsOut.of(await use_case.execute(limit))


@router.get("/documents", response_model=DocumentPipelineOut)
async def document_pipeline(use_case: DocumentPipeline) -> DocumentPipelineOut:
    """Воронка обработки документов и отказы по этапам."""
    return DocumentPipelineOut.of(await use_case.execute())

"""HTTP-интерфейс и AMQP-потребитель сервиса эмбеддингов."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from libs.shared.config import database_settings, embedding_settings, rabbit_settings
from libs.shared.contracts.events import DocumentExtracted, EmbeddingRequested
from libs.shared.logging import configure_logging, get_logger
from libs.shared.messaging.consumer import EventConsumer
from libs.shared.messaging.topology import QueueSpec
from services.embedding_service.bootstrap import EmbeddingContainer, build_container

log = get_logger(__name__)

DEFAULT_PREFETCH = 2


def _prefetch() -> int:
    raw = os.getenv("EMBEDDING_PREFETCH", "")
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_PREFETCH


QUEUE = QueueSpec(
    name="embedding-service.enrichment",
    routing_keys=("document.extracted", "embedding.requested"),
    # Один эмбеддинг — это батч чанков документа и секунды CPU. Больше двух
    # в работе разом под квотой в одно ядро только удлиняет каждый.
    prefetch=_prefetch(),
)

MAX_TEXTS_PER_REQUEST = 64


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS_PER_REQUEST)
    #: Асимметричная модель кодирует запрос и документ по-разному.
    is_query: bool = False


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    dim: int


_container: EmbeddingContainer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _container
    configure_logging("embedding-service")

    async with build_container(
        database_settings(), rabbit_settings(), embedding_settings()
    ) as container:
        _container = container

        consumer = EventConsumer(container.connection, QUEUE, idempotency=container.idempotency)
        consumer.on(DocumentExtracted, container.handler.on_document_extracted)
        consumer.on(EmbeddingRequested, container.handler.on_embedding_requested)
        await consumer.run()

        log.info(
            "embedding_service.ready",
            queue=QUEUE.name,
            model=container.embedder.model_name,
            device=container.embedder.device,
        )
        try:
            yield
        finally:
            _container = None


app = FastAPI(title="zakupki embedding-service", lifespan=lifespan)


def container() -> EmbeddingContainer:
    if _container is None:
        raise HTTPException(status_code=503, detail="Сервис ещё не готов")
    return _container


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest) -> EmbedResponse:
    current = container()
    vectors = await current.embedder.embed(request.texts, is_query=request.is_query)
    return EmbedResponse(
        vectors=vectors, model=current.embedder.model_name, dim=current.embedder.dim
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


#: Насколько долго верить однажды подтверждённой готовности, секунд.
#:
#: Проба готовности прогоняет через модель короткий текст — иначе «готов»
#: означало бы лишь «объект создан». Но делать это на каждый опрос нельзя:
#: инференс встаёт в очередь за настоящей работой, и время ответа зависит от
#: загрузки, а не от исправности.
#:
#: Замер: на MPS при разборе очереди `/health/ready` отвечал 0.66–2.75 с при
#: потолке пробы шлюза в 1.5 с — то есть сервис объявлялся то живым, то мёртвым
#: по жребию. На CPU в контейнере то же самое упиралось в 30 с и давало
#: сплошные таймауты. Проверять исправность вычислением, конкурирующим с
#: полезной нагрузкой, — значит мерить занятость и называть её поломкой.
READY_CACHE_SECONDS = 60.0

_verified_at: float | None = None


@app.get("/health/ready")
async def ready() -> dict[str, object]:
    """Готовность: модель загружена и выдаёт векторы.

    Прогон делается один раз и повторяется не чаще, чем раз в минуту. В
    промежутке отдаётся тот же факт — он не перестаёт быть верным оттого, что
    сервис занят.
    """
    global _verified_at
    current = container()

    now = time.monotonic()
    if _verified_at is None or now - _verified_at > READY_CACHE_SECONDS:
        # Первая проверка после старта самая дорогая: модель прогревается.
        vectors = await asyncio.wait_for(current.embedder.embed(["ping"]), timeout=120)
        if not vectors or len(vectors[0]) != current.embedder.dim:
            raise HTTPException(status_code=503, detail="Модель вернула вектор не той длины")
        _verified_at = time.monotonic()

    return {
        "status": "ready",
        "model": current.embedder.model_name,
        "dim": current.embedder.dim,
        "device": current.embedder.device,
        # Видно, насколько свеж факт: «готов» из кэша минутной давности — это
        # не то же самое, что проверка прямо сейчас.
        "verified_ago_s": round(time.monotonic() - _verified_at, 1),
    }

"""HTTP-интерфейс и AMQP-потребитель сервиса эмбеддингов."""

from __future__ import annotations

import asyncio
import os
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


@app.get("/health/ready")
async def ready() -> dict[str, object]:
    current = container()
    # Прогон короткого текста подтверждает, что модель действительно загружена,
    # а не просто объявлена.
    await asyncio.wait_for(current.embedder.embed(["ping"]), timeout=30)
    return {
        "status": "ready",
        "model": current.embedder.model_name,
        "dim": current.embedder.dim,
        "device": current.embedder.device,
    }

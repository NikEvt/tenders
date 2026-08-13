"""Построение эмбеддингов тендеров и чанков документов."""

from __future__ import annotations

import hashlib

from libs.shared.contracts.events import DocumentExtracted, EmbeddingRequested
from libs.shared.contracts.ports import EmbedderPort
from libs.shared.logging import get_logger
from services.embedding_service.application.ports import EmbeddingRepositoryPort

log = get_logger(__name__)

# Батч подбирается под память GPU/CPU; 32 чанка по ~2400 символов проходят
# на 8 ГБ без свопа.
DEFAULT_BATCH_SIZE = 32

# Потолок на разовую догонку чанков тендера: комплект документации крупной
# стройки — это тысячи чанков, их незачем считать в одном сообщении.
MAX_CHUNKS_PER_MESSAGE = 500


class EmbedTenderCardUseCase:
    """Строит «карточный» вектор тендера для семантического поиска и рекомендаций."""

    def __init__(
        self,
        repository: EmbeddingRepositoryPort,
        embedder: EmbedderPort,
        model_name: str,
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._model_name = model_name

    async def execute(self, tender_id: int) -> bool:
        card = await self._repository.load_tender_card(tender_id)
        if card is None:
            log.warning("embedding.tender_not_found", tender_id=tender_id)
            return False

        text = card.render()
        if not text.strip():
            log.info("embedding.tender_text_empty", tender_id=tender_id)
            return False

        source_hash = hashlib.sha256(text.encode()).hexdigest()
        # Текст не изменился — пересчитывать вектор незачем. Краулер перезаписывает
        # извещение при каждой выгрузке, так что без этой проверки мы бы гоняли
        # модель на одних и тех же данных ежечасно.
        if await self._repository.tender_embedding_hash(tender_id) == source_hash:
            return False

        vectors = await self._embedder.embed([text])
        await self._repository.save_tender_embedding(
            tender_id, vectors[0], self._model_name, source_hash
        )
        log.info("embedding.tender_saved", tender_id=tender_id, chars=len(text))
        return True


class EmbedChunksUseCase:
    """Строит векторы для чанков документов."""

    def __init__(
        self,
        repository: EmbeddingRepositoryPort,
        embedder: EmbedderPort,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._batch_size = batch_size

    async def execute(self, chunk_ids: list[int]) -> int:
        if not chunk_ids:
            return 0

        pending = await self._repository.load_chunks(chunk_ids[:MAX_CHUNKS_PER_MESSAGE])
        if not pending:
            return 0

        saved = 0
        for start in range(0, len(pending), self._batch_size):
            batch = pending[start : start + self._batch_size]
            vectors = await self._embedder.embed([text for _, text in batch])
            await self._repository.save_chunk_embeddings(
                [(chunk_id, vector) for (chunk_id, _), vector in zip(batch, vectors, strict=True)]
            )
            saved += len(batch)

        log.info("embedding.chunks_saved", count=saved)
        return saved


class HandleEmbeddingEventsUseCase:
    """Единая точка входа для событий, требующих эмбеддингов."""

    def __init__(
        self,
        repository: EmbeddingRepositoryPort,
        tender_use_case: EmbedTenderCardUseCase,
        chunks_use_case: EmbedChunksUseCase,
    ) -> None:
        self._repository = repository
        self._tender = tender_use_case
        self._chunks = chunks_use_case

    async def on_document_extracted(self, event: DocumentExtracted) -> None:
        await self._chunks.execute(list(event.chunk_ids))
        # Карточка тендера включает выдержку из документов, поэтому после появления
        # текста её вектор пересчитывается.
        await self._tender.execute(event.tender_id)

    async def on_embedding_requested(self, event: EmbeddingRequested) -> None:
        if event.target == "tender":
            await self._tender.execute(event.tender_id)
            return

        chunk_ids = list(event.chunk_ids) or await self._repository.pending_chunk_ids(
            event.tender_id, MAX_CHUNKS_PER_MESSAGE
        )
        await self._chunks.execute(chunk_ids)

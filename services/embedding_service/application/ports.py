"""Порты сервиса эмбеддингов."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from services.embedding_service.domain.models import TenderCardText


class EmbeddingRepositoryPort(ABC):
    """Чтение текстов и запись векторов."""

    @abstractmethod
    async def load_tender_card(self, tender_id: int) -> TenderCardText | None: ...

    @abstractmethod
    async def load_chunks(self, chunk_ids: Sequence[int]) -> list[tuple[int, str]]:
        """Возвращает пары (chunk_id, текст) только для чанков без эмбеддинга."""

    @abstractmethod
    async def save_tender_embedding(
        self, tender_id: int, vector: Sequence[float], model: str, source_hash: str
    ) -> None: ...

    @abstractmethod
    async def save_chunk_embeddings(
        self, vectors: Sequence[tuple[int, Sequence[float]]]
    ) -> None: ...

    @abstractmethod
    async def tender_embedding_hash(self, tender_id: int) -> str | None:
        """Хеш текста, по которому построен текущий вектор тендера."""

    @abstractmethod
    async def pending_chunk_ids(self, tender_id: int, limit: int) -> list[int]:
        """Чанки тендера, у которых эмбеддинга ещё нет."""

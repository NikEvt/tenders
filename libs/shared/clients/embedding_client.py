"""HTTP-клиент к embedding-service.

Реализует тот же `EmbedderPort`, что и локальная модель, поэтому api, llm-service
и recsys вызывают эмбеддинги одинаково и не тянут torch в свои образы (DIP + ISP).
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from libs.shared.contracts.ports import EmbedderPort
from libs.shared.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 120.0
# Сервис отдаёт не более 64 текстов за запрос — соблюдаем и на стороне клиента.
MAX_BATCH = 64


class EmbeddingServiceUnavailable(RuntimeError):
    """Сервис эмбеддингов недоступен; вызывающий может деградировать до FTS."""


class HttpEmbedder(EmbedderPort):
    def __init__(
        self,
        base_url: str,
        dim: int,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dim = dim
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def dim(self) -> int:
        return self._dim

    async def aclose(self) -> None:
        await self._client.aclose()

    async def embed(self, texts: Sequence[str], is_query: bool = False) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            batch = list(texts[start : start + MAX_BATCH])
            vectors.extend(await self._embed_batch(batch, is_query))
        return vectors

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )
    async def _post(self, payload: dict) -> httpx.Response:
        response = await self._client.post(f"{self._base_url}/embed", json=payload)
        response.raise_for_status()
        return response

    async def _embed_batch(self, texts: list[str], is_query: bool) -> list[list[float]]:
        try:
            response = await self._post({"texts": texts, "is_query": is_query})
        except httpx.HTTPError as exc:
            raise EmbeddingServiceUnavailable(str(exc)) from exc

        data = response.json()
        vectors = data["vectors"]
        if vectors and len(vectors[0]) != self._dim:
            # Молча записать вектор не той размерности нельзя: pgvector примет
            # его только в столбец своей размерности, и ошибка всплывёт далеко.
            raise EmbeddingServiceUnavailable(
                f"Сервис вернул {len(vectors[0])}-мерные векторы вместо {self._dim}"
            )
        return vectors

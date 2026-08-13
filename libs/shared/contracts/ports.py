"""Порты внешних систем, общие для нескольких сервисов.

Порты, специфичные для одного сервиса, живут в его собственном `application/ports.py`.
Здесь — только то, что реально переиспользуется, чтобы `libs.shared` не превратился
в свалку доменной логики.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import BinaryIO

from libs.shared.contracts.events import Event


class EventPublisher(ABC):
    """Публикация доменных событий. Реализации: RabbitMQ, outbox, in-memory (тесты)."""

    @abstractmethod
    async def publish(self, event: Event) -> None: ...

    @abstractmethod
    async def publish_many(self, events: Sequence[Event]) -> None: ...


class ObjectStoragePort(ABC):
    """Файловое хранилище (MinIO/S3)."""

    @abstractmethod
    def put(
        self,
        key: str,
        data: BinaryIO,
        size: int,
        content_type: str | None = None,
    ) -> None: ...

    @abstractmethod
    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str: ...


class EmbedderPort(ABC):
    """Построение эмбеддингов. Вызывающий код не знает, локальная это модель или HTTP."""

    @abstractmethod
    async def embed(self, texts: Sequence[str], is_query: bool = False) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dim(self) -> int: ...

"""Модели раздела «Мониторинг».

Браузеру нельзя ходить на шесть портов напрямую — это и CORS, и сеть, и
секреты. Поэтому шлюз собирает состояние сам и отдаёт одним ответом.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

ServiceStatus = Literal["ok", "degraded", "down"]

# Порядок соответствует конвейеру: от выгрузки до выдачи.
SERVICE_NAMES = (
    "api",
    "crawler",
    "docs-worker",
    "embedding-service",
    "llm-service",
    "recsys-service",
)


@dataclass(slots=True)
class ServiceHealth:
    name: str
    status: ServiceStatus
    port: int | None = None
    p95_ms: float | None = None
    # Что именно сервис рассказал о себе: модель, устройство, глубина очереди.
    # Ключи разные у разных сервисов — это не таблица, а карточка.
    facts: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class QueueStat:
    name: str
    depth: int
    consumers: int
    dead_letters: int


@dataclass(slots=True)
class RetryStage:
    """Ступень лестницы повторов: 5с → 30с → 2м → 10м → 1ч."""

    stage: str
    depth: int


@dataclass(slots=True)
class DeadLetter:
    message_id: str
    event: str
    error: str | None
    retry_stage: str | None
    failed_at: datetime | None


@dataclass(slots=True)
class QueuesSnapshot:
    queues: list[QueueStat] = field(default_factory=list)
    retry_ladder: list[RetryStage] = field(default_factory=list)
    dead_letters: list[DeadLetter] = field(default_factory=list)


@dataclass(slots=True)
class CrawlerRunView:
    run_id: int
    target_date: str | None
    status: str
    fetched: int
    saved: int
    error_code: int | None
    error_message: str | None
    raw: dict | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(slots=True)
class PipelineFunnel:
    """Сколько документов дошло до каждого этапа обработки."""

    downloaded: int
    extracted: int
    ocr: int
    chunked: int
    embedded: int
    failures: list[tuple[str, int]] = field(default_factory=list)
    #: Причины отказа политики допуска: том архива, бюджет закупки, размер.
    #: Объясняют разрыв между «скачано» и «извлечён текст».
    skip_reasons: list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class TenderEvent:
    """Строка событийного следа закупки."""

    message_id: str
    event: str
    occurred_at: datetime
    status: Literal["pending", "published", "consumed", "retry", "dead"]
    attempt: int
    retry_stage: str | None
    error: str | None

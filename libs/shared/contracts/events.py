"""Контракты событий — единственное, что сервисы знают друг о друге.

Любое изменение здесь ломает совместимость между сервисами, поэтому поля только
добавляются (никогда не переименовываются и не удаляются без версии в routing key).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

EXCHANGE = "zakupki.events"
DLX = "zakupki.dlx"
RETRY_EXCHANGE = "zakupki.retry"


class Event(BaseModel):
    """Базовый конверт. `routing_key` — единственный источник правды о маршруте."""

    routing_key: ClassVar[str] = "event.unknown"

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None


class TenderIngested(Event):
    """Тендер сохранён/обновлён краулером. Точка входа для всего обогащения."""

    routing_key: ClassVar[str] = "tender.ingested"

    tender_id: int
    reg_num: str
    is_new: bool
    attachment_count: int = 0


class CrawlRequested(Event):
    """Заявка на выгрузку периода из ЕИС.

    Штатный краулер тянет вчерашний день по расписанию; исследованию нужен
    произвольный период за прошлое. Это единственный способ такой период
    заказать: сервисы связаны событиями, а не вызовами.

    Уже выгруженные дни повторно не тянутся — краулер сверяется с журналом
    запусков, поэтому заявку можно слать сколько угодно раз.
    """

    routing_key: ClassVar[str] = "crawl.requested"

    regions: list[str]
    date_from: date
    date_to: date
    #: Пусто — значит типы по умолчанию из настроек краулера.
    document_types: list[str] = Field(default_factory=list)
    #: Кто заказал. Нужен, чтобы связать выгрузку с исследованием.
    research_id: int | None = None


class DocumentStored(Event):
    """Файл вложения скачан и положен в MinIO."""

    routing_key: ClassVar[str] = "document.stored"

    document_id: int
    tender_id: int
    minio_key: str
    content_type: str | None = None
    size_bytes: int | None = None


class DocumentExtracted(Event):
    """Из документа извлечён текст и нарезаны чанки."""

    routing_key: ClassVar[str] = "document.extracted"

    document_id: int
    tender_id: int
    chunk_ids: list[int]
    ocr_used: bool = False
    char_count: int = 0


class TenderEnriched(Event):
    """Тендер полностью обогащён: документы обработаны, эмбеддинги готовы."""

    routing_key: ClassVar[str] = "tender.enriched"

    tender_id: int
    reg_num: str
    documents_status: Literal["done", "partial", "failed"]


class EmbeddingRequested(Event):
    """Запрос на построение эмбеддингов. `target` определяет, куда писать результат."""

    routing_key: ClassVar[str] = "embedding.requested"

    target: Literal["tender", "chunks"]
    tender_id: int
    chunk_ids: list[int] = Field(default_factory=list)


class ResearchRequested(Event):
    """Запуск отбора по сохранённому критерию.

    Пришло на смену `filter.evaluate.requested`. Прежний движок отбирал 200
    кандидатов гибридным поиском и отдавал модели фрагменты документации;
    новый ищет упоминания по всему корпусу, решает уверенные случаи правилами
    и зовёт модель только к спорным.
    """

    routing_key: ClassVar[str] = "research.requested"

    filter_id: int
    job_id: uuid.UUID
    regions: list[str] = Field(default_factory=list)
    since: date | None = None
    until: date | None = None
    # Пробный прогон конструктора: считает воронку и не отмечает критерий как
    # отработавший.
    dry_run: bool = False


class DigestRequested(Event):
    """Запрос на генерацию ИИ-сводки за день."""

    routing_key: ClassVar[str] = "digest.requested"

    digest_date: date
    force: bool = False


class FeedbackRecorded(Event):
    """Пользователь оценил тендер — профиль рекомендаций надо обновить."""

    routing_key: ClassVar[str] = "feedback.recorded"

    tender_id: int
    signal: Literal["like", "dislike", "hide", "shortlist", "view", "won"]


ALL_EVENTS: tuple[type[Event], ...] = (
    CrawlRequested,
    TenderIngested,
    DocumentStored,
    DocumentExtracted,
    TenderEnriched,
    EmbeddingRequested,
    ResearchRequested,
    DigestRequested,
    FeedbackRecorded,
)

EVENT_BY_ROUTING_KEY: dict[str, type[Event]] = {e.routing_key: e for e in ALL_EVENTS}

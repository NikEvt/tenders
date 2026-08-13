"""Доменные модели чтения каталога закупок."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20

#: Состояния обработки вложений закупки — ровно те, что выставляет docs-worker.
#: Объявлены типом, а не строкой: неизвестное значение обязано быть ошибкой
#: запроса, а не молчаливо пустой выдачей.
DocumentsStatus = Literal["pending", "processing", "done", "partial", "failed"]


@dataclass(slots=True)
class TenderFilter:
    """Структурные условия выборки — то, что раньше собиралось SQL-ом в дашборде."""

    query: str | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    okpd2_prefix: str | None = None
    regions: list[str] = field(default_factory=list)
    customer_inn: str | None = None
    published_since: date | None = None
    published_until: date | None = None
    only_active: bool = False
    deadline_changed: bool = False
    documents_status: DocumentsStatus | None = None
    # Есть ли у закупки распознанный текст. Отдельно от documents_status:
    # тот агрегирует обработку вложений и расходится с фактом наличия
    # текста в обе стороны.
    has_text: bool | None = None
    filter_id: int | None = None
    matched_only: bool = True

    def normalized_page_size(self, page_size: int) -> int:
        return max(1, min(page_size, MAX_PAGE_SIZE))


@dataclass(slots=True)
class TenderSummary:
    tender_id: int
    reg_num: str
    name: str | None
    description: str | None
    price: Decimal | None
    currency: str | None
    customer_name: str | None
    customer_inn: str | None
    okpd2_code: str | None
    okpd2_name: str | None
    region_code: str | None
    publish_date: datetime | None
    start_date: datetime | None
    end_date: datetime | None
    prev_end_date: datetime | None
    status: str | None
    documents_status: str
    document_count: int = 0
    relevance: float | None = None

    @property
    def deadline_changed(self) -> bool:
        return self.prev_end_date is not None and self.prev_end_date != self.end_date


@dataclass(slots=True)
class TenderDocumentInfo:
    document_id: int
    file_name: str | None
    doc_kind_name: str | None
    file_size: int | None
    extraction_status: str
    page_count: int | None
    ocr_used: bool
    char_count: int | None
    has_text: bool


@dataclass(slots=True)
class TenderDetail:
    summary: TenderSummary
    documents: list[TenderDocumentInfo] = field(default_factory=list)
    verdicts: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class DownloadLink:
    """Временная ссылка на файл в объектном хранилище."""

    url: str
    file_name: str | None
    expires_in: int


@dataclass(slots=True)
class DocumentContent:
    document_id: int
    content: str
    char_count: int


@dataclass(slots=True)
class Page:
    items: list[TenderSummary]
    total: int
    page: int | None
    page_size: int
    # Непрозрачная метка последней строки. None означает «дальше ничего нет»,
    # и клиент по этому признаку останавливает догрузку.
    next_cursor: str | None = None

    @property
    def total_pages(self) -> int:
        return max(1, -(-self.total // self.page_size))

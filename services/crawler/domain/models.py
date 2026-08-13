"""Доменные модели краулера. Никаких зависимостей на SQLAlchemy, requests и XML."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class TenderStatus(StrEnum):
    """Вычисляемый статус.

    `purchaseStatus` в `epNotificationEF2020` не приходит (все 1124 записи в старой
    базе имели NULL), поэтому статус выводится из дат, а не читается из XML.
    """

    PLANNED = "planned"  # публикация ещё впереди
    COLLECTING = "collecting"  # идёт приём заявок
    BIDDING = "bidding"  # приём закрыт, торги/подведение итогов
    FINISHED = "finished"  # итоги подведены
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Attachment:
    """Вложение извещения. Именно здесь лежит основная документация закупки."""

    attachment_id: str
    file_name: str | None
    url: str | None
    file_size: int | None = None
    doc_description: str | None = None
    doc_kind_code: str | None = None
    doc_kind_name: str | None = None

    @property
    def is_downloadable(self) -> bool:
        return bool(self.url and self.attachment_id)


@dataclass(slots=True)
class Tender:
    """Извещение о закупке в терминах предметной области."""

    reg_num: str
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    currency: str = "RUB"

    publish_date: datetime | None = None
    direct_date: datetime | None = None
    planned_publish_date: date | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    bidding_date: date | None = None
    summarizing_date: date | None = None
    contract_end_date: date | None = None

    customer_name: str | None = None
    customer_inn: str | None = None
    customer_region: str | None = None
    region_code: str | None = None

    okpd2_codes: list[str] = field(default_factory=list)
    okpd2_names: list[str] = field(default_factory=list)

    law_type: str = "44-FZ"
    raw_xml: str | None = None
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def okpd2_code(self) -> str | None:
        """Основной код — для обратной совместимости с существующими фильтрами."""
        return self.okpd2_codes[0] if self.okpd2_codes else None

    @property
    def okpd2_name(self) -> str | None:
        return self.okpd2_names[0] if self.okpd2_names else None

    def status_at(self, moment: datetime | None = None) -> TenderStatus:
        """Статус на заданный момент. Information Expert: даты знает сам тендер."""
        now = moment or datetime.now(UTC)

        if self.publish_date and self.publish_date > now:
            return TenderStatus.PLANNED
        if self.end_date and now < self.end_date:
            return TenderStatus.COLLECTING
        if self.summarizing_date and now.date() > self.summarizing_date:
            return TenderStatus.FINISHED
        if self.end_date and now >= self.end_date:
            return TenderStatus.BIDDING
        return TenderStatus.UNKNOWN

    @property
    def is_valid(self) -> bool:
        """Минимально пригодная для сохранения запись."""
        return bool(self.reg_num)

    @property
    def downloadable_attachments(self) -> list[Attachment]:
        return [a for a in self.attachments if a.is_downloadable]


@dataclass(slots=True)
class CrawlRequest:
    """Что именно выгружаем: регион × тип документа × дата."""

    region: str
    document_type: str
    target_date: date
    subsystem: str = "PRIZ"


@dataclass(slots=True)
class CrawlResult:
    """Итог одной выгрузки — то, что попадает в `crawler_runs`."""

    request: CrawlRequest
    fetched: int = 0
    saved: int = 0
    new: int = 0
    errors: int = 0
    error_message: str | None = None

    @property
    def status(self) -> str:
        if self.error_message:
            return "failed"
        return "partial" if self.errors else "success"

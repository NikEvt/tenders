"""Порты краулера. Слой application знает только эти интерфейсы."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from services.crawler.domain.models import CrawlRequest, CrawlResult, Tender


@dataclass(frozen=True, slots=True)
class SavedTender:
    """Результат сохранения — нужен, чтобы понять, новый тендер или обновлённый."""

    id: int
    reg_num: str
    is_new: bool
    attachment_count: int


class TenderSourcePort(ABC):
    """Источник извещений. Сегодня — SOAP ЕИС по 44-ФЗ, завтра может быть 223-ФЗ."""

    @abstractmethod
    def fetch(self, request: CrawlRequest) -> Sequence[Tender]: ...


class TenderRepositoryPort(ABC):
    """Персистентность тендеров."""

    @abstractmethod
    async def upsert_many(self, tenders: Sequence[Tender]) -> list[SavedTender]: ...


class CrawlRunLogPort(ABC):
    """Журнал запусков — наблюдаемость выгрузки и она же карта покрытия."""

    @abstractmethod
    async def start(self, request: CrawlRequest) -> int: ...

    @abstractmethod
    async def finish(self, run_id: int, result: CrawlResult) -> None: ...

    @abstractmethod
    async def completed(self, since: date, until: date) -> set[tuple[str, str, date]]:
        """Успешно выгруженные сочетания регион × тип документа × день.

        Отдельной таблицы покрытия нет и не нужно: журнал запусков уже знает,
        что и когда получилось. Дозаказ периода сверяется с ним и тянет только
        недостающее — поэтому заявку можно повторять, а прерванный прогон
        продолжается с места остановки.
        """


class CrawlRunnerPort(ABC):
    """Выполняет одну выгрузку регион × тип × день целиком.

    Существует ради параллельности. Сессия SQLAlchemy не переживает
    одновременного использования из нескольких задач, поэтому каждая выгрузка
    обязана открыть свою — а значит, кто-то должен уметь её открыть. Сценарий
    периода этого делать не может: он не знает ни про сессии, ни про SQL.

    Побочная выгода: сбой на одном регионе не откатывает сохранённое по
    соседнему — у каждого своя транзакция.
    """

    @abstractmethod
    async def run(self, request: CrawlRequest) -> CrawlResult: ...

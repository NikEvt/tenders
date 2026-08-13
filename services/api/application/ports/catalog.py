"""Порты чтения каталога закупок."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from services.api.domain.catalog import Facets, GroupBucket, RestrictiveHint, SimilarTender
from services.api.domain.models import Page, TenderDetail, TenderFilter
from services.api.domain.pagination import PageRequest


class TenderCatalogPort(ABC):
    """Список и карточка закупки — структурный отбор без модели."""

    @abstractmethod
    async def list(self, filters: TenderFilter, page: PageRequest) -> Page: ...

    @abstractmethod
    async def get(self, reg_num: str) -> TenderDetail | None: ...

    @abstractmethod
    async def tender_id(self, reg_num: str) -> int | None:
        """Внутренний идентификатор по реестровому номеру."""


class TenderSearchPort(ABC):
    """Гибридный поиск.

    Отделён от каталога намеренно: ему нужен эмбеддер, а списку — нет, и
    падение сервиса эмбеддингов не должно попадать в зависимости выдачи.
    """

    @abstractmethod
    async def search(self, query: str, filters: TenderFilter, page: PageRequest) -> Page: ...

    @abstractmethod
    async def matching_ids(self, query: str, filters: TenderFilter) -> list[int]:
        """Идентификаторы всей выдачи запроса, без постраничности.

        Нужны фасетам: считать их предикатами нельзя — векторная часть поиска
        предикатом не выражается, и счётчики разошлись бы со списком."""


class TenderFacetsPort(ABC):
    """Счётчики по всей выдаче — то, чего нельзя получить из страницы."""

    @abstractmethod
    async def facets(
        self, filters: TenderFilter, restrict_to: Sequence[int] | None = None
    ) -> Facets:
        """`restrict_to` сужает подсчёт до заданных закупок.

        Так фасеты описывают ровно ту выдачу, которую видит пользователь, когда
        она получена поиском, а не предикатами."""

    @abstractmethod
    async def restrictive(
        self, filters: TenderFilter, restrict_to: Sequence[int] | None = None
    ) -> RestrictiveHint | None:
        """Какое одно условие отсекает больше всего. None — если условий нет."""

    @abstractmethod
    async def groups(self, filters: TenderFilter, field: str) -> list[GroupBucket]:
        """Шапки групп по категорийному полю: счётчик и сумма НМЦК на группу."""


class TenderSimilarityPort(ABC):
    @abstractmethod
    async def similar(self, tender_id: int, limit: int) -> list[SimilarTender]: ...

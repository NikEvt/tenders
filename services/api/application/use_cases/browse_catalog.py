"""Сценарии каталога: фасеты и похожие закупки."""

from __future__ import annotations

from services.api.application.errors import InvalidRequest, NotFound
from services.api.application.ports.catalog import (
    TenderCatalogPort,
    TenderFacetsPort,
    TenderSearchPort,
    TenderSimilarityPort,
)
from services.api.domain.catalog import Facets, GroupBucket, RestrictiveHint, SimilarTender
from services.api.domain.models import TenderFilter


class CatalogFacetsUseCase:
    """Счётчики по той же выдаче, которую видит пользователь.

    Композиция живёт здесь, а не в репозитории: при текстовом запросе список
    строит поиск, и фасеты обязаны считаться по его результату. Предикатами это
    множество не воспроизвести — векторная часть поиска предикатом не
    выражается, и счётчики расходились со списком (запрос «мебель» давал 302
    в списке и 0 в фасетах). Репозиторий фасетов при этом остаётся простым и
    про поиск не знает.
    """

    def __init__(self, facets: TenderFacetsPort, search: TenderSearchPort) -> None:
        self._facets = facets
        self._search = search

    async def execute(
        self, filters: TenderFilter, explain_empty: bool = False
    ) -> tuple[Facets, RestrictiveHint | None]:
        # Без текстового запроса предикаты и есть выдача — лишний проход не нужен.
        restrict_to = (
            await self._search.matching_ids(filters.query, filters) if filters.query else None
        )
        counts = await self._facets.facets(filters, restrict_to)
        # Подсказка «какое условие лишнее» стоит нескольких COUNT-ов, поэтому
        # считается только когда клиент прямо просит — то есть на пустой выдаче.
        hint = (
            await self._facets.restrictive(filters, restrict_to) if explain_empty else None
        )
        return counts, hint


class CatalogGroupsUseCase:
    """Оглавление сгруппированного списка.

    Отдельный сценарий, а не поле в фасетах: фасеты запрашиваются на каждой
    смене фильтра, а группы — только когда группировка включена.
    """

    ALLOWED = ("okpd", "customer", "region")

    def __init__(self, facets: TenderFacetsPort) -> None:
        self._facets = facets

    async def execute(self, filters: TenderFilter, field: str) -> list[GroupBucket]:
        if field not in self.ALLOWED:
            raise InvalidRequest(f"По этому полю группировать нельзя: {field}")
        return await self._facets.groups(filters, field)


class SimilarTendersUseCase:
    """Похожесть считается по внутреннему id, а клиент знает реестровый номер."""

    def __init__(self, catalog: TenderCatalogPort, similarity: TenderSimilarityPort) -> None:
        self._catalog = catalog
        self._similarity = similarity

    async def execute(self, reg_num: str, limit: int) -> list[SimilarTender]:
        tender_id = await self._catalog.tender_id(reg_num)
        if tender_id is None:
            raise NotFound(f"Закупка {reg_num} не найдена", reg_num=reg_num)
        return await self._similarity.similar(tender_id, limit)

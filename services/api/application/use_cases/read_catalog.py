"""Чтение карточки закупки."""

from __future__ import annotations

from services.api.application.errors import NotFound
from services.api.application.ports.catalog import TenderCatalogPort
from services.api.domain.models import TenderDetail


class GetTenderUseCase:
    """Порт отвечает «нет такой строки», сценарий решает, что это 404."""

    def __init__(self, catalog: TenderCatalogPort) -> None:
        self._catalog = catalog

    async def execute(self, reg_num: str) -> TenderDetail:
        detail = await self._catalog.get(reg_num)
        if detail is None:
            raise NotFound(f"Закупка {reg_num} не найдена", reg_num=reg_num)
        return detail

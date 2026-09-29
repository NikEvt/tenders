"""Маршруты шлюза.

Порядок подключения важен: `/tenders/search` обязан идти до `/tenders/{reg_num}`,
иначе «search» будет разобран как реестровый номер. Внутри `catalog.py` порядок
объявления это уже обеспечивает, но при добавлении новых роутеров про правило
стоит помнить.
"""

from fastapi import APIRouter

from services.api.presentation.routers import (
    catalog,
    crawl,
    data,
    digest,
    documents,
    filters,
    load,
    monitoring,
    recommendations,
    research,
    search,
    settings,
    system,
)

ROUTERS: tuple[APIRouter, ...] = (
    catalog.router,
    crawl.router,
    documents.router,
    filters.router,
    search.router,
    digest.router,
    recommendations.router,
    research.router,
    monitoring.router,
    data.router,
    settings.router,
    load.router,
    system.router,
)

__all__ = ["ROUTERS"]

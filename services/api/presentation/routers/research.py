"""Раздел «Исследования».

Чтение — здесь: прогоны, их закупки и рыночные разрезы собираются из общей базы,
это проекция для экрана. **Запуск** — вниз, в llm-service: он владеет критериями
и рассылает заявку движку отбора. Один агрегат — один писатель, тот же разрез,
что и у фильтров.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from services.api.presentation.deps import (
    GetResearchMarket,
    GetResearchRun,
    ListResearchRuns,
    ListResearchTenders,
)
from services.api.presentation.schemas import (
    MarketOut,
    ResearchRunOut,
    ResearchTenderOut,
    ResearchTendersOut,
)

router = APIRouter(tags=["Исследования"], prefix="/research")


@router.get("/runs", response_model=list[ResearchRunOut])
async def runs(
    use_case: ListResearchRuns, limit: int = Query(default=50, ge=1, le=200)
) -> list[ResearchRunOut]:
    return [ResearchRunOut.of(card) for card in await use_case.execute(limit)]


@router.get("/runs/{run_id}", response_model=ResearchRunOut)
async def run(run_id: int, use_case: GetResearchRun) -> ResearchRunOut:
    return ResearchRunOut.of(await use_case.execute(run_id))


@router.get("/runs/{run_id}/tenders", response_model=ResearchTendersOut)
async def tenders(
    run_id: int,
    use_case: ListResearchTenders,
    confidence: str | None = Query(default=None, pattern="^(confirmed|rejected|disputed)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ResearchTendersOut:
    """Закупки прогона с вердиктом и цитатами.

    `confidence` — не фильтр «показать только хорошее»: спорные и отклонённые
    нужны не меньше, потому что по ним видно, что именно движок отбросил.
    """
    items, total = await use_case.execute(run_id, confidence, page, page_size)
    return ResearchTendersOut(
        items=[ResearchTenderOut.of(row) for row in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}/market", response_model=MarketOut)
async def market(run_id: int, use_case: GetResearchMarket) -> MarketOut:
    """Разрезы по подтверждённым закупкам прогона."""
    return MarketOut.of(await use_case.execute(run_id))

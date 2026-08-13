"""Ежедневная сводка."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from services.api.presentation.deps import DigestDates, GetDigest, LlmDep
from services.api.presentation.schemas import DigestDatesOut

router = APIRouter(tags=["Сводка"])


@router.get("/digest", response_model=DigestDatesOut)
async def digest_dates(
    use_case: DigestDates,
    since: date = Query(alias="from", description="Начало периода"),  # noqa: B008
    until: date = Query(alias="to", description="Конец периода"),  # noqa: B008
) -> DigestDatesOut:
    """За какие дни сводка уже есть — точки в календаре."""
    return DigestDatesOut(dates=await use_case.execute(since, until))


@router.get("/digest/{digest_date}")
async def digest(digest_date: date, use_case: GetDigest) -> dict:
    return await use_case.execute(digest_date)


@router.post("/digest/{digest_date}", status_code=202)
async def request_digest(digest_date: date, llm: LlmDep, force: bool = False) -> dict:
    return await llm.request_digest(digest_date, force)

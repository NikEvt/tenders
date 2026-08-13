"""Рекомендации и сигналы обратной связи — всё через recsys-service."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from services.api.presentation.deps import ProfileHistory, ProfileWins, RecsysDep
from services.api.presentation.schemas import (
    FeedbackIn,
    RatingHistoryOut,
    ViewIn,
    WeightPatchIn,
    WinIn,
    WinsOut,
)

router = APIRouter(tags=["Рекомендации"])


@router.get("/recommendations")
async def recommendations(
    recsys: RecsysDep, limit: int = Query(default=20, ge=1, le=100)
) -> list[dict]:
    return await recsys.recommendations(limit)


@router.post("/feedback", status_code=202)
async def feedback(request: FeedbackIn, recsys: RecsysDep) -> dict:
    return await recsys.feedback(request.tender_id, request.signal, request.reason)


@router.post("/views", status_code=202)
async def view(request: ViewIn, recsys: RecsysDep) -> dict:
    return await recsys.view(request.tender_id, request.dwell_ms)


@router.post("/wins", status_code=202)
async def win(request: WinIn, recsys: RecsysDep) -> dict:
    payload = request.model_dump(mode="json", exclude={"tender_id"})
    return await recsys.win(request.tender_id, payload)


@router.get("/profile")
async def profile(recsys: RecsysDep) -> dict:
    return await recsys.profile()


# ─── Профиль ──────────────────────────────────────────────────────────────────
# Чтение истории — своё, это проекция общей БД. Веса и удаление оценки —
# в recsys: правку весов обязана уважать пересборка профиля, а сигналы
# интерпретирует тот, кто по ним учится.


@router.get("/profile/weights")
async def profile_weights(recsys: RecsysDep) -> list[dict]:
    return await recsys.profile_weights()


@router.patch("/profile/weights")
async def patch_profile_weight(request: WeightPatchIn, recsys: RecsysDep) -> list[dict]:
    """`weight: null` снимает ручную правку и возвращает вычисленное значение."""
    return await recsys.set_profile_weight(request.facet, request.key, request.weight)


@router.get("/profile/ranker")
async def profile_ranker(recsys: RecsysDep) -> dict:
    """Сколько сигналов есть и сколько нужно — порог приходит с сервера."""
    return await recsys.ranker()


@router.get("/profile/history", response_model=RatingHistoryOut)
async def profile_history(
    use_case: ProfileHistory,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=50, ge=1, le=200),
) -> RatingHistoryOut:
    records, total = await use_case.execute(page, page_size)
    return RatingHistoryOut.of(records, total, page, page_size)


@router.get("/profile/wins", response_model=WinsOut)
async def profile_wins(use_case: ProfileWins) -> WinsOut:
    return WinsOut.of(await use_case.execute())


@router.delete("/profile/history/{signal_id}", status_code=204)
async def delete_rating(signal_id: int, recsys: RecsysDep) -> Response:
    """«Отменить оценку». Запись принадлежит recsys — он же по ней учится."""
    await recsys.delete_rating(signal_id)
    return Response(status_code=204)

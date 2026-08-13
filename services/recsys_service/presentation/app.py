"""HTTP-интерфейс рекомендательного сервиса."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from libs.shared.config import database_settings, rabbit_settings
from libs.shared.contracts.events import FeedbackRecorded
from libs.shared.logging import configure_logging, get_logger, set_correlation_id
from libs.shared.messaging.consumer import EventConsumer
from libs.shared.messaging.topology import QueueSpec
from services.recsys_service.bootstrap import RecsysContainer, build_container
from services.recsys_service.domain.models import MIN_SIGNALS_FOR_PERSONALIZATION, Signal

log = get_logger(__name__)

QUEUE = QueueSpec(
    name="recsys-service.feedback",
    routing_keys=("feedback.recorded",),
    prefetch=8,
)

MAX_RECOMMENDATIONS = 100


class FeedbackRequest(BaseModel):
    tender_id: int
    signal: Signal
    reason: str | None = Field(default=None, max_length=1000)


class ViewRequest(BaseModel):
    tender_id: int
    dwell_ms: int | None = Field(default=None, ge=0)


class WinRequest(BaseModel):
    tender_id: int
    won_at: date | None = None
    contract_price: Decimal | None = None
    notes: str | None = Field(default=None, max_length=2000)


class RecommendationItem(BaseModel):
    tender_id: int
    reg_num: str
    name: str | None
    description: str | None
    price: Decimal | None
    customer_name: str | None
    okpd2_code: str | None
    end_date: date | None
    score: float
    explanation: dict


class ProfileResponse(BaseModel):
    signal_count: int
    has_embedding: bool
    okpd2_weights: dict[str, float]
    price_stats: dict[str, float]
    is_usable: bool


_container: RecsysContainer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _container
    configure_logging("recsys-service")

    async with build_container(database_settings(), rabbit_settings()) as container:
        _container = container

        consumer = EventConsumer(container.connection, QUEUE, idempotency=container.idempotency)
        consumer.on(FeedbackRecorded, container.rebuild_profile.execute)
        await consumer.run()

        log.info("recsys_service.ready", queue=QUEUE.name)
        try:
            yield
        finally:
            _container = None


app = FastAPI(title="zakupki recsys-service", lifespan=lifespan)


def container() -> RecsysContainer:
    if _container is None:
        raise HTTPException(status_code=503, detail="Сервис ещё не готов")
    return _container


@app.get("/recommendations", response_model=list[RecommendationItem])
async def recommendations(
    limit: int = Query(default=20, ge=1, le=MAX_RECOMMENDATIONS),
    record: bool = Query(default=True, description="Отмечать выдачу как показанную"),
) -> list[RecommendationItem]:
    set_correlation_id()
    results = await container().recommend.execute(limit=limit, record=record)
    return [
        RecommendationItem(
            tender_id=item.candidate.tender_id,
            reg_num=item.candidate.reg_num,
            name=item.candidate.name,
            description=item.candidate.description,
            price=item.candidate.price,
            customer_name=item.candidate.customer_name,
            okpd2_code=item.candidate.okpd2_code,
            end_date=item.candidate.end_date,
            score=round(item.score, 4),
            explanation=item.breakdown.explain(),
        )
        for item in results
    ]


@app.post("/feedback", status_code=202)
async def feedback(request: FeedbackRequest) -> dict[str, str]:
    """Оценка тендера. Профиль пересобирается асинхронно, по событию."""
    set_correlation_id()
    current = container()
    await current.recommendations.record_feedback(
        request.tender_id, request.signal, request.reason
    )
    await current.publisher.publish(
        FeedbackRecorded(tender_id=request.tender_id, signal=request.signal.value)
    )
    return {"status": "accepted"}


@app.post("/views", status_code=202)
async def view(request: ViewRequest) -> dict[str, str]:
    current = container()
    await current.recommendations.record_view(request.tender_id, request.dwell_ms)

    # Мимолётный просмотр профиль не меняет — пересборку не запускаем.
    from services.recsys_service.domain.models import MIN_DWELL_MS_FOR_SIGNAL

    if request.dwell_ms and request.dwell_ms >= MIN_DWELL_MS_FOR_SIGNAL:
        await current.publisher.publish(
            FeedbackRecorded(tender_id=request.tender_id, signal="view")
        )
    return {"status": "accepted"}


@app.post("/wins", status_code=202)
async def win(request: WinRequest) -> dict[str, str]:
    """Отметка о выигранном тендере — сильнейший сигнал для профиля."""
    set_correlation_id()
    current = container()
    await current.recommendations.record_win(
        request.tender_id, request.won_at, request.contract_price, request.notes
    )
    await current.publisher.publish(
        FeedbackRecorded(tender_id=request.tender_id, signal="won")
    )
    return {"status": "accepted"}


class WeightOut(BaseModel):
    facet: str
    key: str
    label: str
    weight: float
    source: str


class WeightPatch(BaseModel):
    facet: str = "okpd2"
    key: str = Field(min_length=1, max_length=64)
    # None — сброс к вычисленному значению, а не ноль.
    weight: float | None = None


class RankerOut(BaseModel):
    kind: str
    signals: int
    threshold: int


@app.get("/profile", response_model=ProfileResponse)
async def profile() -> ProfileResponse:
    current = await container().profiles.load_profile()
    return ProfileResponse(
        signal_count=current.signal_count,
        has_embedding=current.embedding is not None,
        okpd2_weights=current.okpd2_weights,
        price_stats=current.price_stats,
        is_usable=current.is_usable,
    )


@app.get("/profile/weights", response_model=list[WeightOut])
async def profile_weights() -> list[WeightOut]:
    """Веса профиля: вычисленные и перекрытые вручную.

    `source` показывает происхождение — без него нельзя понять, почему вес
    именно такой, и стоит ли его трогать.
    """
    current = await container().profiles.load_profile()
    keys = set(current.okpd2_weights) | set(current.manual_weights)
    return [
        WeightOut(
            facet="okpd2",
            key=key,
            label=key,
            weight=current.manual_weights.get(key, current.okpd2_weights.get(key, 0.0)),
            source="manual" if key in current.manual_weights else "computed",
        )
        for key in sorted(keys)
    ]


@app.patch("/profile/weights", response_model=list[WeightOut])
async def patch_profile_weight(request: WeightPatch) -> list[WeightOut]:
    """`weight: null` снимает ручную правку и возвращает вычисленное значение."""
    await container().profiles.set_manual_weight(request.key, request.weight)
    return await profile_weights()


@app.delete("/profile/history/{signal_id}", status_code=204)
async def delete_rating(signal_id: int) -> None:
    """Отменяет оценку.

    Профиль после этого пересобирать не нужно принудительно: он перестроится
    по ближайшему сигналу, а до тех пор просто чуть отстаёт от истории.
    """
    if not await container().recommendations.delete_feedback(signal_id):
        raise HTTPException(status_code=404, detail=f"Оценка {signal_id} не найдена")


@app.get("/profile/ranker", response_model=RankerOut)
async def profile_ranker() -> RankerOut:
    """Состояние ранжировщика: сколько сигналов есть и сколько нужно.

    Порог приходит отсюда, чтобы клиент не хардкодил «нужно около 500 оценок»
    и не расходился с реальностью при смене настройки.
    """
    current = await container().profiles.load_profile()
    return RankerOut(
        kind="linear",
        signals=current.signal_count,
        threshold=MIN_SIGNALS_FOR_PERSONALIZATION,
    )


@app.post("/profile/rebuild", response_model=ProfileResponse)
async def rebuild_profile() -> ProfileResponse:
    """Ручная пересборка — нужна после массового импорта выигранных тендеров."""
    rebuilt = await container().rebuild_profile.execute()
    return ProfileResponse(
        signal_count=rebuilt.signal_count,
        has_embedding=rebuilt.embedding is not None,
        okpd2_weights=rebuilt.okpd2_weights,
        price_stats=rebuilt.price_stats,
        is_usable=rebuilt.is_usable,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    container()
    return {"status": "ready"}

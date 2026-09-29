"""HTTP-интерфейс и потребитель событий LLM-сервиса."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from libs.shared.config import (
    database_settings,
    embedding_settings,
    llm_settings,
    rabbit_settings,
)
from libs.shared.contracts.criteria_spec import CriteriaSpec, StrictSchema
from libs.shared.contracts.events import DigestRequested, Event, ResearchRequested
from libs.shared.logging import configure_logging, get_logger, set_correlation_id
from libs.shared.messaging.consumer import EventConsumer
from libs.shared.messaging.topology import QueueSpec
from libs.shared.regions import is_known_region, normalize_region_code
from services.llm_service.application.ports import LlmUnavailable
from services.llm_service.application.use_cases.generate_digest import digest_date_for
from services.llm_service.bootstrap import LlmContainer, build_container
from services.llm_service.domain.models import FilterPatch, SavedFilterView

log = get_logger(__name__)

QUEUE = QueueSpec(
    name="llm-service.jobs",
    routing_keys=("digest.requested",),
    # Модель — самый дефицитный ресурс; параллелизм ограничен внутри клиента,
    # а низкий prefetch не даёт заданиям копиться в памяти процесса.
    prefetch=2,
)

#: Во сколько по Москве идёт утренняя сборка.
#:
#: Час именно московский, и таймзона указана явно: `datetime.now()` в
#: контейнере отдаёт UTC, поэтому «7» без зоны означал 10:00 MSK, а имя
#: константы утверждало обратное.
DIGEST_HOUR_MSK = 7
MOSCOW = ZoneInfo("Europe/Moscow")


class CompileRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)


class CompileResponse(BaseModel):
    spec: CriteriaSpec


class SaveFilterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=3, max_length=2000)
    # Спецификация из конструктора. Передана — используется как есть, а `query`
    # сохраняется исходным текстом для истории; иначе текст компилируется заново.
    spec: CriteriaSpec | None = None


class PatchFilterRequest(BaseModel):
    """Частичное изменение. Не переданное поле не трогается."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    spec: CriteriaSpec | None = None
    in_digest: bool | None = None
    notify: bool | None = None
    is_active: bool | None = None


class TestFilterRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class SaveFilterResponse(BaseModel):
    filter_id: int
    spec: CriteriaSpec


class RunFilterRequest(BaseModel):
    """Что именно прогонять: критерий уже задан путём, здесь — охват.

    `tender_ids` отсюда убран. Он принимался, валидировался, пересылался через
    границу сервиса — и не читался никогда: в `ResearchRequested` поля под него
    нет. Параметр, который молча ничего не делает, хуже отсутствующего: рано
    или поздно им пользуются добросовестно.
    """

    since: date | None = None
    until: date | None = None
    regions: list[str] = Field(default_factory=list)


class JobAccepted(BaseModel):
    job_id: str


_container: LlmContainer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _container
    configure_logging("llm-service")

    async with build_container(
        database_settings(), rabbit_settings(), llm_settings(), embedding_settings()
    ) as container:
        _container = container

        consumer = EventConsumer(container.connection, QUEUE, idempotency=container.idempotency)
        consumer.on(DigestRequested, container.generate_digest.execute)
        await consumer.run()

        digest_task = asyncio.create_task(_daily_digest_loop(container))
        log.info("llm_service.ready", queue=QUEUE.name, model=container.model_name)
        try:
            yield
        finally:
            digest_task.cancel()
            _container = None


app = FastAPI(title="zakupki llm-service", lifespan=lifespan)


def container() -> LlmContainer:
    if _container is None:
        raise HTTPException(status_code=503, detail="Сервис ещё не готов")
    return _container


@app.post("/filters/compile", response_model=CompileResponse)
async def compile_filter(request: CompileRequest) -> CompileResponse:
    """Превью: свободный текст → структурный фильтр, без сохранения."""
    set_correlation_id()
    try:
        spec = await container().compile_filter.compile(request.query)
    except LlmUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Модель недоступна: {exc}") from exc
    return CompileResponse(spec=spec)


@app.post("/filters", response_model=SaveFilterResponse, status_code=201)
async def save_filter(request: SaveFilterRequest) -> SaveFilterResponse:
    set_correlation_id()
    try:
        filter_id, spec = await container().compile_filter.compile_and_save(
            request.name, request.query, request.spec
        )
    except LlmUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Модель недоступна: {exc}") from exc
    return SaveFilterResponse(filter_id=filter_id, spec=spec)


@app.get("/filters", response_model=list[SavedFilterView])
async def list_filters() -> list[SavedFilterView]:
    return await container().manage_filters.list()


@app.get("/filters/{filter_id}", response_model=SavedFilterView)
async def get_filter(filter_id: int) -> SavedFilterView:
    found = await container().manage_filters.get(filter_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Фильтр {filter_id} не найден")
    return found


@app.patch("/filters/{filter_id}", response_model=SavedFilterView)
async def patch_filter(filter_id: int, request: PatchFilterRequest) -> SavedFilterView:
    patch = FilterPatch(**request.model_dump(exclude_none=True))
    updated = await container().manage_filters.update(filter_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Фильтр {filter_id} не найден")
    return updated


@app.delete("/filters/{filter_id}", status_code=204)
async def delete_filter(filter_id: int) -> None:
    if not await container().manage_filters.delete(filter_id):
        raise HTTPException(status_code=404, detail=f"Фильтр {filter_id} не найден")


@app.post("/filters/{filter_id}/duplicate", response_model=SavedFilterView, status_code=201)
async def duplicate_filter(filter_id: int) -> SavedFilterView:
    copy = await container().manage_filters.duplicate(filter_id)
    if copy is None:
        raise HTTPException(status_code=404, detail=f"Фильтр {filter_id} не найден")
    return copy


@app.post("/filters/{filter_id}/test", response_model=JobAccepted, status_code=202)
async def test_filter(filter_id: int, request: TestFilterRequest) -> JobAccepted:
    """Пробный прогон: та же фильтрация, но со счётчиками по этапам.

    Идёт через ту же очередь, что и боевой прогон, — ретраи и ограничение
    конкурентности работают одинаково.
    """
    current = container()
    if await current.filters.get_spec(filter_id) is None:
        raise HTTPException(status_code=404, detail=f"Фильтр {filter_id} не найден")

    job_id = uuid.uuid4()
    await _publish(
        current,
        ResearchRequested(
            filter_id=filter_id,
            job_id=job_id,
            since=date.today() - timedelta(days=request.days),
            dry_run=True,
        ),
    )
    return JobAccepted(job_id=str(job_id))


@app.post("/filters/{filter_id}/run", response_model=JobAccepted, status_code=202)
async def run_filter(filter_id: int, request: RunFilterRequest) -> JobAccepted:
    """Запускает исследование асинхронно: прогон по сотням тендеров занимает минуты.

    Регионы и сроки задаются здесь и **перекрывают** структурные условия
    критерия: человек выбрал охват явно, и молча его расширять нельзя — иначе
    знаменатель воронки перестанет соответствовать запросу.
    """
    current = container()
    if await current.filters.get_spec(filter_id) is None:
        raise HTTPException(status_code=404, detail=f"Фильтр {filter_id} не найден")

    if request.since and request.until and request.until < request.since:
        raise HTTPException(status_code=422, detail="Конец периода раньше начала")

    # Опечатка в коде региона иначе дала бы прогон, который ничего не прочитал,
    # ничего не нашёл и отчитался чистой воронкой нулей — ложноотрицательный
    # результат в обличье настоящего.
    unknown = [code for code in request.regions if not is_known_region(code)]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Неизвестные коды регионов: {', '.join(unknown)}"
        )

    job_id = uuid.uuid4()
    # Задание идёт через ту же очередь, что и события: ретраи, dead-letter
    # и ограничение конкурентности работают одинаково для обоих путей.
    await _publish(
        current,
        ResearchRequested(
            filter_id=filter_id,
            job_id=job_id,
            regions=[normalize_region_code(code) or code for code in request.regions],
            since=request.since,
            until=request.until,
        ),
    )
    return JobAccepted(job_id=str(job_id))


class _JudgeEvidence(StrictSchema):
    """Ссылка на цитату, которую показывали модели.

    Номер, а не свободный текст: только по нему вызывающий может сверить ответ
    с тем, что действительно передавал. Модель охотно цитирует правдоподобное,
    но отсутствующее.
    """

    hit_number: int
    quote: str = ""


class _JudgeVerdict(StrictSchema):
    """Схема структурного ответа судьи."""

    match: bool
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    reasoning: str = ""
    evidence: list[_JudgeEvidence] = Field(default_factory=list)


class JudgeRequest(BaseModel):
    """Промпт судьи целиком. Формулировку задаёт движок отбора, не сервис.

    Здесь остаётся только транспорт: ключи, схема авторизации и структурный
    вывод — забота llm-service, а что считать подходящей закупкой, знает тот,
    кто ищет.
    """

    system: str
    user: str


class JudgeResponse(BaseModel):
    match: bool
    score: float = 0.0
    reasoning: str = ""
    evidence: list[dict] = Field(default_factory=list)


@app.post("/judge", response_model=JudgeResponse)
async def judge(request: JudgeRequest) -> JudgeResponse:
    """Структурный вердикт по готовому промпту.

    Ответ 503 при недоступной модели — не деталь: по нему вызывающий понимает,
    что останавливаться надо целиком, а не перебирать очередь.
    """
    current = container()
    try:
        verdict = await current.llm.structured(
            system=request.system,
            user=request.user,
            schema=_JudgeVerdict,
            reasoning_effort=current.judge_reasoning_effort,
        )
    except LlmUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Модель недоступна: {exc}") from exc

    return JudgeResponse(
        match=verdict.match,
        score=verdict.score,
        reasoning=verdict.reasoning,
        evidence=[item.model_dump() for item in verdict.evidence],
    )


@app.post("/digest/{digest_date}", response_model=JobAccepted, status_code=202)
async def request_digest(digest_date: date, force: bool = False) -> JobAccepted:
    event = DigestRequested(digest_date=digest_date, force=force)
    await _publish(container(), event)
    return JobAccepted(job_id=str(event.event_id))


async def _publish(current: LlmContainer, event: Event) -> None:
    from libs.shared.messaging.publisher import RabbitPublisher

    publisher = RabbitPublisher(current.connection)
    await publisher.setup()
    await publisher.publish(event)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready", "model": container().model_name}


async def _daily_digest_loop(current: LlmContainer) -> None:
    """Держит сводку в актуальном состоянии.

    Расписание внутри сервиса, а не во внешнем cron: так оно едет вместе с кодом
    и не разъезжается с версией промпта.

    Три свойства, каждое куплено отдельным дефектом.

    **Просит две сводки, а не одну.** За сегодня — черновик, он пересобирается
    и догоняет доезжающие данные. За вчера — финальную: день закончился, и её
    можно закрывать. Раньше просилась только вчерашняя, а главная страница
    спрашивала сегодняшнюю, которой не существовало никогда.

    **Работает сразу при старте, а не после первого сна.** Прежний цикл спал
    первым делом, поэтому рестарт после часа сборки означал день без сводки
    вовсе — в базе так и осталось три пустых дня подряд.

    **Час считается по Москве.** `datetime.now()` в контейнере — UTC.
    """
    from libs.shared.messaging.publisher import RabbitPublisher

    publisher = RabbitPublisher(current.connection)
    await publisher.setup()

    while True:
        await _request_digests(publisher)
        await asyncio.sleep(_seconds_until_next_run())


async def _request_digests(publisher) -> None:
    """Черновик за сегодня и финальная за вчера.

    Порядок важен ровно настолько, насколько важна очерёдность на экране:
    сначала то, что пользователь откроет утром.
    """
    today = _moscow_today()
    for digest_date in (today, digest_date_for(today)):
        try:
            set_correlation_id()
            await publisher.publish(DigestRequested(digest_date=digest_date))
            log.info("digest.scheduled", digest_date=digest_date.isoformat())
        except Exception as exc:
            # Отказ по одной дате не должен уносить вторую.
            log.error(
                "digest.schedule_failed",
                digest_date=digest_date.isoformat(),
                error=str(exc),
            )


def _moscow_today() -> date:
    return datetime.now(MOSCOW).date()


def _seconds_until_next_run() -> float:
    now = datetime.now(MOSCOW)
    target = datetime.combine(now.date(), time(hour=DIGEST_HOUR_MSK), tzinfo=MOSCOW)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()

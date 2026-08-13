"""Фильтры и статус заданий.

Разрез по CQRS. **Чтение** — своё: список и карточка собираются из общей БД
вместе со статистикой совпадений, потому что это проекция для экрана.
**Запись** — вниз, в llm-service: он компилирует спецификацию, знает версию
промпта и инвалидирует ею кэш вердиктов. Один агрегат — один писатель.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from services.api.presentation.deps import GetFilter, GetJob, ListFilters, LlmDep
from services.api.presentation.schemas import (
    CompileFilterIn,
    FilterOut,
    PatchFilterIn,
    RunFilterIn,
    SaveFilterIn,
    TestFilterIn,
)

router = APIRouter(tags=["Фильтры"])


@router.get("/filters", response_model=list[FilterOut])
async def list_filters(use_case: ListFilters) -> list[FilterOut]:
    return [FilterOut.of(card) for card in await use_case.execute()]


@router.get("/filters/{filter_id}", response_model=FilterOut)
async def get_filter(filter_id: int, use_case: GetFilter) -> FilterOut:
    return FilterOut.of(await use_case.execute(filter_id))


@router.post("/filters/compile")
async def compile_filter(request: CompileFilterIn, llm: LlmDep) -> dict:
    """Превью структурного фильтра из свободного текста, без сохранения."""
    return await llm.compile_filter(request.query)


@router.post("/filters", status_code=201)
async def save_filter(request: SaveFilterIn, llm: LlmDep) -> dict:
    return await llm.save_filter(request.name, request.query, request.spec)


@router.patch("/filters/{filter_id}")
async def patch_filter(filter_id: int, request: PatchFilterIn, llm: LlmDep) -> dict:
    return await llm.patch_filter(filter_id, request.model_dump(exclude_none=True))


@router.delete("/filters/{filter_id}", status_code=204)
async def delete_filter(filter_id: int, llm: LlmDep) -> Response:
    await llm.delete_filter(filter_id)
    return Response(status_code=204)


@router.post("/filters/{filter_id}/duplicate", status_code=201)
async def duplicate_filter(filter_id: int, llm: LlmDep) -> dict:
    return await llm.duplicate_filter(filter_id)


@router.post("/filters/{filter_id}/run", status_code=202)
async def run_filter(filter_id: int, request: RunFilterIn, llm: LlmDep) -> dict:
    """Запуск LLM-фильтрации. Прогон занимает минуты — отвечаем job_id."""
    return await llm.run_filter(filter_id, request.since, request.tender_ids)


@router.post("/filters/{filter_id}/test", status_code=202)
async def test_filter(filter_id: int, request: TestFilterIn, llm: LlmDep) -> dict:
    """Пробный прогон: та же фильтрация, но с разбивкой по этапам отбора.

    Результат приходит в `GET /jobs/{job_id}.result.funnel`.
    """
    return await llm.test_filter(filter_id, request.days)


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, use_case: GetJob) -> dict:
    return await use_case.execute(job_id)

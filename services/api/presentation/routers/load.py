"""Уровень нагрузки на машину.

Переключение задумано под живой сценарий — человек садится за тяжёлый софт и
просит систему подвинуться. Поэтому перезапуска здесь нет: заявка пишется в
настройку, воркеры сверяются с ней сами и применяют потолки на границе задач.
Уже начатая работа доводится до конца.
"""

from __future__ import annotations

from fastapi import APIRouter

from libs.shared.load_policy import LoadLevel
from services.api.presentation.deps import ReadLoadLevel, SetLoadLevel
from services.api.presentation.schemas import LoadLevelIn, LoadLevelOut

router = APIRouter(tags=["Система"], prefix="/system")


@router.get("/load-level", response_model=LoadLevelOut)
async def load_level(use_case: ReadLoadLevel) -> LoadLevelOut:
    return LoadLevelOut.of(await use_case.execute())


@router.patch("/load-level", response_model=LoadLevelOut)
async def set_load_level(request: LoadLevelIn, use_case: SetLoadLevel) -> LoadLevelOut:
    """Смена уровня. Ответ приходит сразу, воркеры подтягиваются за секунды."""
    return LoadLevelOut.of(await use_case.execute(LoadLevel(request.level)))

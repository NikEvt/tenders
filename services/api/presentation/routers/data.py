"""Вкладка «Данные»: состав корпуса и ход его обогащения.

Раздел отвечает на вопрос «с чем я работаю», а мониторинг — на «что сломано».
Числа, которые мониторинг уже считает, здесь не пересчитываются: воронка
документов и глубина очереди берутся его портами.

Два маршрута, а не один, потому что у них разная частота опроса: состав корпуса
стабилен и считается групповыми запросами, ход обработки опрашивается каждые
пятнадцать секунд. Слить их значило бы гонять групповые запросы по всей
`tenders` четыре раза в минуту.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from services.api.application.use_cases.read_corpus import (
    DEFAULT_DAYS,
    DEFAULT_TOP,
    MAX_DAYS,
    MAX_TOP,
)
from services.api.presentation.deps import CorpusOverview, CorpusProcessing
from services.api.presentation.schemas import CorpusOverviewOut, CorpusProcessingOut

router = APIRouter(tags=["Данные"], prefix="/data")


@router.get("/overview", response_model=CorpusOverviewOut)
async def overview(
    use_case: CorpusOverview,
    days: int = Query(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS),
    limit: int = Query(default=DEFAULT_TOP, ge=1, le=MAX_TOP),
) -> CorpusOverviewOut:
    """Состав корпуса за период: по дням, регионам и ОКПД2.

    Период один на все разрезы — иначе «топ регионов за всё время» рядом со
    столбиками за квартал читался бы как один разрез, описывая другое
    множество.
    """
    return CorpusOverviewOut.of(await use_case.execute(days=days, limit=limit))


@router.get("/processing", response_model=CorpusProcessingOut)
async def processing(use_case: CorpusProcessing) -> CorpusProcessingOut:
    """Ход векторизации и сегодняшней выгрузки."""
    return CorpusProcessingOut.of(await use_case.execute())

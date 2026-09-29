"""Заказ выгрузки из ЕИС.

Ход выгрузки виден в `GET /jobs/{job_id}` — там же, где ход исследования и
сборки сводки.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from libs.shared.regions import is_known_region, normalize_region_code
from services.api.presentation.deps import CrawlDep
from services.api.presentation.schemas import CrawlIn, JobAcceptedOut

router = APIRouter(tags=["Выгрузка"])

#: Глубина одной заявки. Заявка на год из интерфейса — способ случайно
#: устроить себе бан: она разворачивается в тысячи обращений к ЕИС.
MAX_PERIOD_DAYS = 90


@router.post("/crawl", response_model=JobAcceptedOut, status_code=202)
async def request_crawl(request: CrawlIn, crawl: CrawlDep) -> JobAcceptedOut:
    """Заказывает выгрузку периода.

    ЕИС отдаёт извещения суточными архивами, поэтому «обновить» означает
    перекачать архивы последних дней: новыми окажутся лишь те извещения,
    которых ещё не было. Уже закрытые дни пропускаются сами — день считается
    закрытым, только если выгрузка шла после его окончания.
    """
    since = request.since or date.today() - timedelta(days=1)
    until = request.until or date.today()

    if until < since:
        raise HTTPException(status_code=422, detail="Конец периода раньше начала")
    if (until - since).days + 1 > MAX_PERIOD_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Период длиннее {MAX_PERIOD_DAYS} дней — закажите его частями",
        )

    unknown = [code for code in request.regions if not is_known_region(code)]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Неизвестные коды регионов: {', '.join(unknown)}"
        )

    job_id = uuid.uuid4()
    await crawl.request(
        job_id=job_id,
        regions=[normalize_region_code(code) or code for code in request.regions],
        date_from=since,
        date_to=until,
    )
    return JobAcceptedOut(job_id=str(job_id))

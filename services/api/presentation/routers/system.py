"""Служебные пробы.

`/health` отвечает всегда, пока жив процесс; `/health/ready` — только когда
поднялись зависимости. Оркестратору нужны обе: первая для рестарта, вторая для
включения в балансировку.
"""

from __future__ import annotations

from fastapi import APIRouter

from services.api.presentation.deps import ReadinessDep

router = APIRouter(tags=["Служебное"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(readiness: ReadinessDep) -> dict:
    await readiness.check()
    return {"status": "ready"}

"""Состояние длительного прогона — то, что читает `GET /jobs/{id}`.

Своя реализация, а не заимствованная у `llm-service`: сервисы не импортируют
друг друга. Таблица общая, потому что общий у них экран, а не код.

Главное здесь — `fail`. Прогон, упавший молча, оставляет задание в `running`
навсегда: интерфейс показывает вечное «идёт», пользователь ждёт результата,
которого не будет. Ошибка обязана доехать до экрана.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import Job


class SqlJobTracker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start(
        self, job_id: str, kind: str, total: int, phase: str | None = None
    ) -> None:
        """Начинает задание или **переводит его в следующую фазу**.

        Вставка с обновлением и обнулением `processed` — не оптимизация, а
        смысл: у новой фазы свой знаменатель, и оставить прежнее число значило
        бы стартовать её шкалу с чужого места.
        """
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(Job).values(
                id=job_id,
                kind=kind,
                status="running",
                phase=phase,
                total=total,
                processed=0,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Job.id],
                    set_={
                        "status": "running",
                        "phase": phase,
                        "total": total,
                        "processed": 0,
                        "updated_at": func.now(),
                    },
                )
            )

    async def progress(self, job_id: str, processed: int) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(processed=processed, updated_at=func.now())
            )

    async def finish(self, job_id: str, result: dict[str, Any]) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status="done", result=result, updated_at=func.now())
            )

    async def fail(self, job_id: str, error: str) -> None:
        """Помечает задание упавшим.

        Вставка с обновлением, а не UPDATE: падение до того, как отработал
        `start`, обязано всё равно оставить строку. Иначе экран опрашивает
        задание, которого нет, и вечное «идёт» превращается в вечную 404.
        """
        message = error[:1000]
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(Job).values(
                id=job_id, kind="research", status="failed", error_message=message
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Job.id],
                    set_={
                        "status": "failed",
                        "error_message": message,
                        "updated_at": func.now(),
                    },
                )
            )

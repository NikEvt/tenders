"""Репозитории LLM-сервиса: фильтры, вердикты, сводки, задания."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.contracts.criteria_spec import CriteriaSpec
from libs.shared.db.schema import (
    DailyDigest,
    Job,
    LlmVerdict,
    ResearchVerdict,
    SavedFilter,
    Tender,
)
from libs.shared.db.tender_criteria import TenderCriteria, predicates
from libs.shared.logging import get_logger
from services.llm_service.application.ports import (
    DigestRepositoryPort,
    FilterRepositoryPort,
    JobTrackerPort,
)
from services.llm_service.domain.models import (
    DigestInput,
    DigestScope,
    FilterPatch,
    SavedFilterView,
    TenderCandidate,
    Verdict,
)

log = get_logger(__name__)

# Сколько закупок попадает в сводку по каждому разделу.
DIGEST_TOP_LIMIT = 15
DIGEST_CLUSTER_TENDERS = 200
# Заказчик считается новым, если раньше этой даты его закупок в базе не было.
NEW_CUSTOMER_LOOKBACK_DAYS = 90


def _to_view(row: SavedFilter) -> SavedFilterView:
    """Строка БД → карточка фильтра.

    Критерий и семантика лежат отдельными колонками, чтобы их можно было
    править без перезаписи всего JSON, — при чтении они возвращаются в spec.
    """
    spec = CriteriaSpec.model_validate(row.spec)
    return SavedFilterView(
        filter_id=row.id,
        name=row.name,
        query=row.nl_query or "",
        spec=spec,
        in_digest=row.in_digest,
        notify=row.notify,
        is_active=row.is_active,
        created_at=row.created_at,
        last_run_at=row.last_run_at,
    )


class SqlFilterRepository(FilterRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_spec(self, filter_id: int) -> CriteriaSpec | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(SavedFilter).where(SavedFilter.id == filter_id)
            )
        if row is None:
            return None

        spec = CriteriaSpec.model_validate(row.spec)
        # Критерий и семантический запрос хранятся отдельными колонками, чтобы
        # их можно было править без перезаписи всего JSON.
        return spec

    async def save_compiled(self, name: str, nl_query: str, spec: CriteriaSpec) -> int:
        async with self._session_factory() as session, session.begin():
            filter_id = await session.scalar(
                pg_insert(SavedFilter)
                .values(
                    name=name,
                    nl_query=nl_query,
                    spec=spec.model_dump(mode="json"),
                )
                .returning(SavedFilter.id)
            )
        assert filter_id is not None
        return filter_id

    async def active_filters(self) -> list[tuple[int, CriteriaSpec]]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(SavedFilter).where(SavedFilter.is_active.is_(True))
                )
            ).all()

        result: list[tuple[int, CriteriaSpec]] = []
        for row in rows:
            spec = CriteriaSpec.model_validate(row.spec)
            result.append((row.id, spec))
        return result

    async def list_filters(self) -> list[SavedFilterView]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(SavedFilter).order_by(SavedFilter.created_at.desc())
                )
            ).all()
        return [_to_view(row) for row in rows]

    async def get_filter(self, filter_id: int) -> SavedFilterView | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(SavedFilter).where(SavedFilter.id == filter_id))
        return _to_view(row) if row is not None else None

    async def save_spec(self, name: str, nl_query: str, spec: CriteriaSpec) -> int:
        # Отличие от save_compiled только в источнике spec: там его посчитала
        # модель, здесь — прислал конструктор. Инвариант «spec согласован с
        # колонками критерия и семантики» держится одинаково.
        return await self.save_compiled(name, nl_query, spec)

    async def update_filter(self, filter_id: int, patch: FilterPatch) -> SavedFilterView | None:
        values: dict = {}
        if patch.name is not None:
            values["name"] = patch.name
        if patch.in_digest is not None:
            values["in_digest"] = patch.in_digest
        if patch.notify is not None:
            values["notify"] = patch.notify
        if patch.is_active is not None:
            values["is_active"] = patch.is_active
        if patch.spec is not None:
            values["spec"] = patch.spec.model_dump(mode="json")
        if values:
            values["updated_at"] = func.now()

        async with self._session_factory() as session, session.begin():
            if values:
                await session.execute(
                    update(SavedFilter).where(SavedFilter.id == filter_id).values(**values)
                )
            row = await session.scalar(select(SavedFilter).where(SavedFilter.id == filter_id))
            return _to_view(row) if row is not None else None

    async def delete_filter(self, filter_id: int) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                delete(SavedFilter).where(SavedFilter.id == filter_id)
            )
        # Вердикты уходят каскадом: без фильтра они не интерпретируются.
        return bool(result.rowcount)

    async def cached_verdict_tender_ids(
        self, filter_id: int, prompt_version: str
    ) -> set[int]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(LlmVerdict.tender_id).where(
                        LlmVerdict.filter_id == filter_id,
                        LlmVerdict.prompt_version == prompt_version,
                    )
                )
            ).all()
        return set(rows)

    async def save_verdict(
        self,
        tender_id: int,
        filter_id: int,
        verdict: Verdict,
        model: str,
        prompt_version: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(LlmVerdict).values(
                tender_id=tender_id,
                filter_id=filter_id,
                match=verdict.match,
                score=verdict.score,
                reasoning=verdict.reasoning,
                evidence=[item.model_dump(mode="json") for item in verdict.evidence],
                model=model,
                prompt_version=prompt_version,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_llm_verdict",
                    set_={
                        "match": statement.excluded.match,
                        "score": statement.excluded.score,
                        "reasoning": statement.excluded.reasoning,
                        "evidence": statement.excluded.evidence,
                        "model": statement.excluded.model,
                    },
                )
            )


class SqlDigestRepository(DigestRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def built_at(self, digest_date: date) -> datetime | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(DailyDigest.generated_at).where(
                    DailyDigest.digest_date == digest_date
                )
            )

    async def collect(self, digest_date: date) -> DigestInput:
        start = datetime.combine(digest_date, time.min)
        end = start + timedelta(days=1)

        async with self._session_factory() as session:
            scope, selected = await self._scope(session)
            published = (
                Tender.publish_date >= start,
                Tender.publish_date < end,
                # Отбор по фильтрам, включённым в сводку. До этого условия
                # сводка молча брала весь день, а тумблер «включать в сводку»
                # не был подключён ни к чему.
                *( [selected] if selected is not None else [] ),
            )

            total = await session.scalar(
                select(func.count()).select_from(Tender).where(*published)
            )
            total_price = await session.scalar(
                select(func.coalesce(func.sum(Tender.price), 0)).where(*published)
            )

            rows = (
                await session.execute(
                    select(
                        Tender.id,
                        Tender.reg_num,
                        Tender.name,
                        Tender.description,
                        Tender.price,
                        Tender.customer_name,
                        Tender.customer_inn,
                        Tender.okpd2_code,
                        Tender.okpd2_name,
                        Tender.end_date,
                    )
                    .where(*published)
                    .order_by(Tender.price.desc().nullslast())
                    .limit(DIGEST_CLUSTER_TENDERS)
                )
            ).all()

            changed = (
                await session.execute(
                    select(
                        Tender.id,
                        Tender.reg_num,
                        Tender.name,
                        Tender.description,
                        Tender.price,
                        Tender.customer_name,
                        Tender.okpd2_code,
                        Tender.end_date,
                    )
                    .where(
                        Tender.updated_at >= start,
                        Tender.updated_at < end,
                        Tender.prev_end_date.is_not(None),
                        Tender.prev_end_date != Tender.end_date,
                        # Сдвиг срока интересен по тем же закупкам, что и
                        # остальная сводка. Иначе раздел описывал бы весь
                        # рынок, а соседний — только отобранное.
                        *([selected] if selected is not None else []),
                    )
                    .limit(DIGEST_TOP_LIMIT)
                )
            ).all()

            new_customers = await self._new_customers(session, digest_date, selected)

        candidates = [_to_candidate(row) for row in rows]
        clusters: dict[str, list[TenderCandidate]] = {}
        for row, candidate in zip(rows, candidates, strict=True):
            # Группируем по названию ОКПД2: код без расшифровки в сводке нечитаем.
            category = row.okpd2_name or "Прочее"
            clusters.setdefault(category, []).append(candidate)

        return DigestInput(
            digest_date=digest_date,
            total=total or 0,
            total_price=Decimal(total_price or 0),
            top_by_price=candidates[:DIGEST_TOP_LIMIT],
            clusters=clusters,
            deadline_changes=[_to_candidate(row) for row in changed],
            new_customers=new_customers,
            scope=scope,
        )

    async def _scope(
        self, session: AsyncSession
    ) -> tuple[DigestScope, ColumnElement[bool] | None]:
        """Какие фильтры включены в сводку — и условие отбора по ним.

        Условие собирается **тем же** `predicates`, что и каталог: правило
        «какие закупки прошли сохранённый фильтр» живёт в одном месте
        (`libs/shared/db/tender_criteria.py`), и второй его реализации здесь
        быть не должно. Однажды такая уже завелась и разошлась с первой.

        Фильтров может быть несколько, поэтому условия объединяются `OR`:
        сводка — это объединение того, что интересно, а не пересечение.

        Возвращает `None` вместо условия, когда включённых фильтров нет: тогда
        сводка честно описывает весь день, и это её область отбора.
        """
        rows = (
            await session.execute(
                select(SavedFilter.id, SavedFilter.name, SavedFilter.spec).where(
                    SavedFilter.is_active.is_(True),
                    SavedFilter.in_digest.is_(True),
                )
            )
        ).all()
        if not rows:
            return DigestScope(), None

        # Фильтр без прогонов вердиктов не имеет и не принесёт ни одной
        # закупки. Молчать об этом нельзя: пустая сводка выглядела бы выводом
        # о рынке, хотя это несделанная работа.
        versions = {
            row.id: (row.spec or {}).get("version") for row in rows
        }
        judged = set(
            (
                await session.scalars(
                    select(func.distinct(ResearchVerdict.criteria_version)).where(
                        ResearchVerdict.criteria_version.in_(
                            [v for v in versions.values() if v]
                        )
                    )
                )
            ).all()
        )

        scope = DigestScope(
            filters=[row.name for row in rows],
            unrun_filters=[
                row.name for row in rows if versions.get(row.id) not in judged
            ],
        )
        condition = or_(
            *(
                predicates(TenderCriteria(filter_id=row.id))["filter_id"]
                for row in rows
            )
        )
        return scope, condition

    async def _new_customers(
        self,
        session: AsyncSession,
        digest_date: date,
        selected: ColumnElement[bool] | None,
    ) -> list[str]:
        start = datetime.combine(digest_date, time.min)
        end = start + timedelta(days=1)
        lookback = start - timedelta(days=NEW_CUSTOMER_LOOKBACK_DAYS)

        seen_before = (
            select(Tender.customer_inn)
            .where(Tender.publish_date >= lookback, Tender.publish_date < start)
            .scalar_subquery()
        )
        rows = (
            await session.scalars(
                select(func.distinct(Tender.customer_name)).where(
                    Tender.publish_date >= start,
                    Tender.publish_date < end,
                    Tender.customer_inn.is_not(None),
                    Tender.customer_inn.notin_(seen_before),
                    # «Новый» — в пределах области отбора: заказчик, впервые
                    # появившийся с интересной закупкой, и заказчик, впервые
                    # появившийся вообще, — разные новости.
                    *([selected] if selected is not None else []),
                )
            )
        ).all()
        return [name for name in rows if name][:DIGEST_TOP_LIMIT]

    async def save(
        self,
        digest_date: date,
        summary_md: str,
        sections: dict,
        tender_count: int,
        model: str,
        prompt_version: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(DailyDigest).values(
                digest_date=digest_date,
                summary_md=summary_md,
                sections=sections,
                tender_count=tender_count,
                model=model,
                prompt_version=prompt_version,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[DailyDigest.digest_date],
                    set_={
                        "summary_md": statement.excluded.summary_md,
                        "sections": statement.excluded.sections,
                        "tender_count": statement.excluded.tender_count,
                        "model": statement.excluded.model,
                        "prompt_version": statement.excluded.prompt_version,
                        "generated_at": func.now(),
                    },
                )
            )


class SqlJobTracker(JobTrackerPort):
    """Статус длительной операции — то, что читает `GET /jobs/{id}`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start(
        self, job_id: str, kind: str, total: int, phase: str | None = None
    ) -> None:
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

    async def finish(self, job_id: str, result: dict) -> None:
        # `processed` не трогаем: он уже доведён до `total` ходом операции.
        # Раньше здесь стояло `result.get("evaluated_by_llm", 0)` — наследие
        # удалённого движка фильтров, обнулявшее полосу в момент завершения.
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status="done", result=result, updated_at=func.now())
            )

    async def fail(self, job_id: str, error: str) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(Job).values(
                id=job_id, kind="digest", status="failed", error_message=error[:2000]
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Job.id],
                    set_={
                        "status": "failed",
                        "error_message": error[:2000],
                        "updated_at": func.now(),
                    },
                )
            )


def _to_candidate(row) -> TenderCandidate:
    return TenderCandidate(
        tender_id=row.id,
        reg_num=row.reg_num,
        name=row.name,
        description=getattr(row, "description", None),
        price=row.price,
        customer_name=row.customer_name,
        okpd2_code=row.okpd2_code,
        end_date=row.end_date.date() if row.end_date else None,
    )

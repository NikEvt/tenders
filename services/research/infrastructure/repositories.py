"""Персистентность движка отбора: корпус, находки, прогоны, кэш вердиктов."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import (
    DocumentText,
    ResearchHit,
    ResearchRun,
    ResearchVerdict,
    SavedFilter,
    Tender,
    TenderDocument,
)
from libs.shared.db.tender_criteria import TenderCriteria, predicates
from services.research.application.ports import (
    CorpusDocument,
    CorpusPort,
    CorpusTender,
    HitRepositoryPort,
    ResearchRunPort,
    ScanStats,
    TenderVerdict,
    VerdictStorePort,
)
from services.research.domain.criteria import (
    Confidence,
    Criteria,
    Structural,
    criteria_from_spec,
)
from services.research.domain.hits import Hit

#: Сколько карточек тянуть за раз. Корпус — сотни тысяч строк, и держать его
#: в памяти незачем: движку нужна одна закупка за раз.
TENDER_BATCH = 500

#: Сколько вердиктов писать одним INSERT. Полный прогон по корпусу приносит
#: тысячи решений, а одно выражение на все — лишний способ упереться в предел
#: параметров запроса.
VERDICT_BATCH = 500


class SqlCorpusRepository(CorpusPort):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        structural: Structural | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._structural = structural

    async def tenders(
        self, regions: Sequence[str] | None, since: date | None, until: date | None
    ) -> AsyncIterator[CorpusTender]:
        """Поток карточек, порциями по первичному ключу.

        Курсор по `id`, а не OFFSET: на сотнях тысяч строк OFFSET заставляет
        базу каждый раз перечитывать всё, что уже отдано.
        """
        after = 0
        while True:
            async with self._session_factory() as session:
                rows = (
                    await session.execute(
                        select(
                            Tender.id,
                            Tender.reg_num,
                            Tender.name,
                            Tender.description,
                            Tender.customer_name,
                            Tender.okpd2_code,
                            Tender.okpd2_codes,
                            Tender.okpd2_name,
                        )
                        .where(*_period(regions, since, until, self._structural), Tender.id > after)
                        .order_by(Tender.id)
                        .limit(TENDER_BATCH)
                    )
                ).all()

            if not rows:
                return

            for row in rows:
                after = row.id
                yield CorpusTender(
                    tender_id=row.id,
                    reg_num=row.reg_num,
                    name=row.name,
                    description=row.description,
                    customer_name=row.customer_name,
                    okpd2_code=row.okpd2_code,
                    okpd2_codes=tuple(row.okpd2_codes or ()),
                    okpd2_names=(row.okpd2_name,) if row.okpd2_name else (),
                )

    async def documents(self, tender_id: int) -> list[CorpusDocument]:
        """Все вложения закупки, в том числе ещё не разобранные.

        Внешнее соединение, а не внутреннее: документ без текста — это и есть
        знаменатель воронки, и считать его надо там же, где считается
        числитель, то есть в обходе кандидатов. Отдельный запрос по всему
        корпусу считал другую популяцию и завышал знаменатель в разы.
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        TenderDocument.id,
                        DocumentText.text_key,
                        TenderDocument.file_name,
                    )
                    .outerjoin(DocumentText, DocumentText.document_id == TenderDocument.id)
                    .where(TenderDocument.tender_id == tender_id)
                    .order_by(TenderDocument.priority.nullslast(), TenderDocument.id)
                )
            ).all()

        return [
            CorpusDocument(document_id=row.id, text_key=row.text_key, file_name=row.file_name)
            for row in rows
        ]

    async def count_tenders(
        self, regions: Sequence[str] | None, since: date | None, until: date | None
    ) -> int:
        async with self._session_factory() as session:
            return (
                await session.scalar(
                    select(func.count())
                    .select_from(Tender)
                    .where(*_period(regions, since, until, self._structural))
                )
            ) or 0


class SqlHitRepository(HitRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, run_id: int, tender_id: int, hits: Sequence[Hit]) -> None:
        if not hits:
            return
        async with self._session_factory() as session, session.begin():
            await session.execute(
                insert(ResearchHit),
                [
                    {
                        "run_id": run_id,
                        "tender_id": tender_id,
                        "term": hit.term,
                        "role": str(hit.role),
                        "quote": hit.quote,
                        "match_start": hit.match_start,
                        "match_end": hit.match_end,
                        "file_name": hit.file_name,
                        "page": hit.page,
                        "source_offset": hit.source_offset,
                    }
                    for hit in hits
                ],
            )


class SqlResearchRunRepository(ResearchRunPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start(
        self,
        name: str,
        criteria: Criteria,
        regions: Sequence[str] | None,
        since: date | None,
        until: date | None,
    ) -> int:
        async with self._session_factory() as session, session.begin():
            run_id = await session.scalar(
                insert(ResearchRun)
                .values(
                    name=name,
                    criteria_version=criteria.version,
                    criteria=_describe(criteria),
                    regions=list(regions) if regions else None,
                    date_from=since,
                    date_to=until,
                    status="running",
                )
                .returning(ResearchRun.id)
            )
        assert run_id is not None
        return int(run_id)

    async def update_funnel(self, run_id: int, stats: ScanStats) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(ResearchRun)
                .where(ResearchRun.id == run_id)
                .values(
                    tenders_total=stats.tenders_total,
                    tenders_candidate=stats.tenders_candidate,
                    documents_scanned=stats.documents_scanned,
                    documents_pending=stats.documents_pending,
                    hits_found=stats.hits_found,
                )
            )

    async def finish(
        self, run_id: int, confirmed: int, rejected: int, disputed: int
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(ResearchRun)
                .where(ResearchRun.id == run_id)
                .values(
                    status="done",
                    finished_at=func.now(),
                    tenders_confirmed=confirmed,
                    tenders_rejected=rejected,
                    tenders_disputed=disputed,
                )
            )

    async def fail(self, run_id: int, error: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(ResearchRun)
                .where(ResearchRun.id == run_id)
                .values(status="failed", finished_at=func.now(), error_message=error[:2000])
            )


class SqlVerdictStore(VerdictStorePort):
    """Решения по закупкам: и кэш модели, и то, по чему отбирает каталог.

    Ключ не включает прогон: решение принадлежит паре «закупка + критерий».
    Поэтому повторный прогон не тратит токенов, а правка шаблонов обесценивает
    прежние решения сама собой — через версию критериев.

    Сюда же ходит `libs/shared/db/tender_criteria.py` за отбором по
    сохранённому фильтру, так что таблица — источник истины для выдачи, а не
    только хранилище оплаченных ответов.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def stored(
        self, tender_ids: Sequence[int], criteria_version: str, prompt_version: str
    ) -> dict[int, TenderVerdict]:
        if not tender_ids:
            return {}
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(ResearchVerdict).where(
                        ResearchVerdict.tender_id.in_(list(tender_ids)),
                        ResearchVerdict.criteria_version == criteria_version,
                        ResearchVerdict.prompt_version == prompt_version,
                    )
                )
            ).scalars().all()

        return {
            row.tender_id: TenderVerdict(
                tender_id=row.tender_id,
                confidence=Confidence(row.confidence),
                reason=row.reason or "",
                score=row.score,
                decided_by=row.decided_by,
                evidence=list(row.evidence or []),
            )
            for row in rows
        }

    async def save(
        self,
        verdicts: Sequence[TenderVerdict],
        criteria_version: str,
        prompt_version: str,
        model: str,
    ) -> None:
        if not verdicts:
            return

        # Последний вердикт по закупке побеждает: Postgres отказывается
        # применять ON CONFLICT DO UPDATE дважды к одной строке в пределах
        # одного INSERT, а внутри прогона решение по закупке ровно одно.
        unique = {verdict.tender_id: verdict for verdict in verdicts}
        rows = [
            {
                "tender_id": verdict.tender_id,
                "criteria_version": criteria_version,
                "prompt_version": prompt_version,
                "confidence": str(verdict.confidence),
                "reason": verdict.reason,
                "score": verdict.score,
                "decided_by": verdict.decided_by,
                "evidence": verdict.evidence,
                # У решения правил модели нет — и `model IS NULL` означает
                # ровно «это решение ничего не стоило».
                "model": model if verdict.decided_by == "model" else None,
            }
            for verdict in unique.values()
        ]

        async with self._session_factory() as session, session.begin():
            for start in range(0, len(rows), VERDICT_BATCH):
                chunk = rows[start : start + VERDICT_BATCH]
                statement = pg_insert(ResearchVerdict).values(chunk)
                await session.execute(
                    statement.on_conflict_do_update(
                        constraint="uq_research_verdict",
                        set_={
                            "confidence": statement.excluded.confidence,
                            "reason": statement.excluded.reason,
                            "score": statement.excluded.score,
                            "decided_by": statement.excluded.decided_by,
                            "evidence": statement.excluded.evidence,
                            "model": statement.excluded.model,
                        },
                    )
                )


def _period(
    regions: Sequence[str] | None,
    since: date | None,
    until: date | None,
    structural: Structural | None = None,
) -> list[Any]:
    """Условия отбора закупок — через общий модуль, а не своим набором.

    `libs/shared/db/tender_criteria.py` — единственный ответ на вопрос «какие
    закупки подходят». Второй набор предикатов уже заводился однажды и разошёлся
    с первым: префикс `20.11` находил `26.20.11.110`, и судья получал ноутбуки
    в кандидаты фильтра по газам.

    Регионы прогона **перекрывают** регионы критерия, а не объединяются с ними.
    Регионы критерия — умолчание, выбранные при запуске — воля пользователя:
    объединение молча расширило бы прогон за пределы запрошенного, и
    знаменатель воронки перестал бы соответствовать тому, что просили.
    """
    conditions = list(
        predicates(
            TenderCriteria(
                regions=tuple(regions or (structural.regions if structural else ())),
                customer_inns=tuple(structural.customer_inns if structural else ()),
                price_min=structural.price_min if structural else None,
                price_max=structural.price_max if structural else None,
                published_since=since,
                published_until=until,
                only_active=bool(structural and structural.only_active),
            )
        ).values()
    )
    return conditions or [True]


def _describe(criteria: Criteria) -> dict[str, Any]:
    """Критерий в виде, пригодном для хранения и объяснения задним числом.

    Скомпилированные регулярные выражения не сериализуются, да и незачем:
    храним их исходный текст — по нему видно, что именно искали.
    """
    return {
        "name": criteria.name,
        "version": criteria.version,
        "terms": [
            {"name": term.name, "role": str(term.role), "pattern": term.pattern.pattern}
            for term in criteria.terms
        ],
        "context_rules": [
            {
                "name": rule.name,
                "verdict": str(rule.verdict),
                "window": rule.window,
                "pattern": rule.pattern.pattern,
            }
            for rule in criteria.context_rules
        ],
        "okpd2_prefixes": list(criteria.okpd2_prefixes),
        "card_pattern": criteria.card_pattern.pattern if criteria.card_pattern else None,
        "quote_radius": criteria.quote_radius,
        "max_hits_per_document": criteria.max_hits_per_document,
    }


def criteria_json(criteria: Criteria) -> str:
    return json.dumps(_describe(criteria), ensure_ascii=False)


class SqlCriteriaRepository:
    """Критерий отбора из сохранённого фильтра.

    Спецификация лежит в `saved_filters.spec` — там же, где раньше жил
    `FilterSpec`. Формат другой (термины шаблонами, правила по контексту), и
    старые записи в него не превращаются: правила по контексту из списка
    ключевых слов не выводятся. Поэтому критерии заводятся заново.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, filter_id: int) -> Criteria | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(SavedFilter.name, SavedFilter.spec).where(
                        SavedFilter.id == filter_id
                    )
                )
            ).first()

        if row is None:
            return None

        spec = dict(row.spec or {})
        spec.setdefault("name", row.name)
        return criteria_from_spec(spec)

    async def mark_run(self, filter_id: int) -> None:
        """Отмечает, что по критерию прошёл настоящий прогон.

        Пробный прогон сюда не попадает: отметка отвечает на вопрос «есть ли по
        этому фильтру вердикты», а тест их не оставляет. Меню фильтров на
        каталоге показывает по ней «не запускался» — выбор такого фильтра даёт
        пустую выдачу, и сказать об этом до клика честнее, чем после.
        """
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(SavedFilter)
                .where(SavedFilter.id == filter_id)
                .values(last_run_at=func.now())
            )

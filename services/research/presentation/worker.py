"""Точка входа движка отбора: потребитель `research.requested`.

Прогон по корпусу занимает минуты, а то и часы, поэтому prefetch равен единице:
одно исследование за раз. Параллелизм внутри прогона задаётся уровнем нагрузки
и там же ограничен — умножать его ещё и числом одновременных заявок значило бы
потерять контроль над машиной.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

from libs.shared.config import (
    database_settings,
    llm_settings,
    minio_settings,
    rabbit_settings,
)
from libs.shared.contracts.events import Event, ResearchRequested
from libs.shared.load_policy import LoadBudget
from libs.shared.logging import configure_logging, get_logger, set_correlation_id
from libs.shared.messaging.consumer import EventConsumer
from libs.shared.messaging.topology import QueueSpec
from services.research.application.use_cases.judge_disputed import JudgeDisputedUseCase
from services.research.application.use_cases.scan_corpus import ScanCorpusUseCase
from services.research.bootstrap import ResearchContainer, build_container
from services.research.domain.criteria import CriteriaError
from services.research.infrastructure.repositories import SqlCorpusRepository

log = get_logger(__name__)

QUEUE = QueueSpec(
    name="research.requested",
    routing_keys=("research.requested",),
    prefetch=1,
)

DEFAULT_LLM_SERVICE_URL = "http://llm-service:8010"


async def run() -> None:
    configure_logging("research")

    async with build_container(
        database_settings(),
        rabbit_settings(),
        minio_settings(),
        llm_settings(),
        os.getenv("LLM_SERVICE_URL", DEFAULT_LLM_SERVICE_URL),
    ) as container:
        watcher_task = asyncio.create_task(container.load_watcher.run())

        consumer = EventConsumer(container.connection, QUEUE, idempotency=container.idempotency)
        consumer.on(ResearchRequested, _handler(container))
        await consumer.run()

        log.info(
            "research.ready",
            queue=QUEUE.name,
            level=int(container.controller.level),
        )
        try:
            await asyncio.Event().wait()
        finally:
            container.load_watcher.stop()
            watcher_task.cancel()


def _handler(container: ResearchContainer) -> Callable[[Event], Awaitable[None]]:
    async def handle(event: Event) -> None:
        assert isinstance(event, ResearchRequested)
        set_correlation_id(str(event.job_id))
        await execute(container, event)

    return handle


async def execute(container: ResearchContainer, event: ResearchRequested) -> None:
    """Один прогон: критерий → находки → вердикты.

    Задание переводится в `failed` при любом отказе. Молча вернуть управление
    нельзя: задание осталось бы в `running` навсегда, и на экране вечно шло бы
    «идёт прогон» — пользователь ждал бы результата, которого не будет.
    """
    job_id = str(event.job_id)
    budget: LoadBudget = container.controller.budget
    await container.jobs.start(job_id, "research", 0)

    try:
        criteria = await container.criteria.get(event.filter_id)
    except CriteriaError as exc:
        # Спецификация не складывается в критерий: искать «примерно то» хуже,
        # чем не искать вовсе — результат будет выглядеть настоящим.
        log.error("research.bad_criteria", filter_id=event.filter_id, error=str(exc))
        await container.jobs.fail(job_id, f"Критерий непригоден: {exc}")
        return

    if criteria is None:
        log.error("research.criteria_not_found", filter_id=event.filter_id)
        await container.jobs.fail(job_id, f"Критерий {event.filter_id} не найден")
        return

    run_id = await container.runs.start(
        criteria.name,
        criteria,
        event.regions or None,
        event.since,
        event.until,
    )

    try:
        await _run(container, event, criteria, run_id, job_id, budget)
    except Exception as exc:
        # Обещание докстринга держится здесь. Раньше обёрнут был только разбор
        # критерия, и падение в обходе корпуса или в судье оставляло и задание,
        # и прогон в `running` навсегда.
        log.exception("research.run_failed", run_id=run_id)
        await container.runs.fail(run_id, str(exc))
        await container.jobs.fail(job_id, str(exc))
        # Наверх — чтобы повторы и dead-letter работали как прежде.
        raise


#: Названия фаз прогона. Живут в `presentation`, потому что это подписи на
#: экране, а не понятия предметной области: `application` знает только числа.
PHASE_SCAN = "обход корпуса"
PHASE_JUDGE = "судья читает документы"


class _JobProgress:
    """Ход одной фазы → строка задания.

    Адаптер живёт здесь, в `presentation`: порт знает только про числа, а про
    таблицу заданий — инфраструктура.

    **Экземпляр на фазу.** Фаза — свойство адаптера, а не аргумент отчёта:
    иначе о ней пришлось бы знать порту, то есть слою, который сознательно не
    знает, куда идут числа.
    """

    def __init__(self, container: ResearchContainer, job_id: str, phase: str) -> None:
        self._container = container
        self._job_id = job_id
        self._phase = phase
        self._total: int | None = None

    async def report(self, processed: int, total: int) -> None:
        if total != self._total:
            # Общее число известно только после подсчёта корпуса. `start` —
            # вставка с обновлением, поэтому повторный вызов законен; он же
            # переводит задание в эту фазу и обнуляет счётчик предыдущей.
            self._total = total
            await self._container.jobs.start(self._job_id, "research", total, self._phase)
        await self._container.jobs.progress(self._job_id, processed)


async def _run(
    container: ResearchContainer,
    event: ResearchRequested,
    criteria,
    run_id: int,
    job_id: str,
    budget: LoadBudget,
) -> None:
    """Обход корпуса и разбор находок — то, что может упасть на середине."""
    # Корпус сужается структурными условиями критерия ещё до чтения текстов.
    corpus = SqlCorpusRepository(container.session_factory, criteria.structural)

    scan = ScanCorpusUseCase(
        criteria,
        corpus,
        container.texts,
        hits=container.hits,
        runs=container.runs,
        readers=budget.extraction_workers,
        progress=_JobProgress(container, job_id, PHASE_SCAN),
    )
    stats = await scan.execute(
        run_id=run_id,
        regions=event.regions or None,
        since=event.since,
        until=event.until,
    )

    judge = JudgeDisputedUseCase(
        criteria,
        container.judge,
        store=container.verdicts,
        concurrency=budget.llm_concurrency,
        # Пробный прогон считает воронку, но не оставляет вердиктов: отбор по
        # сохранённому фильтру ключуется версией критерия, а не прогоном, и
        # решения теста были бы неотличимы от настоящих.
        dry_run=event.dry_run,
        # Вторая фаза, и она же самая долгая. Пока её не было на шкале, полоса
        # доходила до конца обхода и стояла там минуты — то есть утверждала,
        # что прогон закончен, посреди работы судьи.
        progress=_JobProgress(container, job_id, PHASE_JUDGE),
    )
    outcome = await judge.execute(stats.candidates)

    if not event.dry_run:
        # Отметка о настоящем прогоне: по ней меню фильтров отличает критерий
        # с вердиктами от того, что даст пустую выдачу.
        await container.criteria.mark_run(event.filter_id)

    confirmed = sum(1 for v in outcome.verdicts if v.confidence.value == "confirmed")
    rejected = sum(1 for v in outcome.verdicts if v.confidence.value == "rejected")
    await container.runs.finish(
        run_id, confirmed, rejected, outcome.funnel.disputed
    )

    await container.jobs.finish(job_id, _result(run_id, stats, outcome, confirmed, rejected))

    log.info(
        "research.run_finished",
        run_id=run_id,
        tenders=stats.tenders_total,
        candidates=stats.tenders_candidate,
        hits=stats.hits_found,
        confirmed=confirmed,
        rejected=rejected,
        asked_model=outcome.funnel.asked_model,
        interrupted=outcome.interrupted,
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()


def _result(run_id: int, stats, outcome, confirmed: int, rejected: int) -> dict:
    """Итог прогона в том виде, в каком его читает экран.

    Воронка отдаётся ветвлением, а не лестницей: «принято правилами» не
    подмножество «отсеяно правилами», и рисовать их каскадом значило бы врать.
    `not_reached` и `documents_pending` — те самые знаменатели, без которых
    «находок нет» невозможно отличить от «ничего не читали».
    """
    funnel = outcome.funnel
    return {
        "run_id": run_id,
        "matched": [v.tender_id for v in outcome.verdicts if v.confidence.value == "confirmed"],
        "confirmed": confirmed,
        "rejected": rejected,
        "interrupted": outcome.interrupted,
        "funnel": {
            "tenders_total": stats.tenders_total,
            "tenders_candidate": stats.tenders_candidate,
            "documents_scanned": stats.documents_scanned,
            "documents_pending": stats.documents_pending,
            "hits_found": stats.hits_found,
            "reviewed": funnel.total,
            "rejected_by_rules": funnel.rejected_by_rules,
            "confirmed_by_rules": funnel.confirmed_by_rules,
            "disputed": funnel.disputed,
            "from_cache": funnel.from_cache,
            "asked_model": funnel.asked_model,
            "not_reached": funnel.not_reached,
            "failed": funnel.failed,
        },
    }

"""Точка входа краулера: разовый прогон или периодический демон."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import date, timedelta

from libs.shared.config import database_settings, eis_settings, rabbit_settings
from libs.shared.contracts.events import CrawlRequested, Event
from libs.shared.logging import configure_logging, get_logger, set_correlation_id
from libs.shared.messaging.consumer import EventConsumer
from libs.shared.messaging.topology import QueueSpec
from services.crawler.bootstrap import CrawlerContainer, build_container

log = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Выгрузка извещений из ЕИС")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Дата выгрузки YYYY-MM-DD (по умолчанию — вчера)",
    )
    parser.add_argument(
        "--region",
        action="append",
        default=None,
        help="Код региона; можно повторять. По умолчанию — из EIS_REGIONS",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=1,
        help="Догнать N последних дней за один прогон (по умолчанию 1)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Один прогон и выход (без периодического расписания)",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="Дозаказать период с этой даты (YYYY-MM-DD) и выйти",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        default=None,
        help="Конец периода дозаказа; по умолчанию — вчера",
    )
    return parser.parse_args(argv)


async def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging("crawler")

    db = database_settings()
    rabbit = rabbit_settings()
    eis = eis_settings()

    async with build_container(db, rabbit, eis) as container:
        if args.region:
            container.regions = args.region

        # Relay крутится рядом с выгрузкой: события из outbox уходят в брокер,
        # пока идёт следующий регион.
        relay_task = asyncio.create_task(container.relay.run())
        watcher_task = asyncio.create_task(container.load_watcher.run())

        if args.since:
            # Разовый дозаказ периода из командной строки — то же, что делает
            # заявка событием, только без брокера.
            try:
                await container.crawl_period().execute(
                    regions=args.region or container.regions,
                    date_from=args.since,
                    date_to=args.until or (date.today() - timedelta(days=1)),
                )
            finally:
                await _shutdown(container, relay_task, watcher_task)
            return

        consumer_task: asyncio.Task | None = None
        try:
            if not args.once:
                # Заявки на дозаказ приходят событием: связывать сервисы
                # вызовами нельзя, а период нужен исследованию, а не расписанию.
                consumer_task = asyncio.create_task(_listen_for_requests(container))

            await _crawl_days(container, args)

            if not args.once:
                await _schedule_loop(container, eis.crawl_interval_minutes, args.days_back)
        finally:
            if consumer_task is not None:
                consumer_task.cancel()
            await _shutdown(container, relay_task, watcher_task)


async def _shutdown(container: CrawlerContainer, *tasks: asyncio.Task) -> None:
    container.load_watcher.stop()
    container.relay.stop()
    for task in tasks:
        # Даём relay дослать то, что уже лежит в outbox.
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=30)


QUEUE = QueueSpec(
    name="crawler.crawl-requested",
    routing_keys=("crawl.requested",),
    prefetch=1,
)


async def _listen_for_requests(container: CrawlerContainer) -> None:
    """Потребитель заявок на дозаказ периода.

    Prefetch=1 намеренно: заявка на двести дней сама по себе разворачивается в
    сотни выгрузок, и параллелить ещё и заявки значило бы умножать нагрузку на
    ЕИС на величину, которой никто не управляет.
    """

    async def handle(event: Event) -> None:
        assert isinstance(event, CrawlRequested)
        if event.job_id is None:
            # Заявка без задания — докладывать некому.
            await _execute_request(container, event, progress=None)
            return

        job_id = str(event.job_id)
        progress = _JobProgress(container, job_id)
        try:
            outcome = await _execute_request(container, event, progress)
        except Exception as exc:
            # Ошибка обязана доехать до экрана — и всё равно уйти наверх,
            # к повторам и dead-letter.
            await container.jobs.fail(job_id, str(exc))
            raise
        await container.jobs.finish(
            job_id,
            {
                "requested": outcome.requested,
                "skipped": outcome.skipped,
                "fetched": outcome.fetched,
                "saved": outcome.saved,
                "failed": outcome.failed,
            },
        )

    consumer = EventConsumer(container.connection, QUEUE)
    consumer.on(CrawlRequested, handle)
    await consumer.run()
    log.info("crawler.listening", queue=QUEUE.name)
    await asyncio.Event().wait()


#: Единственная фаза выгрузки. Названа всё равно: на экране рядом идут прогоны
#: с двумя фазами, и безымянная строка выглядела бы недосказанной.
PHASE_FETCH = "выгрузка дней по регионам"


class _JobProgress:
    """Ход выгрузки → строка задания.

    Адаптер живёт в `presentation`: порт знает только про числа, про таблицу
    заданий знает инфраструктура, а имя фазы — это подпись на экране.
    """

    def __init__(self, container: CrawlerContainer, job_id: str) -> None:
        self._container = container
        self._job_id = job_id
        self._total: int | None = None

    async def report(self, processed: int, total: int) -> None:
        if total != self._total:
            # Общее число известно только после сверки с журналом покрытия.
            # `start` — вставка с обновлением, повторный вызов законен.
            self._total = total
            await self._container.jobs.start(self._job_id, total, PHASE_FETCH)
        await self._container.jobs.progress(self._job_id, processed)


async def _execute_request(
    container: CrawlerContainer, event: CrawlRequested, progress: _JobProgress | None
):
    return await container.crawl_period(progress).execute(
        regions=event.regions or container.regions,
        date_from=event.date_from,
        date_to=event.date_to,
        document_types=event.document_types or None,
    )


def _window(args: argparse.Namespace) -> tuple[date, date]:
    """Окно дневного прохода: `days_back` последних дней, кончая целевым.

    Целевой день — вчерашний: ЕИС отдаёт выгрузку за завершившийся день.
    """
    base = args.date or (date.today() - timedelta(days=1))
    return base - timedelta(days=max(args.days_back, 1) - 1), base


async def _crawl_days(container: CrawlerContainer, args: argparse.Namespace) -> None:
    """Дневной проход — тем же сценарием, что и дозаказ периода.

    Своего сценария у расписания больше нет. Прежний обходил регионы
    последовательно и в одной транзакции на все: на восьмидесяти пяти субъектах
    транзакция висела бы весь обход, а события копились бы в outbox до коммита.
    Заодно проход стал идемпотентным — перезапуск контейнера не перекачивает
    уже выгруженное.
    """
    set_correlation_id()
    date_from, date_to = _window(args)
    outcome = await container.crawl_period().execute(
        regions=container.regions, date_from=date_from, date_to=date_to
    )
    log.info(
        "crawl.window_done",
        since=date_from.isoformat(),
        until=date_to.isoformat(),
        requested=outcome.requested,
        skipped=outcome.skipped,
        fetched=outcome.fetched,
        saved=outcome.saved,
        failed=outcome.failed,
    )


async def _schedule_loop(
    container: CrawlerContainer, interval_minutes: int, days_back: int
) -> None:
    """Периодический прогон вместо библиотеки `schedule` с busy-wait раз в 30 секунд."""
    interval = max(interval_minutes, 1) * 60
    while True:
        await asyncio.sleep(interval)
        args = argparse.Namespace(date=None, days_back=days_back)
        try:
            await _crawl_days(container, args)
        except Exception as exc:
            # Демон не должен умирать из-за одной неудачной выгрузки.
            log.error("crawl.cycle_failed", error=str(exc), exc_info=True)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

"""Точка входа краулера: разовый прогон или периодический демон."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import date, timedelta

from libs.shared.config import database_settings, eis_settings, rabbit_settings
from libs.shared.contracts.events import CrawlRequested, Event
from libs.shared.db.base import transaction
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
        await container.crawl_period().execute(
            regions=event.regions or container.regions,
            date_from=event.date_from,
            date_to=event.date_to,
            document_types=event.document_types or None,
        )

    consumer = EventConsumer(container.connection, QUEUE)
    consumer.on(CrawlRequested, handle)
    await consumer.run()
    log.info("crawler.listening", queue=QUEUE.name)
    await asyncio.Event().wait()


async def _crawl_days(container: CrawlerContainer, args: argparse.Namespace) -> None:
    base = args.date or (date.today() - timedelta(days=1))
    days = [base - timedelta(days=offset) for offset in range(max(args.days_back, 1))]

    for day in days:
        set_correlation_id()
        async with transaction(container.session_factory) as session:
            results = await container.crawl_all(session).execute(day)
        log.info(
            "crawl.day_done",
            day=day.isoformat(),
            fetched=sum(r.fetched for r in results),
            saved=sum(r.saved for r in results),
            new=sum(r.new for r in results),
            failed=sum(1 for r in results if r.status == "failed"),
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

"""Описание очереди: имена, лестница повторов, потолок попыток.

Лестница переехала из глобальной константы в `QueueSpec`, потому что
объявляется она per-queue — через `x-message-ttl` каждой retry-очереди.
Побочная выгода видна в интеграционных тестах: короткая лестница вместо
настоящей вернула 20 секунд из 36.
"""

from __future__ import annotations

from itertools import pairwise

from libs.shared.messaging.topology import RETRY_DELAYS_MS, QueueSpec

SPEC = QueueSpec(name="docs.ingested", routing_keys=("tender.ingested",))


class TestNames:
    def test_retry_queues_are_numbered_from_zero(self) -> None:
        assert SPEC.retry_queue(0) == "docs.ingested.retry.0"
        assert SPEC.retry_queue(4) == "docs.ingested.retry.4"

    def test_dead_queue_hangs_off_the_name(self) -> None:
        assert SPEC.dead_queue == "docs.ingested.dead"


class TestTheLadder:
    def test_default_is_the_production_ladder(self) -> None:
        """Умолчание обязано остаться прежним: 5с → 30с → 2мин → 10мин → 1ч."""
        assert SPEC.retry_delays_ms == RETRY_DELAYS_MS
        assert SPEC.retry_delays_ms == (5_000, 30_000, 120_000, 600_000, 3_600_000)

    def test_ladder_grows(self) -> None:
        """Смысл лестницы в нарастании: ровные задержки — это не отступление."""
        delays = SPEC.retry_delays_ms
        assert all(a < b for a, b in pairwise(delays))

    def test_attempts_follow_the_ladder(self) -> None:
        assert SPEC.max_attempts == len(RETRY_DELAYS_MS)

    def test_a_shorter_ladder_shortens_the_ceiling(self) -> None:
        """Потолок попыток считается по лестнице, а не по глобальной константе.

        Иначе короткая лестница в тестах дала бы обращение к несуществующей
        retry-очереди — вместо dead-letter сообщение потерялось бы молча.
        """
        fast = QueueSpec(
            name="test.fast", routing_keys=("tender.ingested",), retry_delays_ms=(10, 20)
        )

        assert fast.max_attempts == 2
        assert fast.retry_queue(1) == "test.fast.retry.1"

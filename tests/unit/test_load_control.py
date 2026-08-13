"""Смена уровня нагрузки на работающем сервисе."""

from __future__ import annotations

import asyncio

import pytest

from libs.shared.load_control import AdjustableSemaphore, LoadController
from libs.shared.load_policy import LoadLevel, resolve


def budget(level: LoadLevel) -> object:
    return resolve(level, cpu_count=8, memory_mb=None)


class TestAdjustableSemaphore:
    async def test_limits_concurrency_to_capacity(self) -> None:
        semaphore = AdjustableSemaphore(2)
        running = 0
        peak = 0

        async def task() -> None:
            nonlocal running, peak
            async with semaphore:
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.01)
                running -= 1

        await asyncio.gather(*(task() for _ in range(8)))
        assert peak == 2

    async def test_growing_capacity_wakes_more_than_one_waiter(self) -> None:
        """После расширения пройти должен не один ожидающий, а все влезающие."""
        semaphore = AdjustableSemaphore(1)
        await semaphore.acquire()

        waiters = [asyncio.create_task(semaphore.acquire()) for _ in range(3)]
        await asyncio.sleep(0.01)
        assert all(not task.done() for task in waiters)

        await semaphore.resize(4)
        await semaphore.release()
        await asyncio.wait_for(asyncio.gather(*waiters), timeout=1)
        assert semaphore.in_use == 3

    async def test_shrinking_does_not_preempt_current_holders(self) -> None:
        """Прервать работу на середине хуже, чем доработать на старом потолке."""
        semaphore = AdjustableSemaphore(4)
        for _ in range(4):
            await semaphore.acquire()

        await semaphore.resize(1)
        assert semaphore.capacity == 1
        # Четверо держат разрешения при ёмкости в одно — допустимое состояние.
        assert semaphore.in_use == 4

        blocked = asyncio.create_task(semaphore.acquire())
        await asyncio.sleep(0.01)
        assert not blocked.done()

        # Освобождения возвращают систему к новому потолку, а не к старому.
        for _ in range(4):
            await semaphore.release()
        await asyncio.wait_for(blocked, timeout=1)
        assert semaphore.in_use == 1

    async def test_capacity_never_drops_below_one(self) -> None:
        """Ноль означал бы остановку навсегда, а не фоновый режим."""
        semaphore = AdjustableSemaphore(0)
        assert semaphore.capacity == 1
        await semaphore.resize(-5)
        assert semaphore.capacity == 1

    async def test_release_without_acquire_does_not_go_negative(self) -> None:
        semaphore = AdjustableSemaphore(2)
        await semaphore.release()
        assert semaphore.in_use == 0

    async def test_context_manager_releases_on_error(self) -> None:
        semaphore = AdjustableSemaphore(1)
        with pytest.raises(RuntimeError):
            async with semaphore:
                raise RuntimeError("сбой внутри критической секции")
        assert semaphore.in_use == 0


class TestLoadController:
    async def test_notifies_every_subscriber(self) -> None:
        controller = LoadController(budget(LoadLevel.BALANCED))
        seen: list[int] = []

        async def listener(new) -> None:
            seen.append(int(new.level))

        controller.subscribe(listener)
        controller.subscribe(listener)
        await controller.apply(budget(LoadLevel.FULL))

        assert seen == [3, 3]
        assert controller.level == LoadLevel.FULL

    async def test_a_failing_subscriber_does_not_block_the_others(self) -> None:
        """Половина системы на новом уровне лучше, чем прерванная смена."""
        controller = LoadController(budget(LoadLevel.BALANCED))
        reached: list[str] = []

        async def broken(_new) -> None:
            raise RuntimeError("канал закрыт")

        async def healthy(_new) -> None:
            reached.append("ok")

        controller.subscribe(broken)
        controller.subscribe(healthy)
        await controller.apply(budget(LoadLevel.BACKGROUND))

        assert reached == ["ok"]
        assert controller.level == LoadLevel.BACKGROUND

    async def test_budget_is_visible_before_any_change(self) -> None:
        controller = LoadController(budget(LoadLevel.BACKGROUND))
        assert controller.budget.extraction_workers == 1

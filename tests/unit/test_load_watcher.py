"""Сверка сервиса с записанным уровнем нагрузки."""

from __future__ import annotations

import asyncio

from libs.shared.load_control import LoadController
from libs.shared.load_policy import LoadLevel, resolve
from libs.shared.load_store import LoadLevelWatcher


class FakeStore:
    def __init__(self, level: LoadLevel) -> None:
        self.level = level
        self.reads = 0
        self.fail_next = False

    async def get(self) -> LoadLevel:
        self.reads += 1
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("база недоступна")
        return self.level

    async def set(self, level: LoadLevel) -> None:
        self.level = level


def controller(level: LoadLevel) -> LoadController:
    return LoadController(resolve(level, cpu_count=8, memory_mb=None))


class TestSync:
    async def test_applies_a_changed_level(self) -> None:
        store = FakeStore(LoadLevel.FULL)
        current = controller(LoadLevel.BALANCED)
        watcher = LoadLevelWatcher(store, current)

        assert await watcher.sync_once() is True
        assert current.level == LoadLevel.FULL

    async def test_does_nothing_when_the_level_matches(self) -> None:
        """Совпадение не должно дёргать подписчиков: пул пересобирается зря."""
        store = FakeStore(LoadLevel.BALANCED)
        current = controller(LoadLevel.BALANCED)
        applied: list[int] = []
        current.subscribe(lambda budget: _record(applied, budget))

        watcher = LoadLevelWatcher(store, current)
        assert await watcher.sync_once() is False
        assert applied == []

    async def test_recomputes_the_budget_for_this_machine(self) -> None:
        store = FakeStore(LoadLevel.BACKGROUND)
        current = controller(LoadLevel.FULL)
        await LoadLevelWatcher(store, current).sync_once()
        assert current.budget.extraction_workers == 1


class TestResilience:
    async def test_a_failed_poll_keeps_the_last_known_level(self) -> None:
        """Потеря связи с настройкой не имеет права уронить воркер."""
        store = FakeStore(LoadLevel.BALANCED)
        store.fail_next = True
        current = controller(LoadLevel.FULL)

        watcher = LoadLevelWatcher(store, current, poll_seconds=0.01)
        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.05)
        watcher.stop()
        await asyncio.wait_for(task, timeout=1)

        # Первый опрос упал, последующие прошли — уровень догнал настройку.
        assert store.reads >= 2
        assert current.level == LoadLevel.BALANCED

    async def test_stop_ends_the_loop_promptly(self) -> None:
        """Опрос не должен задерживать остановку сервиса на целый интервал."""
        store = FakeStore(LoadLevel.BALANCED)
        watcher = LoadLevelWatcher(store, controller(LoadLevel.BALANCED), poll_seconds=30)

        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.01)
        watcher.stop()
        await asyncio.wait_for(task, timeout=1)

    async def test_keeps_polling_until_stopped(self) -> None:
        store = FakeStore(LoadLevel.BALANCED)
        watcher = LoadLevelWatcher(store, controller(LoadLevel.BALANCED), poll_seconds=0.01)

        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.06)
        watcher.stop()
        await asyncio.wait_for(task, timeout=1)
        assert store.reads >= 3


async def _record(sink: list[int], budget) -> None:
    sink.append(int(budget.level))

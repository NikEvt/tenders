"""Применение уровня нагрузки на работающем сервисе.

[`load_policy`](load_policy.py) отвечает на вопрос «какие потолки», этот модуль —
на вопрос «как их сменить, не перезапуская процесс».

Смена уровня обязана быть безболезненной: пользователь садится за тяжёлый софт и
переводит систему на фоновый уровень, ожидая, что она подвинется, а не упадёт.
Поэтому уже начатая работа доводится до конца, а новые потолки действуют со
следующей задачи.

Не всё меняется одинаково легко:

* **семафор** — сужается сразу, но не отбирает уже выданные разрешения;
* **prefetch** — `basic.qos` на живом канале, применяется к следующей выдаче;
* **пул процессов** — пересобирается целиком, поэтому только на границе задач
  (тот же механизм, что и восстановление после `BrokenProcessPool`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import TracebackType

from libs.shared.load_policy import LoadBudget, LoadLevel, resolve_current
from libs.shared.logging import get_logger

log = get_logger(__name__)

#: Ключ уровня в `app_settings`.
#:
#: Живёт здесь, а не рядом с SQL-хранилищем: ключ нужен и сценариям шлюза, а
#: тянуть ради строковой константы SQLAlchemy в слой `application` — значит
#: протащить инфраструктуру туда, где её быть не должно.
LOAD_LEVEL_KEY = "system.load_level"

#: Подписчик на смену уровня. Возвращает awaitable, потому что применение
#: потолка почти всегда — обращение к брокеру или пересборка пула.
Listener = Callable[[LoadBudget], Awaitable[None]]


class AdjustableSemaphore:
    """Семафор, ёмкость которого меняется на ходу.

    `asyncio.Semaphore` создаётся с фиксированным значением, и уменьшить его
    можно только выдумками вроде «захватить лишние разрешения навсегда». Здесь
    ёмкость — обычное поле, а ожидание описано через `Condition`.

    Сужение не отбирает уже выданные разрешения: прервать работу на середине
    хуже, чем доработать её на старом потолке. Поэтому после уменьшения ёмкости
    число занятых какое-то время может превышать её — это допустимое состояние,
    а не ошибка.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = max(int(capacity), 1)
        self._in_use = 0
        self._condition = asyncio.Condition()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def in_use(self) -> int:
        return self._in_use

    async def acquire(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._in_use < self._capacity)
            self._in_use += 1

    async def release(self) -> None:
        async with self._condition:
            self._in_use = max(self._in_use - 1, 0)
            # Будим всех: после расширения ёмкости пройти должен не один
            # ожидающий, а столько, сколько поместится.
            self._condition.notify_all()

    async def resize(self, capacity: int) -> None:
        async with self._condition:
            self._capacity = max(int(capacity), 1)
            self._condition.notify_all()

    async def __aenter__(self) -> AdjustableSemaphore:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()


class LoadController:
    """Текущий уровень нагрузки сервиса и подписчики на его смену.

    Information Expert: знает уровень и кого о нём уведомлять, но ничего не знает
    о том, что подписчики с ним делают. Пул, канал и семафор подписываются сами.
    """

    def __init__(self, budget: LoadBudget | None = None) -> None:
        self._budget = budget or resolve_current()
        self._listeners: list[Listener] = []
        self._lock = asyncio.Lock()

    @property
    def budget(self) -> LoadBudget:
        return self._budget

    @property
    def level(self) -> LoadLevel:
        return self._budget.level

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    async def apply(self, budget: LoadBudget) -> None:
        """Ставит новый бюджет и уведомляет подписчиков.

        Сбой одного подписчика не отменяет смену уровня для остальных: половина
        системы на новом уровне — состояние рабочее, а прерванная смена оставила
        бы её в состоянии, которого никто не заказывал.
        """
        async with self._lock:
            previous, self._budget = self._budget, budget
            log.info(
                "load.level_changed",
                previous=int(previous.level),
                level=int(budget.level),
                extraction_workers=budget.extraction_workers,
                docs_prefetch=budget.docs_prefetch,
                llm_concurrency=budget.llm_concurrency,
            )
            for listener in self._listeners:
                try:
                    await listener(budget)
                except Exception as exc:
                    log.warning(
                        "load.listener_failed",
                        listener=getattr(listener, "__qualname__", repr(listener)),
                        error=str(exc),
                    )

"""Где хранится уровень нагрузки и как сервисы о нём узнают.

Уровень лежит в `app_settings` — той же таблице, куда шлюз пишет отметку о
ротации токена. Сервисы **опрашивают** её, а не подписываются на событие.

Опрос вместо рассылки выбран сознательно:

* сервис, лежавший в момент переключения, событие бы пропустил и остался на
  старом уровне до перезапуска — то есть подписку всё равно пришлось бы
  дополнять чтением при старте, и механизмов стало бы два;
* шлюзу не нужно уметь публиковать в брокер: сегодня он ходит в RabbitMQ только
  за статистикой очередей по HTTP, и заводить ради одной настройки AMQP-
  соединение с собственным жизненным циклом — плохой обмен;
* задержка опроса измеряется секундами, а сценарий у переключения человеческий
  («сажусь за тяжёлый софт»), и секунды в нём ничего не решают.

Цена — регулярный SELECT по первичному ключу с каждого воркера. На фоне
разбора документов это шум.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import AppSetting
from libs.shared.load_control import LOAD_LEVEL_KEY, LoadController
from libs.shared.load_policy import LoadLevel, resolve_current
from libs.shared.logging import get_logger

log = get_logger(__name__)

#: Как часто воркер сверяется с настройкой.
DEFAULT_POLL_SECONDS = 15.0


class LoadLevelStore(Protocol):
    """Чтение и запись уровня. Протокол — чтобы подменять в тестах без БД."""

    async def get(self) -> LoadLevel: ...

    async def set(self, level: LoadLevel) -> None: ...


class SqlLoadLevelStore:
    """Уровень в `app_settings`. Отсутствие записи — это средний уровень."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self) -> LoadLevel:
        async with self._session_factory() as session:
            stored = await session.scalar(
                select(AppSetting.value).where(AppSetting.key == LOAD_LEVEL_KEY)
            )
        return LoadLevel.parse(stored.get("level") if isinstance(stored, dict) else None)

    async def set(self, level: LoadLevel) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(AppSetting).values(
                key=LOAD_LEVEL_KEY, value={"level": int(level)}
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[AppSetting.key],
                    set_={"value": statement.excluded.value},
                )
            )


class LoadLevelWatcher:
    """Держит контроллер в согласии с тем, что записано в настройке.

    Собственных решений не принимает: только замечает расхождение и передаёт
    новый бюджет контроллеру. Сбой опроса не имеет права уронить сервис —
    воркер, потерявший связь с настройкой, обязан продолжать работать на
    последнем известном уровне.
    """

    def __init__(
        self,
        store: LoadLevelStore,
        controller: LoadController,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._store = store
        self._controller = controller
        self._poll_seconds = poll_seconds
        self._stopped = asyncio.Event()

    async def sync_once(self) -> bool:
        """Сверяется с настройкой. Возвращает True, если уровень сменился."""
        level = await self._store.get()
        if level == self._controller.level:
            return False
        await self._controller.apply(resolve_current(level))
        return True

    async def run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.sync_once()
            except Exception as exc:
                # Настройка недоступна — работаем на последнем известном уровне.
                log.warning("load.poll_failed", error=str(exc))
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stopped.set()

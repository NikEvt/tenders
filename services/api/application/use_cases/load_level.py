"""Чтение и смена уровня нагрузки на машину.

Шлюз здесь — единственный писатель: `app_settings` не имеет других, поэтому
правило «один агрегат — один писатель» соблюдено. Воркеры настройку только
читают, каждый в своём темпе.

Смена уровня ничего не применяет прямо здесь и не ждёт, пока применят воркеры:
запись в настройку — это заявка, а не команда. Ответ описывает потолки, которые
получатся **на машине шлюза**; у воркера с другим лимитом памяти числа могут
отличаться, и выдавать их за общие было бы неправдой.
"""

from __future__ import annotations

from libs.shared.load_control import LOAD_LEVEL_KEY
from libs.shared.load_policy import LoadBudget, LoadLevel, resolve_current
from services.api.application.ports.monitoring import AppStatePort


class ReadLoadLevelUseCase:
    def __init__(self, state: AppStatePort) -> None:
        self._state = state

    async def execute(self) -> LoadBudget:
        stored = await self._state.get(LOAD_LEVEL_KEY)
        raw = stored.get("level") if isinstance(stored, dict) else None
        return resolve_current(LoadLevel.parse(raw))


class SetLoadLevelUseCase:
    """Записывает уровень; воркеры подхватят его при следующей сверке."""

    def __init__(self, state: AppStatePort) -> None:
        self._state = state

    async def execute(self, level: LoadLevel) -> LoadBudget:
        await self._state.set(LOAD_LEVEL_KEY, {"level": int(level)})
        return resolve_current(level)

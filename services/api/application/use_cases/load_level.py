"""Чтение и смена уровня нагрузки на машину.

Шлюз здесь — единственный писатель: `app_settings` не имеет других, поэтому
правило «один агрегат — один писатель» соблюдено. Воркеры настройку только
читают, каждый в своём темпе.

Смена уровня ничего не применяет прямо здесь и не ждёт, пока применят воркеры:
запись в настройку — это заявка, а не команда.

Потолки в ответе считаются по числу ядер, но **без** поправки на память: пул
разборщиков живёт в docs-worker, у которого свой лимит, а у шлюза он намеренно
тесный (448 МиБ). Считая по памяти шлюза, ответ отдавал один разборщик на всех
трёх уровнях — переключатель выглядел ни на что не влияющим, хотя воркер честно
поднимал пять. Поправку на память накладывает тот, кто разбирает.
"""

from __future__ import annotations

from libs.shared.load_control import LOAD_LEVEL_KEY
from libs.shared.load_policy import LoadBudget, LoadLevel, detect_cpu_count, resolve
from services.api.application.ports.monitoring import AppStatePort


class ReadLoadLevelUseCase:
    def __init__(self, state: AppStatePort) -> None:
        self._state = state

    async def execute(self) -> LoadBudget:
        stored = await self._state.get(LOAD_LEVEL_KEY)
        raw = stored.get("level") if isinstance(stored, dict) else None
        return resolve(LoadLevel.parse(raw), cpu_count=detect_cpu_count())


class SetLoadLevelUseCase:
    """Записывает уровень; воркеры подхватят его при следующей сверке."""

    def __init__(self, state: AppStatePort) -> None:
        self._state = state

    async def execute(self, level: LoadLevel) -> LoadBudget:
        await self._state.set(LOAD_LEVEL_KEY, {"level": int(level)})
        return resolve(level, cpu_count=detect_cpu_count())

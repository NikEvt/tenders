"""Порты LLM-сервиса."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import TypeVar

from pydantic import BaseModel

from libs.shared.contracts.criteria_spec import CriteriaSpec
from services.llm_service.domain.models import (
    DigestInput,
    FilterPatch,
    SavedFilterView,
    Verdict,
)

T = TypeVar("T", bound=BaseModel)


class LlmUnavailable(RuntimeError):
    """Модель недоступна. Система обязана деградировать, а не падать."""


class LlmPort(ABC):
    """Узкий интерфейс к языковой модели (ISP): свободный текст и структурный вывод.

    `reasoning_effort` — необязательный уровень рассуждений для reasoning-моделей.
    По умолчанию берётся из настроек; переопределяют его только там, где качество
    рассуждения окупает токены (LLM-судья).
    """

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
        reasoning_effort: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def structured(
        self,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 2000,
        reasoning_effort: str | None = None,
    ) -> T: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...


class FilterRepositoryPort(ABC):
    @abstractmethod
    async def get_spec(self, filter_id: int) -> CriteriaSpec | None: ...

    @abstractmethod
    async def save_compiled(
        self, name: str, nl_query: str, spec: CriteriaSpec
    ) -> int: ...

    @abstractmethod
    async def active_filters(self) -> list[tuple[int, CriteriaSpec]]: ...

    # ── Управление фильтрами ─────────────────────────────────────────────────
    # Запись живёт здесь, а не в шлюзе: согласованность `nl_query ↔ spec ↔
    # llm_criteria` держит компиляция, и второй писатель в ту же таблицу дал бы
    # две точки истины на один агрегат.

    @abstractmethod
    async def list_filters(self) -> list[SavedFilterView]: ...

    @abstractmethod
    async def get_filter(self, filter_id: int) -> SavedFilterView | None: ...

    @abstractmethod
    async def save_spec(self, name: str, nl_query: str, spec: CriteriaSpec) -> int:
        """Сохраняет уже готовую спецификацию, не перекомпилируя текст."""

    @abstractmethod
    async def update_filter(self, filter_id: int, patch: FilterPatch) -> SavedFilterView | None: ...

    @abstractmethod
    async def delete_filter(self, filter_id: int) -> bool: ...

    @abstractmethod
    async def cached_verdict_tender_ids(
        self, filter_id: int, prompt_version: str
    ) -> set[int]: ...

    @abstractmethod
    async def save_verdict(
        self,
        tender_id: int,
        filter_id: int,
        verdict: Verdict,
        model: str,
        prompt_version: str,
    ) -> None: ...


class DigestRepositoryPort(ABC):
    @abstractmethod
    async def collect(self, digest_date: date) -> DigestInput:
        """Материал за день — по фильтрам, включённым в сводку.

        Отбор идёт по тем же предикатам, что и каталог
        (`libs/shared/db/tender_criteria.py`): второй реализации у правила
        отбора быть не должно.
        """

    @abstractmethod
    async def save(
        self,
        digest_date: date,
        summary_md: str,
        sections: dict,
        tender_count: int,
        model: str,
        prompt_version: str,
    ) -> None: ...

    @abstractmethod
    async def built_at(self, digest_date: date) -> datetime | None:
        """Когда сводка за этот день была собрана. `None` — её ещё нет.

        Не `exists`: важен не факт наличия, а **когда** её собрали. Сводка,
        собранная в середине того же дня, описывает половину дня, и считать её
        готовой нельзя. Прежний `exists` этой разницы не знал, поэтому сводка
        за 13 августа навсегда осталась с четырьмястами закупками из 4878.
        """


class JobTrackerPort(ABC):
    """Статус длительной операции, запущенной через API."""

    @abstractmethod
    async def start(
        self, job_id: str, kind: str, total: int, phase: str | None = None
    ) -> None:
        """Начинает задание или переводит его в следующую фазу.

        Повторный вызов законен и обнуляет `processed`: у новой фазы свой
        знаменатель, и продолжать счёт предыдущей значило бы врать шкалой.
        """

    @abstractmethod
    async def progress(self, job_id: str, processed: int) -> None: ...

    @abstractmethod
    async def finish(self, job_id: str, result: dict) -> None: ...

    @abstractmethod
    async def fail(self, job_id: str, error: str) -> None: ...

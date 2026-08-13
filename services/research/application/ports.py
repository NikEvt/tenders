"""Порты движка отбора."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date

from services.research.domain.criteria import Confidence, Criteria
from services.research.domain.hits import Hit
from services.research.domain.verdict import ModelVerdict


class ModelUnavailable(Exception):
    """Модель недоступна.

    Отдельно от прочих ошибок: сбой на одной закупке — это её свойство, а
    лежащая модель означает, что продолжать бессмысленно. Прогон обязан
    остановиться, а не сжечь очередь ошибками.
    """


@dataclass(slots=True)
class TenderCandidate:
    """Закупка с находками — то, по чему принимается решение."""

    tender_id: int
    reg_num: str
    name: str | None = None
    description: str | None = None
    customer_name: str | None = None
    okpd2_code: str | None = None
    hits: list[Hit] = field(default_factory=list)


@dataclass(slots=True)
class TenderVerdict:
    """Итоговое решение по закупке, откуда бы оно ни пришло."""

    tender_id: int
    confidence: Confidence
    reason: str
    score: float = 0.0
    #: Кем решено: правилами по контексту или моделью. Нужно и для отчёта, и
    #: для того, чтобы понимать, во что обошёлся прогон.
    decided_by: str = "rules"
    evidence: list[dict[str, object]] = field(default_factory=list)


class ModelJudgePort(ABC):
    """Обращение к модели-судье."""

    @abstractmethod
    async def judge(self, system: str, user: str) -> ModelVerdict: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...


class VerdictCachePort(ABC):
    """Кэш решений модели.

    Ключ — закупка вместе с версиями критериев и промпта: правка любой из них
    обязана обесценить прежние решения, а не смешаться с ними.
    """

    @abstractmethod
    async def cached(
        self, tender_ids: Sequence[int], criteria_version: str, prompt_version: str
    ) -> dict[int, TenderVerdict]: ...

    @abstractmethod
    async def save(
        self,
        verdict: TenderVerdict,
        criteria_version: str,
        prompt_version: str,
        model: str,
    ) -> None: ...


@dataclass(slots=True)
class CorpusTender:
    """Карточка закупки глазами движка — ровно то, что нужно предфильтру."""

    tender_id: int
    reg_num: str
    name: str | None = None
    description: str | None = None
    customer_name: str | None = None
    okpd2_code: str | None = None
    okpd2_codes: tuple[str, ...] = ()
    okpd2_names: tuple[str, ...] = ()


@dataclass(slots=True)
class CorpusDocument:
    """Документ, из которого есть что читать."""

    document_id: int
    text_key: str | None
    file_name: str | None = None


@dataclass(slots=True)
class ScanStats:
    """Воронка прохода. Знаменатели обязательны.

    `documents_pending` — то, до чего не дошли. Без этого числа «в этом
    приоритете находок нет» неотличимо от «в этом приоритете ничего не читали»,
    и вывод об отсутствии находок ничего не стоит.
    """

    tenders_total: int = 0
    tenders_candidate: int = 0
    documents_scanned: int = 0
    documents_pending: int = 0
    documents_unreadable: int = 0
    hits_found: int = 0
    tenders_with_hits: int = 0
    candidates: list[TenderCandidate] = field(default_factory=list)


class CorpusPort(ABC):
    """Чтение накопленного корпуса закупок и документов."""

    @abstractmethod
    def tenders(
        self, regions: Sequence[str] | None, since: date | None, until: date | None
    ) -> AsyncIterator[CorpusTender]:
        """Поток карточек. Именно поток: корпус не помещается в память."""

    @abstractmethod
    async def documents(self, tender_id: int) -> list[CorpusDocument]: ...

    @abstractmethod
    async def count_tenders(
        self, regions: Sequence[str] | None, since: date | None, until: date | None
    ) -> int: ...

    @abstractmethod
    async def count_unscanned(
        self, regions: Sequence[str] | None, since: date | None, until: date | None
    ) -> int:
        """Сколько документов ещё не разобрано — знаменатель воронки.

        Без него «находок нет» неотличимо от «ничего не читали».
        """


class TextStoragePort(ABC):
    """Чтение извлечённого текста из объектного хранилища."""

    @abstractmethod
    async def read(self, text_key: str) -> str: ...


class HitRepositoryPort(ABC):
    @abstractmethod
    async def save(self, run_id: int, tender_id: int, hits: Sequence[Hit]) -> None: ...


class ResearchRunPort(ABC):
    @abstractmethod
    async def start(
        self,
        name: str,
        criteria: Criteria,
        regions: Sequence[str] | None,
        since: date | None,
        until: date | None,
    ) -> int: ...

    @abstractmethod
    async def update_funnel(self, run_id: int, stats: ScanStats) -> None: ...

    @abstractmethod
    async def finish(
        self, run_id: int, confirmed: int, rejected: int, disputed: int
    ) -> None: ...

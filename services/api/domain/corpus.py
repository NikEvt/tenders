"""Состав накопленного корпуса — то, что показывает вкладка «Данные».

Раздел отвечает на вопрос «с чем я работаю», а не «что сломалось»: последний
живёт в мониторинге, и числа оттуда сюда не переезжают, а переиспользуются
через те же порты. Две реализации одного счётчика однажды уже разошлись
(см. `libs/shared/db/tender_criteria.py`), и повторять это незачем.

**Знаменатель обязателен.** Каждая величина здесь либо сама является
знаменателем, либо стоит рядом со своим: «в топе 40 тыс.» без «всего 900 тыс.»
читается как весь корпус.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(slots=True)
class DayBucket:
    """Один день на гистограмме публикаций.

    `crawled` отличает «в этот день ничего не публиковали» от «этот день мы не
    выгружали». Без него дыра в покрытии выглядела бы утверждением о рынке —
    та же ошибка, из-за которой в воронке отбора обязателен знаменатель.
    """

    day: date
    count: int
    crawled: bool


@dataclass(slots=True)
class Slice:
    """Доля одного значения в разрезе: регион, ОКПД2."""

    key: str
    label: str
    count: int


@dataclass(slots=True)
class Distribution:
    """Топ значений плюс хвост.

    `others` и `total` не украшение: сумма показанного плюс хвост обязана
    равняться итогу, иначе двенадцать столбиков читаются как весь корпус.
    """

    top: list[Slice] = field(default_factory=list)
    others: int = 0
    total: int = 0
    #: Сколько закупок вообще не несут этого признака. У ОКПД2 такие есть.
    unknown: int = 0


@dataclass(slots=True)
class CorpusOverview:
    """Состав корпуса за выбранный период.

    Период один на все разрезы. Так дешевле, но главное — честнее: «топ
    регионов за всё время» рядом со столбиками за 90 дней читались бы как один
    разрез, хотя описывают разные множества.
    """

    since: date
    until: date
    #: Закупок за период — знаменатель для всех разрезов ниже.
    total: int
    #: Закупок в базе вообще. Показывает, какую часть корпуса видно на экране.
    total_all_time: int
    earliest: date | None
    latest: date | None
    by_day: list[DayBucket] = field(default_factory=list)
    by_region: Distribution = field(default_factory=Distribution)
    by_okpd2: Distribution = field(default_factory=Distribution)


@dataclass(slots=True)
class EmbeddingProgress:
    """Насколько корпус готов к семантическому поиску.

    Два счётчика, а не один: фрагменты документации и «карточные» эмбеддинги
    закупок считаются по-разному и отстают по-разному.
    """

    chunks_total: int
    chunks_embedded: int
    tenders_total: int
    tenders_embedded: int
    #: Сколько документов ждёт в очереди сервиса эмбеддингов прямо сейчас.
    #: `None` — брокер не ответил; это факт о брокере, а не ноль работы.
    queue_depth: int | None = None


@dataclass(slots=True)
class TodayIngest:
    """Ход выгрузки за сегодня.

    Сегодняшний день **никогда** не считается закрытым: суточный архив ЕИС
    дописывается до полуночи (`crawler/domain/coverage.py`). Поэтому здесь нет
    и не может быть «выгружено полностью» — только «на данный момент».
    """

    day: date
    #: Успешных сочетаний «регион × тип документа» за сегодня.
    runs_succeeded: int
    runs_failed: int
    runs_running: int
    #: Закупок, сохранённых сегодняшними прогонами.
    saved: int
    #: Закупок с сегодняшней датой публикации, уже лежащих в базе.
    published_today: int
    last_run_at: datetime | None


@dataclass(slots=True)
class CorpusProcessing:
    """Что происходит с корпусом прямо сейчас."""

    embeddings: EmbeddingProgress
    today: TodayIngest
    #: Документы: скачано и разобрано. Берётся из воронки мониторинга, а не
    #: считается заново, — счётчик один, и живёт он там.
    documents_downloaded: int
    documents_extracted: int

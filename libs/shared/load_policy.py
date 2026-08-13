"""Сколько ресурсов машины система имеет право занять.

Три уровня, между которыми переключаются на ходу:

* **1, фоновый.** Рядом работают в тяжёлом софте, и анализ не должен мешать.
  Один процесс разбора, минимальные очереди.
* **2, средний.** Значение по умолчанию: система заметна, но машина остаётся
  пригодной для работы.
* **3, полный.** Машина отдана под анализ.

Уровень задаёт не «сколько процентов», а конкретные потолки: размер пула
разбора, prefetch очередей, конкурентность модели, потолок запросов к ЕИС.
Проценты пришлось бы каждый раз переводить в эти числа, и перевод разошёлся бы
между сервисами.

**Размер пула ограничен памятью, а не только ядрами.** Один процесс извлечения
на крупном скане разворачивает страницы в растр и занимает сотни мегабайт;
восемь таких процессов на машине с 10 ГиБ — это OOM-killer, который выбирает
жертву хуже, чем это делают лимиты. Поэтому:

    пул = min(доля по ядрам, бюджет памяти // пик на процесс)

**Потоков внутри процесса всегда один.** Параллелизм берётся процессами, и
tesseract с OpenMP-потоками внутри каждого из восьми процессов даёт
восьмикратный оверсабскрайб: то же число ядер делится дважды. Это же записано в
комментарии `docker-compose.yml`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

#: Пик памяти на один процесс извлечения, МиБ.
#:
#: **Замерено в контейнере `docs-worker`**, а не выбрано на глаз:
#:
#:     базовый процесс с реестром экстракторов     ~79 МиБ
#:     PDF 80 страниц с текстовым слоем            ~99 МиБ
#:     XLSX 4000 строк                            ~117 МиБ
#:     скан 5 страниц через растеризацию          ~181 МиБ
#:     скан 20 страниц                            ~182 МиБ
#:
#: Ключевое наблюдение — последние две строки: от пяти страниц к двадцати пик
#: не вырос. Страницы растрируются по одной, поэтому память ограничена самой
#: большой страницей, а не размером документа. Это и делает потолок предсказуемым.
#:
#: 256 — измеренные 182 плюс запас на страницы крупнее A4 и на распаковку
#: архива в память. Прежнее значение 900 было взято с потолка и оказалось
#: впятеро завышенным: на лимите контейнера в 1536 МиБ оно схлопывало пул до
#: одного процесса, то есть отменяло весь смысл перехода на процессы.
PEAK_EXTRACTION_MB = 256

#: Потолок запросов к файловому хранилищу ЕИС, запросов в секунду.
#: На 12.5 файл/с в прогоне ХПК/БПК отказов не было; 14 — с небольшим запасом
#: вверх, дальше начинается риск получить бан на весь прогон.
MAX_EIS_RPS = 14.0

#: Параллельных обращений к SOAP-выгрузке ЕИС. Шесть держатся без отказов —
#: замерено в том же прогоне.
MAX_CRAWL_WORKERS = 6


class LoadLevel(IntEnum):
    """Уровень нагрузки на машину."""

    BACKGROUND = 1
    BALANCED = 2
    FULL = 3

    @classmethod
    def parse(cls, raw: object) -> LoadLevel:
        """Уровень из конфигурации или API; непонятное значение — средний.

        Падать здесь нельзя: уровень читается на старте сервиса, и опечатка в
        настройке не должна мешать ему подняться.
        """
        # bool — подкласс int, и `True` иначе молча стал бы фоновым уровнем.
        # Признак «включено» уровнем нагрузки не является.
        if isinstance(raw, bool):
            return cls.BALANCED

        if isinstance(raw, int):
            value = raw
        elif isinstance(raw, str):
            try:
                value = int(raw.strip())
            except ValueError:
                return cls.BALANCED
        else:
            return cls.BALANCED

        try:
            return cls(value)
        except ValueError:
            return cls.BALANCED


@dataclass(frozen=True, slots=True)
class LoadBudget:
    """Конкретные потолки для одного уровня на конкретной машине."""

    level: LoadLevel

    #: Процессов в пуле извлечения текста.
    extraction_workers: int
    #: Извещений, которые docs-worker берёт из очереди одновременно.
    docs_prefetch: int
    #: Сообщений, которые embedding-service берёт одновременно.
    embedding_prefetch: int
    #: Параллельных выгрузок регион × день.
    crawl_workers: int
    #: Одновременных обращений к модели.
    llm_concurrency: int
    #: Потолок запросов к файловому хранилищу ЕИС.
    eis_rps: float
    #: Потоков OpenMP внутри одного процесса. Всегда 1, см. модульный docstring.
    omp_threads: int = 1


#: Доля ядер под разбор и фиксированные потолки очередей по уровням.
#: Ноль в `cpu_share` означает «ровно один процесс», а не «нисколько».
_SHAPES: dict[LoadLevel, tuple[float, int, int, int, float]] = {
    #                    cpu_share  embed_prefetch  crawl  llm  rps
    LoadLevel.BACKGROUND: (0.0, 1, 1, 1, 3.0),
    LoadLevel.BALANCED: (0.5, 2, 3, 4, 8.0),
    LoadLevel.FULL: (1.0, 4, MAX_CRAWL_WORKERS, 8, MAX_EIS_RPS),
}


def detect_cpu_count() -> int:
    """Ядер, доступных процессу.

    `os.cpu_count()` показывает ядра машины, а не квоту cgroup, и в контейнере
    с ограничением по CPU завышает. `sched_getaffinity` доступна не везде,
    поэтому она первая, но не единственная.
    """
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        return max(len(affinity(0)), 1)
    return max(os.cpu_count() or 1, 1)


def detect_memory_mb() -> int | None:
    """Лимит памяти контейнера, МиБ, или None вне контейнера.

    Читается лимит cgroup, а не свободная память хоста: воркер живёт под
    `deploy.resources.limits.memory`, и именно это число решает, сколько
    процессов он переживёт. Вне Linux — None, и тогда потолок по памяти не
    применяется: на машине разработчика он мешал бы больше, чем помогал.
    """
    candidates = (
        # cgroup v2 — «max» означает «без лимита».
        (Path("/sys/fs/cgroup/memory.max"), "max"),
        # cgroup v1 — при отсутствии лимита выдаёт заведомо огромное число.
        (Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"), None),
    )
    for path, unlimited in candidates:
        try:
            raw = path.read_text().strip()
        except OSError:
            continue
        if unlimited is not None and raw == unlimited:
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        # v1 без лимита отдаёт величину порядка 2^63; всё, что больше терабайта,
        # лимитом не является.
        if value <= 0 or value > 1 << 40:
            return None
        return value // (1024 * 1024)
    return None


def resolve(
    level: LoadLevel,
    *,
    cpu_count: int | None = None,
    memory_mb: int | None = None,
    peak_extraction_mb: int = PEAK_EXTRACTION_MB,
) -> LoadBudget:
    """Потолки для уровня на этой машине.

    Чистая функция: ни окружения, ни ввода-вывода внутри — всё, что зависит от
    машины, передаётся аргументами. Иначе её нельзя было бы проверить на
    конфигурациях, которых нет под рукой.
    """
    cpus = max(cpu_count if cpu_count is not None else detect_cpu_count(), 1)
    share, embedding_prefetch, crawl_workers, llm_concurrency, rps = _SHAPES[level]

    by_cpu = 1 if share == 0.0 else max(int(cpus * share), 1)

    # Потолок по памяти. Один процесс оставляем всегда: воркер без единого
    # разборщика бесполезен, а тесный лимит — повод разбирать медленно, а не
    # повод не разбирать вовсе.
    if memory_mb is not None and peak_extraction_mb > 0:
        workers = max(min(by_cpu, memory_mb // peak_extraction_mb), 1)
    else:
        workers = by_cpu

    return LoadBudget(
        level=level,
        extraction_workers=workers,
        # Очередь держит вдвое больше извещений, чем есть разборщиков: пул не
        # должен простаивать в ожидании следующего сообщения. Больше запаса
        # смысла не имеет — сообщения просто лягут в память воркера.
        docs_prefetch=max(workers * 2, 1),
        embedding_prefetch=embedding_prefetch,
        crawl_workers=crawl_workers,
        llm_concurrency=llm_concurrency,
        eis_rps=rps,
    )


def resolve_current(
    raw_level: object = None, *, peak_extraction_mb: int = PEAK_EXTRACTION_MB
) -> LoadBudget:
    """Потолки для уровня из аргумента или переменной `LOAD_LEVEL`."""
    level = LoadLevel.parse(raw_level if raw_level is not None else os.getenv("LOAD_LEVEL"))
    return resolve(
        level,
        cpu_count=detect_cpu_count(),
        memory_mb=detect_memory_mb(),
        peak_extraction_mb=peak_extraction_mb,
    )

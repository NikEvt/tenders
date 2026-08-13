"""Извлечение текста в пуле процессов.

`pypdfium2` не потокобезопасен. Два параллельных разбора PDF в одном процессе
убивают его нативным сигналом — без исключения Python, без traceback, без
записи в лог. Замерено на этом коде: `scripts/bench_extraction.py --mode
threads` падает с SIGSEGV или SIGABRT на **двух** потоках, шесть запусков из
шести.

Продакшен до сих пор жив только потому, что в такте обработки вложения
преобладает скачивание, и окна разбора почти не пересекаются. Это везение, а не
защита: как только доля разбора вырастет — а ради этого работа и делается, —
падения станут регулярными.

Отсюда процессы вместо потоков. У каждого процесса свой экземпляр PDFium,
делить нечего. Заодно OCR получает все ядра, а не одно под GIL: `tesseract`
держит GIL и в потоках не распараллеливается вовсе.

Реализуется существующий `TextExtractionPort` — сценарий обработки документов
подмены не замечает (LSP), а `bootstrap` выбирает реализацию.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor

from libs.shared.logging import get_logger
from services.docs_worker.application.ports import TextExtractionPort
from services.docs_worker.domain.models import ExtractedText

log = get_logger(__name__)

#: Сколько документов разбирает процесс, прежде чем его заменят.
#:
#: Нативные библиотеки текут: PDFium и tesseract оставляют за собой память,
#: которую Python не видит и не собирает. Замена процесса — единственный
#: надёжный способ вернуть её системе. Число выбрано так, чтобы стоимость
#: запуска (доли секунды) размывалась по сотне документов.
MAX_TASKS_PER_CHILD = 100

#: Реестр экстракторов внутри рабочего процесса.
#: Строится один раз в инициализаторе: сборка тянет за собой pdfium, tesseract
#: и LibreOffice, и делать это на каждый документ значило бы платить за импорт
#: чаще, чем за работу.
_registry: TextExtractionPort | None = None


def _init_worker(ocr_languages: str, omp_threads: int) -> None:
    # Потоки OpenMP ограничиваются до загрузки нативных библиотек: tesseract и
    # BLAS читают эти переменные при инициализации и позже их не перечитывают.
    # Без ограничения каждый из N процессов поднял бы поток на ядро, и то же
    # железо оказалось бы поделено дважды.
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[variable] = str(max(omp_threads, 1))

    # Импорт внутри функции: в режиме spawn инициализатор выполняется в свежем
    # процессе, и реестр обязан собраться именно там.
    from services.docs_worker.bootstrap import build_extraction

    global _registry
    _registry = build_extraction(ocr_languages)


def _extract_in_worker(
    content: bytes, file_name: str, content_type: str | None
) -> ExtractedText:
    if _registry is None:
        # Процесс поднялся без инициализатора — состояние невозможное, но если
        # оно случится, лучше внятная ошибка, чем None-ошибка внутри реестра.
        raise RuntimeError("рабочий процесс не инициализирован")
    return _registry.extract(content, file_name, content_type)


class ProcessPoolExtraction(TextExtractionPort):
    """Фасад над пулом процессов, реализующий порт извлечения.

    Метод синхронный — таким объявлен порт, и таким его ждёт сценарий, который
    вызывает извлечение через `asyncio.to_thread`. Поток вызывающего блокируется
    на ожидании результата, но работа идёт в другом процессе, и событийный цикл
    свободен.

    Содержимое файла копируется в рабочий процесс через pickle. Для 60 МБ это
    доли секунды против секунд самого разбора — обмен приемлемый. Альтернатива
    (качать внутри рабочего процесса, как это делал разовый скрипт) стоила бы
    переноса загрузчика за границу процесса и потери общего лимитера скорости.
    """

    def __init__(self, workers: int, ocr_languages: str = "rus+eng") -> None:
        self._workers = max(int(workers), 1)
        self._ocr_languages = ocr_languages
        self._pool: ProcessPoolExecutor | None = None
        # Пул пересоздают и вызывающие потоки, и смена уровня нагрузки —
        # без замка два потока построили бы два пула, и один остался бы висеть.
        self._lock = threading.Lock()
        self._generation = 0

    @property
    def workers(self) -> int:
        return self._workers

    def extract(
        self, content: bytes, file_name: str, content_type: str | None = None
    ) -> ExtractedText:
        """Разбирает файл; при развале пула повторяет попытку один раз.

        Повтор ровно один. Битый файл, роняющий процесс, обязан быть помечен
        сбойным, а не гонять пул по кругу: именно так разовый прогон однажды
        вечно спотыкался об один документ.
        """
        pool, generation = self._ensure_pool()
        try:
            return pool.submit(_extract_in_worker, content, file_name, content_type).result()
        except BrokenExecutor:
            log.warning("extraction.pool_broken", file_name=file_name)
            self._rebuild(generation)

        pool, _ = self._ensure_pool()
        # Второй раз — без перехвата: если файл роняет процесс, это его
        # свойство, и наверх должно уйти исключение. Сценарий пометит документ
        # сбойным и пойдёт дальше, не потеряв соседей.
        return pool.submit(_extract_in_worker, content, file_name, content_type).result()

    def resize(self, workers: int) -> None:
        """Меняет размер пула под новый уровень нагрузки.

        `ProcessPoolExecutor` менять размер не умеет, поэтому пул пересобирается
        целиком. Дожидаться текущих задач не нужно: `shutdown(wait=False)`
        оставляет их доработать, а новые уходят уже в новый пул.
        """
        workers = max(int(workers), 1)
        with self._lock:
            if workers == self._workers:
                return
            log.info("extraction.pool_resized", was=self._workers, now=workers)
            self._workers = workers
            self._shutdown_locked()

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown_locked()

    def _ensure_pool(self) -> tuple[ProcessPoolExecutor, int]:
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=self._workers,
                    initializer=_init_worker,
                    initargs=(self._ocr_languages, 1),
                    max_tasks_per_child=MAX_TASKS_PER_CHILD,
                )
                self._generation += 1
                log.info("extraction.pool_started", workers=self._workers)
            return self._pool, self._generation

    def _rebuild(self, generation: int) -> None:
        """Сбрасывает пул, если его ещё не сбросил другой поток.

        Развал пула видят все потоки, которые в нём работали. Пересобрать должен
        один: остальные, придя с устаревшим поколением, просто получат уже
        готовый новый пул.
        """
        with self._lock:
            if generation != self._generation:
                return
            self._shutdown_locked()

    def _shutdown_locked(self) -> None:
        if self._pool is None:
            return
        self._pool.shutdown(wait=False)
        self._pool = None

"""Анализ рынка: закупки с упоминанием ХПК/БПК в названии или в документах.

Скрипт использует готовые компоненты проекта — SOAP-клиент ЕИС, маппер извещений,
загрузчик вложений и реестр экстракторов docs-worker, — но ведёт их сам, минуя
RabbitMQ, MinIO, эмбеддинги и LLM-фильтры: для разовой выгрузки под regex-поиск
весь этот тракт не нужен и на порядок медленнее.

Состояние живёт в отдельной SQLite рядом с результатом, а не в рабочей базе:
разовая выгрузка на сотни тысяч извещений не должна раздувать операционную БД,
а прогон обязан переживать перезапуск.

Тексты документов не сохраняются: 150 тыс. файлов — это десятки гигабайт, а для
задачи нужны только цитаты. Поэтому regex прогоняется по тексту в памяти сразу
после извлечения, наружу выходит только совпадение с окружающим контекстом.

Этапы (каждый идемпотентен и возобновляем — прогон можно оборвать в любой
момент и продолжить той же командой):

    crawl   регион × день → извещения и метаданные вложений в SQLite
    docs    скачать и распознать вложения закупок-кандидатов, найти ХПК/БПК
    report  Excel по найденному
    stats   прогресс
    run     всё подряд, регион за регионом

Разбор идёт процессами, а не потоками: pypdfium2 не потокобезопасен и на
параллельных PDF роняет процесс нативным сигналом. Замер на 400 вложениях:
потоки — 0.6 файл/с и краш, процессы с быстрыми экстракторами — 13 файл/с.

Запуск — в образе docker/Dockerfile.analysis, где есть tesseract, LibreOffice
и сертификаты ЕИС:

    docker run -d --name zakupki-hpk \
        -v "$PWD/scripts:/app/scripts" -v "$PWD/data:/app/data" \
        -e EIS_TOKEN=... zakupki-market-analysis:latest \
        python scripts/market_analysis.py run --from 2026-01-01
"""

from __future__ import annotations

import argparse
import itertools
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from services.crawler.infrastructure.eis.notification_mapper import NotificationMapper
from services.crawler.infrastructure.eis.soap_client import (
    EisRejectedError,
    SoapTransportError,
    ZakupkiSoapClient,
)
from services.docs_worker.bootstrap import build_extraction
from services.docs_worker.infrastructure.eis.attachment_downloader import (
    DownloadError,
    EisAttachmentDownloader,
)
from services.docs_worker.infrastructure.extraction.archives import (
    RarExtractor,
    SevenZipExtractor,
    ZipExtractor,
)
from services.docs_worker.infrastructure.extraction.base import (
    ExtractorRegistry,
    SkippedExtractor,
)
from services.docs_worker.infrastructure.extraction.documents import (
    DocxExtractor,
    PdfExtractor,
    PlainTextExtractor,
    RtfExtractor,
    XlsxExtractor,
)

# ─────────────────────────────────────────────────────────────────────────────
# Что ищем
# ─────────────────────────────────────────────────────────────────────────────

# ХПК/БПК набирают и кириллицей, и латиницей (Х/X, К/K визуально неотличимы), а
# после OCR подмена латиницей — обычное дело. Границы заданы lookaround'ами по
# буквам, а не \b: \b считает границей стык кириллицы с латиницей и поймал бы
# «ХПК» внутри слова, набранного вперемешку. Цифры границей не считаются —
# «БПК5» и «ХПК20» должны совпадать.
_NOT_LETTER_BEFORE = r"(?<![А-Яа-яЁёA-Za-z])"
_NOT_LETTER_AFTER = r"(?![А-Яа-яЁёA-Za-z])"

# «БПКполн» и «ХПКполн» — общепринятая запись без пробела. Буква сразу после
# аббревиатуры в остальных случаях означает, что это другое слово («ХПКомбинат»),
# поэтому допускаются только известные суффиксы, а не любой хвост.
_SUFFIX = r"(?:\s*[-–]?\s*(?:полн\w*|п\.|[₅₂₀0-9]{1,2}))?"

PATTERNS: dict[str, re.Pattern[str]] = {
    # Химическое потребление кислорода.
    "ХПК": re.compile(
        _NOT_LETTER_BEFORE + r"[ХXхx]\s?[Пп]\s?[КKкk]" + _SUFFIX + _NOT_LETTER_AFTER
    ),
    # Биохимическое потребление кислорода: БПК, БПК5, БПК-5, БПКполн, БПК₅.
    "БПК": re.compile(
        _NOT_LETTER_BEFORE + r"[Бб]\s?[Пп]\s?[КKкk]" + _SUFFIX + _NOT_LETTER_AFTER
    ),
    # Развёрнутые формулировки — ловят ТЗ, где аббревиатура не используется.
    "потребление кислорода": re.compile(
        r"(?:хим\w*|биохим\w*|биологич\w*)?[\s.]*потреблени\w*\s+кислород\w*",
        re.IGNORECASE,
    ),
}

# Ширина цитаты в обе стороны от совпадения. Достаточно, чтобы человек понял
# контекст, не открывая исходный файл.
QUOTE_RADIUS = 220
MAX_HITS_PER_DOCUMENT = 5

# ─────────────────────────────────────────────────────────────────────────────
# Кого проверять по документам
# ─────────────────────────────────────────────────────────────────────────────

# Скачать документы всех извещений нереально: за 7 месяцев по четырём регионам
# это больше миллиона файлов. Предфильтр по карточке сужает круг до закупок, где
# упоминание ХПК/БПК вообще возможно — вода, стоки, экология, лаборатория,
# реагенты, аналитические приборы. Он намеренно широкий: пропущенная закупка
# уже не вернётся, а лишняя стоит одного скачивания.
CANDIDATE_RE = re.compile(
    r"вод(а|ы|е|у|ой|ное|ного|ному|ным|ном|оснабж|оотвед|оочист|оподгот|оканал)"
    r"|сточн|канализ|очистн|ливнев|дренаж|скважин|водозабор|артезиан"
    r"|питьев|минеральн\w+ вод|гидрохим|гидробиолог|акватор|водоём|водоем|река|озер"
    r"|лаборатор|аналитическ|аккредитован|испытательн"
    r"|анализ\w*\s+(вод|проб|сточн|почв|грунт|осадк|отход|воздух)"
    r"|отбор\w*\s+проб|пробоотбор|пробоподготовк"
    r"|эколог|природоохран|окружающ\w+\s+сред|санитарно-?эпидемиолог|СанПиН"
    r"|производственн\w+\s+контрол|ПЭК\b|мониторинг"
    r"|отход|шлам|осадк\w*\s+сточн|иловы|очистк\w*\s+(вод|стоков|жидк)"
    r"|реагент|реактив|химическ\w+\s+(веществ|продукц|реактив|анализ|состав)"
    r"|анализатор|фотометр|спектрофотометр|хроматограф|титр|рН-метр|pH-метр"
    r"|ПНД\s*Ф|ГОСТ\s*Р?\s*ИСО|методик\w+\s+измерен"
    r"|КОС\b|ВЗУ\b|БОС\b|водоканал|теплосет|котельн|бассейн|градирн",
    re.IGNORECASE,
)

# ОКПД2, где тема возможна даже при нейтральном названии.
#   36/37  вода, сточные воды      39   рекультивация и обращение с отходами
#   71.20  испытания и анализ      71.12 инженерно-техническое проектирование
#   20.59/20.13/20.14 реактивы и химия      26.51 приборы для измерений
#   38     сбор и обработка отходов          43.22 санитарно-технические работы
CANDIDATE_OKPD2 = (
    "36.", "37.", "38.", "39.", "71.20", "71.12", "20.59", "20.13", "20.14",
    "26.51", "26.60", "43.22", "42.21", "35.30", "86.90",
)

# ─────────────────────────────────────────────────────────────────────────────
# Прочие настройки
# ─────────────────────────────────────────────────────────────────────────────

EIS_DOCUMENT_TYPE = "epNotificationEF2020"
NOTICE_URL = "https://zakupki.gov.ru/epz/order/notice/ea44/view/common-info.html?regNumber={}"

# Криптоподписи и сертификаты — не документы, качать их незачем.
SKIP_EXTENSIONS = frozenset({"sig", "p7s", "sgn", "cer", "crt", "der"})

# Том многотомного архива. Распаковать его отдельно нельзя: rarfile требует все
# тома сразу на диске, а вложения качаются по одному в память — каждый том даёт
# «Need to start from first volume». Заказчики выкладывают так проектно-сметную
# документацию, и это не редкость на пару файлов: четыре закупки в выборке
# принесли по ~550 томов на 50 МБ, то есть 84 ГБ бесполезной выкачки, на которой
# скорость разбора падала с 11 до 0.1 файл/с. Первый том тоже пропускаем — без
# остальных он разворачивается в обрезанный мусор.
MULTIVOLUME_RE = re.compile(
    r"\.part\d+\.(rar|zip|7z)$|\.[rz]\d{2,}$|\.7z\.\d{3,}$|\.zip\.\d{3,}$",
    re.IGNORECASE,
)

# Крупные файлы — это альбомы чертежей и сканы планов; текста с ХПК в них
# практически не бывает, а память и время они съедают на порядок больше.
# Замер на живых данных: из 176 находок 173 пришли из файлов меньше 1 МБ, а
# 930 разобранных файлов крупнее 30 МБ не дали ни одной.
DEFAULT_MAX_FILE_MB = 60

# Потолок на закупку. Одиночный лимит на файл не спасает от закупки, которая
# приносит сотни файлов по отдельности небольших: четыре закупки в выборке дали
# 84 ГБ томами по 50 МБ. Бюджет на закупку ограничивает именно это.
DEFAULT_MAX_TENDER_MB = 30

# Документы, где требования к качеству воды встречаются чаще всего, обрабатываются
# первыми: если прогон придётся оборвать, полезное уже будет собрано.
PRIORITY_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (0, re.compile(r"тех\w*\s*зад|\bТЗ\b|описани\w+\s+объект|техническ\w+\s+часть", re.I)),
    (1, re.compile(r"обоснован|НМЦ[КЦ]|расч[ёе]т", re.I)),
    (2, re.compile(r"извещени|документаци|приложени|смет|ведомост", re.I)),
    (3, re.compile(r"контракт|договор|заявк|инструкц|деклараци", re.I)),
)


def _log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Хранилище
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    reg_num        TEXT PRIMARY KEY,
    region         TEXT,
    name           TEXT,
    description    TEXT,
    price          REAL,
    currency       TEXT,
    publish_date   TEXT,
    end_date       TEXT,
    customer_name  TEXT,
    customer_inn   TEXT,
    okpd2_codes    TEXT,
    okpd2_names    TEXT,
    is_candidate   INTEGER NOT NULL DEFAULT 0,
    card_hit       TEXT
);
CREATE INDEX IF NOT EXISTS tenders_candidate_idx ON tenders(is_candidate);

CREATE TABLE IF NOT EXISTS attachments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    reg_num        TEXT NOT NULL,
    attachment_id  TEXT NOT NULL,
    file_name      TEXT,
    url            TEXT,
    file_size      INTEGER,
    doc_kind_name  TEXT,
    priority       INTEGER NOT NULL DEFAULT 9,
    -- pending → done | skipped | failed
    status         TEXT NOT NULL DEFAULT 'pending',
    extractor      TEXT,
    chars          INTEGER,
    hit_count      INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    UNIQUE(reg_num, attachment_id)
);
CREATE INDEX IF NOT EXISTS attachments_status_idx ON attachments(status, priority);
CREATE INDEX IF NOT EXISTS attachments_reg_idx ON attachments(reg_num);

CREATE TABLE IF NOT EXISTS hits (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    reg_num        TEXT NOT NULL,
    source         TEXT NOT NULL,          -- 'card' | 'document'
    term           TEXT NOT NULL,
    quote          TEXT NOT NULL,
    file_name      TEXT,
    doc_url        TEXT,
    page           INTEGER
);
CREATE INDEX IF NOT EXISTS hits_reg_idx ON hits(reg_num);

CREATE TABLE IF NOT EXISTS crawl_state (
    region   TEXT NOT NULL,
    day      TEXT NOT NULL,
    status   TEXT NOT NULL,               -- 'success' | 'failed'
    fetched  INTEGER NOT NULL DEFAULT 0,
    error    TEXT,
    PRIMARY KEY (region, day)
);
"""


class Store:
    """SQLite с одним соединением под общим замком.

    Тяжёлая работа (сеть, OCR) идёт вне замка, поэтому один писатель не мешает
    десятку рабочих потоков, зато снимает вопрос блокировок SQLite.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self._db.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._db.commit()
            self._db.close()

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def scalar(self, sql: str, params: tuple = ()) -> int:
        return int(self.query(sql, params)[0][0])

    def done_days(self) -> set[tuple[str, str]]:
        return {
            (region, day)
            for region, day in self.query(
                "SELECT region, day FROM crawl_state WHERE status='success'"
            )
        }

    def save_day(
        self,
        region: str,
        day: date,
        rows: list[tuple],
        attachments: list[tuple],
        card_hits: list[tuple],
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT OR REPLACE INTO tenders (reg_num, region, name, description,"
                " price, currency, publish_date, end_date, customer_name, customer_inn,"
                " okpd2_codes, okpd2_names, is_candidate, card_hit)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self._db.executemany(
                "INSERT OR IGNORE INTO attachments (reg_num, attachment_id, file_name,"
                " url, file_size, doc_kind_name, priority) VALUES (?,?,?,?,?,?,?)",
                attachments,
            )
            if card_hits:
                # Перекрёшивание дня не должно плодить дубли цитат по карточке.
                self._db.executemany(
                    "DELETE FROM hits WHERE reg_num=? AND source='card'",
                    [(h[0],) for h in card_hits],
                )
                self._db.executemany(
                    "INSERT INTO hits (reg_num, source, term, quote)"
                    " VALUES (?, 'card', ?, ?)",
                    card_hits,
                )
            self._db.execute(
                "INSERT OR REPLACE INTO crawl_state (region, day, status, fetched, error)"
                " VALUES (?,?,?,?,?)",
                (
                    region,
                    day.isoformat(),
                    "failed" if error else "success",
                    len(rows),
                    error,
                ),
            )
            self._db.commit()

    def save_document_result(self, result: DocumentResult) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE attachments SET status=?, extractor=?, chars=?, hit_count=?,"
                " error=? WHERE id=?",
                (
                    result.status,
                    result.extractor,
                    result.chars,
                    len(result.hits),
                    result.error,
                    result.attachment_id,
                ),
            )
            if result.hits:
                self._db.executemany(
                    "INSERT INTO hits (reg_num, source, term, quote, file_name,"
                    " doc_url, page) VALUES (?, 'document', ?, ?, ?, ?, ?)",
                    [
                        (
                            result.reg_num,
                            hit.term,
                            hit.quote,
                            hit.file_name,
                            result.url,
                            hit.page,
                        )
                        for hit in result.hits
                    ],
                )
            self._db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Поиск упоминаний
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Hit:
    term: str
    quote: str
    file_name: str | None = None
    page: int | None = None


def find_mentions(text: str, file_name: str | None = None, page: int | None = None) -> list[Hit]:
    """Все упоминания ХПК/БПК в тексте, с окружающим контекстом.

    Совпадения разных шаблонов на одном месте («ХПК» внутри «химическое
    потребление кислорода» не пересекаются, но перекрытия возможны на стыках)
    схлопываются по позиции: один и тот же фрагмент не должен давать две цитаты.
    """
    if not text:
        return []

    found: list[tuple[int, str, str]] = []
    seen_spans: list[tuple[int, int]] = []

    for term, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < seen_end and seen_start < end for seen_start, seen_end in seen_spans):
                continue
            seen_spans.append((start, end))
            quote = text[max(0, start - QUOTE_RADIUS) : end + QUOTE_RADIUS]
            quote = " ".join(quote.split())
            found.append((start, term, quote))

    found.sort(key=lambda item: item[0])
    return [
        Hit(term=term, quote=quote, file_name=file_name, page=page)
        for _, term, quote in found[:MAX_HITS_PER_DOCUMENT]
    ]


def is_candidate(
    name: str, description: str, okpd2_codes: list[str], okpd2_names: list[str]
) -> bool:
    card = f"{name} {description} {' '.join(okpd2_names)}"
    if CANDIDATE_RE.search(card):
        return True
    return any(code.startswith(CANDIDATE_OKPD2) for code in okpd2_codes)


def priority_of(file_name: str | None, doc_kind: str | None) -> int:
    label = f"{file_name or ''} {doc_kind or ''}"
    for rank, pattern in PRIORITY_PATTERNS:
        if pattern.search(label):
            return rank
    return 9


# ─────────────────────────────────────────────────────────────────────────────
# Этап 1: метаданные
# ─────────────────────────────────────────────────────────────────────────────


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def crawl(
    store: Store, args: argparse.Namespace, regions: list[str] | None = None
) -> None:
    token = require_token()
    regions = regions or args.regions
    days = days_between(args.date_from, args.date_to)
    already_done = store.done_days()
    todo = [
        (region, day)
        for region in regions
        for day in days
        if (region, day.isoformat()) not in already_done
    ]
    if not todo:
        _log(f"crawl [{','.join(regions)}]: все дни уже выгружены")
        return

    _log(
        f"crawl [{','.join(regions)}]: {len(regions)} регион(ов) × {len(days)} дн. = "
        f"{len(todo)} задач(и) к выгрузке"
    )

    counters = {"tenders": 0, "candidates": 0, "card_hits": 0, "failed": 0, "done": 0}
    lock = threading.Lock()
    started = time.monotonic()

    def worker(task: tuple[str, date]) -> None:
        region, day = task
        client = _thread_local_client(token)
        mapper = NotificationMapper(region_code=region)

        rows: list[tuple] = []
        attachments: list[tuple] = []
        card_hits: list[tuple] = []
        error: str | None = None
        candidates = 0

        try:
            for document in client.get_by_region(region, EIS_DOCUMENT_TYPE, day):
                tender = mapper.map_document(document)
                if tender is None or not tender.reg_num:
                    continue

                name = tender.name or ""
                description = tender.description or ""
                codes = list(tender.okpd2_codes or [])
                names = [n for n in (tender.okpd2_names or []) if n]

                hits = find_mentions(f"{name}\n{description}")
                candidate = bool(hits) or is_candidate(name, description, codes, names)
                candidates += candidate

                rows.append(
                    (
                        tender.reg_num,
                        region,
                        name,
                        description,
                        float(tender.price) if tender.price is not None else None,
                        tender.currency,
                        tender.publish_date.isoformat() if tender.publish_date else None,
                        tender.end_date.isoformat() if tender.end_date else None,
                        tender.customer_name,
                        tender.customer_inn,
                        ", ".join(codes),
                        "; ".join(names),
                        int(candidate),
                        hits[0].term if hits else None,
                    )
                )
                for hit in hits:
                    card_hits.append((tender.reg_num, hit.term, hit.quote))

                if candidate:
                    for attachment in tender.attachments:
                        if not attachment.url:
                            continue
                        file_name = attachment.file_name or ""
                        extension = file_name.lower().rsplit(".", 1)[-1]
                        if extension in SKIP_EXTENSIONS or MULTIVOLUME_RE.search(file_name):
                            continue
                        attachments.append(
                            (
                                tender.reg_num,
                                attachment.attachment_id,
                                attachment.file_name,
                                attachment.url,
                                attachment.file_size,
                                attachment.doc_kind_name,
                                priority_of(attachment.file_name, attachment.doc_kind_name),
                            )
                        )
        except (SoapTransportError, EisRejectedError) as exc:
            error = str(exc)[:500]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:500]

        store.save_day(region, day, rows, attachments, card_hits, error)

        with lock:
            counters["done"] += 1
            counters["tenders"] += len(rows)
            counters["candidates"] += candidates
            counters["card_hits"] += len({h[0] for h in card_hits})
            counters["failed"] += bool(error)
            if counters["done"] % 10 == 0 or counters["done"] == len(todo):
                elapsed = time.monotonic() - started
                rate = counters["done"] / elapsed
                eta = (len(todo) - counters["done"]) / rate if rate else 0
                _log(
                    f"crawl {counters['done']}/{len(todo)} дней · "
                    f"извещений {counters['tenders']} · "
                    f"кандидатов {counters['candidates']} · "
                    f"ХПК/БПК в карточке {counters['card_hits']} · "
                    f"ошибок {counters['failed']} · ETA {eta / 60:.0f} мин"
                )
            if error:
                _log(f"  ! {region} {day}: {error[:160]}")

    with ThreadPoolExecutor(args.crawl_workers) as pool:
        list(pool.map(worker, todo))

    _log(
        f"crawl завершён: {counters['tenders']} извещений, "
        f"{counters['candidates']} кандидатов на разбор документов"
    )


_thread_local = threading.local()


def _thread_local_client(token: str) -> ZakupkiSoapClient:
    """У каждого потока свой SOAP-клиент: `requests.Session` не потокобезопасна."""
    client = getattr(_thread_local, "soap", None)
    if client is None:
        client = ZakupkiSoapClient(token=token)
        _thread_local.soap = client
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Этап 2: документы
# ─────────────────────────────────────────────────────────────────────────────


def build_fast_extraction() -> ExtractorRegistry:
    """Реестр без OCR и без LibreOffice.

    Замер на 400 вложениях: 79% файлов читаются текстовыми экстракторами со
    скоростью сети (~10 файл/с), оставшийся 21% (сканы и устаревшие .doc) —
    на порядок медленнее и съедает всё время. Быстрый проход обрабатывает
    большинство сразу, дорогие файлы помечаются `deferred` и добираются
    отдельным проходом `docs --ocr`.
    """
    return ExtractorRegistry(
        [
            SkippedExtractor(),
            PdfExtractor(),
            DocxExtractor(),
            XlsxExtractor(),
            RtfExtractor(),
            ZipExtractor(),
            SevenZipExtractor(),
            RarExtractor(),
            PlainTextExtractor(),
        ]
    )


# Экстракторы, чей пустой результат означает «нужен дорогой проход», а не
# «текста нет»: PDF-скан и форматы, которые умеет только LibreOffice.
DEFERRABLE_EXTENSIONS = frozenset({"doc", "xls", "ppt", "odt", "ods",
                                   "png", "jpg", "jpeg", "tif", "tiff", "bmp"})


@dataclass
class DocumentResult:
    attachment_id: int
    reg_num: str
    url: str
    status: str
    file_name: str = ""
    extractor: str | None = None
    chars: int = 0
    error: str | None = None
    hits: list[Hit] = field(default_factory=list)


class DocumentScanner:
    """Скачивает вложение, извлекает текст и ищет в нём упоминания.

    Текст никуда не сохраняется — наружу уходят только совпадения. Архивы
    разворачиваются в памяти рекурсивно: комплект документации одним zip
    встречается постоянно, и без распаковки теряется как раз ТЗ.
    """

    MAX_ARCHIVE_DEPTH = 2

    def __init__(
        self,
        token: str,
        requests_per_second: float,
        max_file_bytes: int,
        with_ocr: bool = False,
    ) -> None:
        self._downloader = EisAttachmentDownloader(
            token=token, requests_per_second=requests_per_second
        )
        self._extraction = build_extraction() if with_ocr else build_fast_extraction()
        self._with_ocr = with_ocr
        self._max_file_bytes = max_file_bytes

    def scan(self, attachment_id: int, reg_num: str, url: str, file_name: str) -> DocumentResult:
        result = DocumentResult(attachment_id=attachment_id, reg_num=reg_num, url=url,
                                status="done", file_name=file_name)

        # Проверка до скачивания, а не после: смысл как раз в том, чтобы не
        # тратить сеть на том, который всё равно не распакуется.
        if MULTIVOLUME_RE.search(file_name):
            result.status = "skipped"
            result.extractor = "multivolume"
            result.error = "том многотомного архива — распаковка по одному невозможна"
            return result

        try:
            content, content_type = self._downloader.download(url)
        except DownloadError as exc:
            result.status = "failed"
            result.error = str(exc)[:400]
            return result

        if len(content) > self._max_file_bytes:
            result.status = "skipped"
            result.extractor = "too_large"
            result.error = f"{len(content) / 1e6:.0f} МБ — больше лимита"
            return result

        try:
            self._scan_content(content, file_name or "file", content_type, result, depth=0)
        except Exception as exc:
            result.status = "failed"
            result.error = f"{type(exc).__name__}: {exc}"[:400]
        return result

    def _scan_content(
        self,
        content: bytes,
        file_name: str,
        content_type: str | None,
        result: DocumentResult,
        depth: int,
    ) -> None:
        extracted = self._extraction.extract(content, file_name, content_type)
        result.extractor = extracted.extractor

        if not self._with_ocr and depth == 0 and self._needs_expensive_pass(
            file_name, extracted
        ):
            result.status = "deferred"
            return

        if extracted.embedded_files:
            if depth >= self.MAX_ARCHIVE_DEPTH:
                return
            for embedded in extracted.embedded_files:
                extension = embedded.file_name.lower().rsplit(".", 1)[-1]
                if extension in SKIP_EXTENSIONS or len(embedded.content) > self._max_file_bytes:
                    continue
                try:
                    self._scan_content(
                        embedded.content, embedded.file_name, None, result, depth + 1
                    )
                except Exception:
                    continue
            return

        for page in extracted.pages:
            result.chars += len(page.text)
            if len(result.hits) >= MAX_HITS_PER_DOCUMENT:
                break
            result.hits.extend(
                find_mentions(
                    page.text,
                    file_name=file_name,
                    page=page.number if len(extracted.pages) > 1 else None,
                )
            )
        result.hits = result.hits[:MAX_HITS_PER_DOCUMENT]

    @staticmethod
    def _needs_expensive_pass(file_name: str, extracted) -> bool:
        """Файл читается, но только дорогим способом — OCR или LibreOffice."""
        extension = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
        if extension in DEFERRABLE_EXTENSIONS:
            return True
        # PDF без текстового слоя — скан; его берёт только OCR.
        return extension == "pdf" and extracted.looks_like_scan()


def _safe_report(store: Store, args: argparse.Namespace, quiet: bool = True) -> None:
    """Промежуточный отчёт не имеет права оборвать разбор.

    Однажды уже оборвал: openpyxl падает на управляющих символах из OCR, и
    вместе с отчётом умирал прогон, шедший к тому моменту полчаса. Данные лежат
    в SQLite, отчёт из них пересобирается когда угодно — значит, его сбой стоит
    строки в логе, а не потерянных часов.
    """
    try:
        build_report(store, args, quiet=quiet)
    except Exception as exc:
        _log(f"  ! промежуточный отчёт не собрался ({type(exc).__name__}: {exc}), продолжаю")


_worker_scanner: DocumentScanner | None = None


def _init_worker(token: str, rps: float, max_bytes: int, with_ocr: bool) -> None:
    """Свой сканер на процесс.

    Разбор идёт процессами, а не потоками: pypdfium2 не потокобезопасен и на
    параллельных PDF роняет весь процесс нативным сигналом, без исключения
    Python. Заодно OCR получает все ядра, а не одно под GIL.
    """
    global _worker_scanner
    _worker_scanner = DocumentScanner(token, rps, max_bytes, with_ocr)


def _scan_task(row: tuple) -> DocumentResult:
    assert _worker_scanner is not None
    attachment_id, reg_num, url, file_name = row
    return _worker_scanner.scan(attachment_id, reg_num, url, file_name or "")


def scan_documents(
    store: Store, args: argparse.Namespace, regions: list[str] | None = None
) -> None:
    """Разбирает вложения закупок-кандидатов и ищет в них ХПК/БПК.

    Порядок работы подчинён тому, чтобы полезное появлялось раньше: сначала
    техзадания и обоснования НМЦК, затем всё остальное; сканы и .doc в быстром
    режиме откладываются. Excel переписывается по ходу — прогон на много часов
    должен быть виден, а не только по завершении.
    """
    token = require_token()
    regions = regions or args.regions
    source_status = "deferred" if args.ocr else "pending"
    placeholders = ",".join("?" for _ in regions)
    # Отбор сужается запросом, а не пометкой в таблице: невыбранные вложения
    # остаются `pending` и достанутся следующему прогону без флагов. Обзорный
    # проход не должен делать полный невозможным.
    #
    # Бюджет на закупку расходуется в порядке приоритета, поэтому в него первыми
    # попадают ТЗ и обоснование НМЦК, а обрезается тяжёлый хвост — сметы,
    # альбомы чертежей, тома проектной документации. Нарастающая сумма считается
    # по всем вложениям закупки, а не только по ожидающим: иначе возобновлённый
    # прогон выдавал бы закупке новый бюджет и лимит ничего не ограничивал.
    pending = store.query(
        "SELECT id, reg_num, url, file_name FROM ("
        "  SELECT a.id, a.reg_num, a.url, a.file_name, a.priority, a.status,"
        "         SUM(COALESCE(a.file_size, 0)) OVER ("
        "             PARTITION BY a.reg_num ORDER BY a.priority, a.id"
        "             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS spent"
        "    FROM attachments a JOIN tenders t ON t.reg_num = a.reg_num"
        f"   WHERE t.is_candidate=1 AND t.region IN ({placeholders})"
        "     AND a.priority <= ?"
        "     AND (a.file_size IS NULL OR a.file_size <= ?)"
        ") WHERE status=? AND spent <= ?"
        " ORDER BY priority, id" + (f" LIMIT {args.limit}" if args.limit else ""),
        (
            *regions,
            args.max_priority,
            args.max_file_mb * 1024 * 1024,
            source_status,
            args.max_tender_mb * 1024 * 1024,
        ),
    )
    if not pending:
        _log(f"docs [{','.join(regions)}]: нечего обрабатывать ({source_status})")
        return

    total = len(pending)
    mode = "с OCR" if args.ocr else "быстрый проход"
    _log(
        f"docs [{','.join(regions)}] {mode}: {total} вложений, "
        f"{args.doc_workers} потоков"
    )

    # Лимитер живёт внутри процесса, поэтому общий потолок делится между ними.
    per_worker_rps = max(args.rps / args.doc_workers, 0.2)
    initargs = (token, per_worker_rps, args.max_file_mb * 1024 * 1024, args.ocr)

    counters = {"done": 0, "failed": 0, "skipped": 0, "deferred": 0, "hits": 0,
                "crashes": 0}
    found_tenders: set[str] = set()
    started = time.monotonic()

    def handle(result: DocumentResult) -> None:
        store.save_document_result(result)
        counters["done"] += 1
        counters["failed"] += result.status == "failed"
        counters["skipped"] += result.status == "skipped"
        counters["deferred"] += result.status == "deferred"
        if result.hits:
            counters["hits"] += len(result.hits)
            found_tenders.add(result.reg_num)
            _log(
                f"  + {result.reg_num} · {result.hits[0].term} · "
                f"{result.file_name[:55]} · «{result.hits[0].quote[:110]}…»"
            )
        done = counters["done"]
        if done % args.report_every == 0:
            _safe_report(store, args)
        if done % 200 == 0 or done == total:
            elapsed = time.monotonic() - started
            rate = done / elapsed
            eta = (total - done) / rate if rate else 0
            _log(
                f"docs {done}/{total} · {rate:.1f} файл/с · "
                f"находок {counters['hits']} в {len(found_tenders)} закупках · "
                f"отложено {counters['deferred']} · ошибок {counters['failed']} · "
                f"ETA {eta / 60:.0f} мин"
            )

    queue = list(pending)
    while queue:
        queue, crashed = _drain(queue, args.doc_workers, initargs, handle)
        if not crashed:
            break
        # Битый PDF способен убить процесс-разборщик нативным сигналом. Файлы,
        # бывшие в работе, помечаются сбойными: иначе прогон вечно спотыкался
        # бы об один и тот же документ.
        counters["crashes"] += 1
        stuck, queue = queue[: args.doc_workers], queue[args.doc_workers :]
        for attachment_id, reg_num, url, file_name in stuck:
            handle(
                DocumentResult(
                    attachment_id=attachment_id, reg_num=reg_num, url=url,
                    status="failed", file_name=file_name or "",
                    error="разборщик упал на этом файле",
                )
            )
        _log(f"  ! пул перезапущен после сбоя, пропущено {len(stuck)} файл(ов)")

    _safe_report(store, args)
    _log(
        f"docs [{','.join(regions)}] завершён: {counters['hits']} упоминаний в "
        f"{len(found_tenders)} закупках, отложено {counters['deferred']}, "
        f"сбоев пула {counters['crashes']}"
    )


def _drain(
    queue: list[tuple],
    workers: int,
    initargs: tuple,
    handle,
) -> tuple[list[tuple], bool]:
    """Прогоняет очередь через пул процессов.

    Возвращает необработанный остаток и признак падения пула: после нативного
    краха прогон обязан продолжиться с того же места, а не начаться заново.
    Задачи подаются скользящим окном — держать сотни тысяч futures в памяти
    незачем.
    """
    done_ids: set[int] = set()
    tasks = iter(queue)
    crashed = False

    try:
        with ProcessPoolExecutor(
            workers, initializer=_init_worker, initargs=initargs
        ) as pool:
            futures = {
                pool.submit(_scan_task, row): row
                for row in itertools.islice(tasks, workers * 4)
            }
            while futures:
                finished, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in finished:
                    row = futures.pop(future)
                    handle(future.result())
                    done_ids.add(row[0])
                    nxt = next(tasks, None)
                    if nxt is not None:
                        futures[pool.submit(_scan_task, nxt)] = nxt
    except BrokenProcessPool:
        crashed = True

    return [row for row in queue if row[0] not in done_ids], crashed


# ─────────────────────────────────────────────────────────────────────────────
# Этап 3: отчёт
# ─────────────────────────────────────────────────────────────────────────────

REGION_NAMES = {
    "77": "Москва",
    "50": "Московская область",
    "78": "Санкт-Петербург",
    "47": "Ленинградская область",
}

SUMMARY_HEADERS = [
    ("Ссылка на закупку", 46),
    ("Рег. номер", 20),
    ("Наименование закупки", 60),
    ("НМЦК, руб.", 18),
    ("Описание объекта закупки", 60),
    ("Заказчик", 46),
    ("ИНН", 14),
    ("Регион", 20),
    ("Опубликовано", 14),
    ("Приём заявок до", 14),
    ("ОКПД2", 22),
    ("Найдено", 12),
    ("Где найдено", 18),
    ("Документ-источник", 40),
    ("Стр.", 7),
    ("Цитата", 90),
    ("Всего упоминаний", 10),
]

CITATION_HEADERS = [
    ("Рег. номер", 20),
    ("Ссылка на закупку", 46),
    ("Наименование закупки", 55),
    ("Заказчик", 40),
    ("Термин", 12),
    ("Где найдено", 16),
    ("Документ-источник", 40),
    ("Стр.", 7),
    ("Ссылка на документ", 50),
    ("Цитата", 110),
]


# xlsx — это XML, и openpyxl падает с ValueError на символе, которого в XML 1.0
# быть не может. Текстовый слой PDF и OCR приносят такие регулярно: NULL,
# управляющие символы, обломки суррогатных пар из битых CMap, «неперсонажи»
# U+FFFE/U+FFFF (в них разваливается мягкий перенос — «аммоний￾ион»).
# Перечислять запрещённое бесполезно, поэтому оставляем только разрешённое
# продукцией Char из спецификации XML. Ячейка Excel вдобавок вмещает не больше
# 32767 символов.
_ILLEGAL_XML = re.compile(
    "[^\\x09\\x0a\\x0d\\x20-\\ud7ff\\ue000-\\ufffd\\U00010000-\\U0010ffff]"
)
_MAX_CELL_CHARS = 32000


def _cell(value: object) -> object:
    """Готовит значение к записи: чистит текст, остальное отдаёт как есть."""
    if not isinstance(value, str):
        return value
    return _ILLEGAL_XML.sub(" ", value)[:_MAX_CELL_CHARS]


def build_report(store: Store, args: argparse.Namespace, quiet: bool = False) -> None:
    """Пересобирает Excel из накопленного.

    Вызывается и по завершении, и по ходу длинного прогона, поэтому пишет через
    временный файл: иначе открытый пользователем отчёт однажды окажется
    наполовину записанным.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    rows = store.query(
        """
        SELECT t.reg_num, t.name, t.price, t.description, t.customer_name,
               t.customer_inn, t.region, t.publish_date, t.end_date, t.okpd2_codes,
               h.term, h.source, h.file_name, h.page, h.quote, h.doc_url
        FROM hits h JOIN tenders t ON t.reg_num = h.reg_num
        ORDER BY t.publish_date DESC, t.reg_num,
                 CASE h.source WHEN 'card' THEN 0 ELSE 1 END, h.id
        """
    )
    if not rows:
        if not quiet:
            _log("report: упоминаний не найдено, файл не создан")
        return

    workbook = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E78")
    wrap = Alignment(vertical="top", wrap_text=True)

    def setup(sheet, headers) -> None:
        sheet.append([title for title, _ in headers])
        for index, (_, width) in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=index)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    # Лист 1 — по одной строке на закупку: лучшая цитата плюс счётчик.
    summary = workbook.active
    summary.title = "Закупки"
    setup(summary, SUMMARY_HEADERS)

    citations = workbook.create_sheet("Все цитаты")
    setup(citations, CITATION_HEADERS)

    mention_counts = dict(
        store.query("SELECT reg_num, count(*) FROM hits GROUP BY reg_num")
    )

    seen: set[str] = set()
    for row in rows:
        (reg_num, name, price, description, customer, inn, region, published, deadline,
         okpd2, term, source, file_name, page, quote, doc_url) = row
        url = NOTICE_URL.format(reg_num)
        where = "название/описание" if source == "card" else "документ"
        published = (published or "")[:10]
        deadline = (deadline or "")[:10]

        citations.append([
            _cell(v) for v in
            (reg_num, url, name, customer, term, where, file_name, page, doc_url, quote)
        ])

        if reg_num in seen:
            continue
        seen.add(reg_num)
        summary.append([
            _cell(v) for v in
            (url, reg_num, name, price, description, customer, inn,
             REGION_NAMES.get(region, region), published, deadline, okpd2,
             term, where, file_name, page, quote, mention_counts.get(reg_num, 1))
        ])

    for sheet, headers in ((summary, SUMMARY_HEADERS), (citations, CITATION_HEADERS)):
        for line in sheet.iter_rows(min_row=2):
            for cell in line:
                cell.alignment = wrap
        for index, (title, _) in enumerate(headers, start=1):
            if title == "НМЦК, руб.":
                for line in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
                    line[0].number_format = "# ##0.00"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(".tmp.xlsx")
    workbook.save(temporary)
    temporary.replace(args.out)
    if not quiet:
        _log(f"report: {len(seen)} закупок, {len(rows)} цитат → {args.out}")


# ─────────────────────────────────────────────────────────────────────────────
# Прогресс
# ─────────────────────────────────────────────────────────────────────────────


def show_stats(store: Store, args: argparse.Namespace) -> None:
    days = dict(store.query("SELECT status, count(*) FROM crawl_state GROUP BY status"))
    docs = dict(store.query("SELECT status, count(*) FROM attachments GROUP BY status"))
    by_source = dict(
        store.query("SELECT source, count(DISTINCT reg_num) FROM hits GROUP BY source")
    )
    _log(f"дни выгрузки:       {days or '—'}")
    _log(f"извещений:          {store.scalar('SELECT count(*) FROM tenders')}")
    _log(f"кандидатов:         {store.scalar('SELECT count(*) FROM tenders WHERE is_candidate=1')}")
    _log(f"вложения:           {docs or '—'}")
    _log(f"упоминаний ХПК/БПК: {store.scalar('SELECT count(*) FROM hits')}")
    _log(
        f"закупок с находкой: {store.scalar('SELECT count(DISTINCT reg_num) FROM hits')}"
        f" (карточка {by_source.get('card', 0)}, документы {by_source.get('document', 0)})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def run_all(store: Store, args: argparse.Namespace) -> None:
    """Полный прогон: регион за регионом, от дешёвого к дорогому.

    Порядок выбран так, чтобы за первые часы была видна основная часть картины:
    выгрузка метаданных даёт все упоминания в названиях сразу, быстрый проход по
    документам закрывает ~80% файлов, и только потом на остаток тратится OCR.
    Каждый шаг возобновляем, поэтому прогон можно оборвать в любой момент и
    продолжить той же командой.
    """
    for region in args.regions:
        _log(f"═══ регион {REGION_NAMES.get(region, region)} ({region}) ═══")
        crawl(store, args, regions=[region])
        _safe_report(store, args, quiet=False)
        args.ocr = False
        scan_documents(store, args, regions=[region])
        _safe_report(store, args, quiet=False)

    if args.with_ocr_pass:
        _log("═══ проход OCR по отложенным файлам ═══")
        for region in args.regions:
            args.ocr = True
            scan_documents(store, args, regions=[region])
            _safe_report(store, args, quiet=False)

    show_stats(store, args)


def require_token() -> str:
    token = os.environ.get("EIS_TOKEN", "").strip()
    if not token:
        sys.exit("EIS_TOKEN не задан — без него ЕИС не отвечает")
    return token


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Анализ рынка: закупки с упоминанием ХПК/БПК",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "stage", choices=("crawl", "docs", "report", "stats", "run"),
        help="crawl — метаданные, docs — документы, report — Excel, "
             "stats — прогресс, run — всё подряд по регионам",
    )
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat,
                        default=date(2026, 1, 1), help="Начало периода")
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat,
                        default=date.today(), help="Конец периода")
    parser.add_argument("--regions", default="77,50,78,47",
                        help="Коды регионов через запятую")
    parser.add_argument("--db", type=Path, default=Path("data/market_analysis/hpk.sqlite"),
                        help="Файл состояния")
    parser.add_argument("--out", type=Path,
                        default=Path("data/market_analysis/hpk_bpk_zakupki.xlsx"),
                        help="Excel с результатом")
    parser.add_argument("--crawl-workers", type=int, default=6,
                        help="Параллельных запросов к SOAP-интеграции ЕИС")
    parser.add_argument("--doc-workers", type=int, default=12,
                        help="Потоков разбора документов")
    parser.add_argument("--rps", type=float, default=12.0,
                        help="Ограничение скорости скачивания файлов, запросов/с")
    parser.add_argument("--max-file-mb", type=int, default=DEFAULT_MAX_FILE_MB,
                        help="Файлы крупнее пропускаются. Замер на 930 разобранных "
                             "файлах крупнее 30 МБ: ни одной находки, при этом на "
                             "файлы крупнее 5 МБ приходится 91%% трафика")
    parser.add_argument("--max-tender-mb", type=int, default=DEFAULT_MAX_TENDER_MB,
                        help="Суммарный вес вложений, разбираемых у одной закупки. "
                             "Бюджет тратится в порядке приоритета: ТЗ и обоснование "
                             "НМЦК проходят, тяжёлый хвост отсекается")
    parser.add_argument("--max-priority", type=int, default=9,
                        help="Разбирать только документы не ниже приоритета: "
                             "0 — ТЗ и описание объекта, 1 — обоснование НМЦК, "
                             "2 — извещение и приложения, 3 — контракты и заявки, "
                             "9 — прочее. Отсечённое остаётся в очереди "
                             "и достанется прогону без этого флага")
    parser.add_argument("--limit", type=int, default=0,
                        help="Разобрать не больше N вложений за прогон (0 — все)")
    parser.add_argument("--ocr", action="store_true",
                        help="Проход по отложенным файлам: сканы через OCR, .doc "
                             "через LibreOffice. Медленно, запускать после быстрого")
    parser.add_argument("--no-ocr-pass", dest="with_ocr_pass", action="store_false",
                        help="В режиме run не запускать финальный проход OCR")
    parser.add_argument("--report-every", type=int, default=250,
                        help="Пересобирать Excel каждые N разобранных вложений")

    args = parser.parse_args(argv)
    args.regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    store = Store(args.db)
    try:
        {
            "crawl": crawl,
            "docs": scan_documents,
            "report": build_report,
            "stats": show_stats,
            "run": run_all,
        }[args.stage](store, args)
    finally:
        store.close()


if __name__ == "__main__":
    main()

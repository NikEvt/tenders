"""Какие вложения вообще стоит качать и разбирать.

У извещения бывает до нескольких десятков вложений, и они очень разные: ТЗ на
двадцать страниц и альбом чертежей на сорок мегабайт стоят одинакового
скачивания, но ценность их несопоставима. Прогон ХПК/БПК показал это в крайней
форме: четыре закупки приложили проектную документацию многотомными архивами по
~550 томов на 50 МБ — **84 ГБ бесполезной выкачки**, на которой скорость разбора
упала с 11 до 0.22 файла в секунду.

Отсюда четыре правила, и все они применяются **до скачивания**, по метаданным,
которые ЕИС отдаёт вместе с извещением.

**Приоритет.** ТЗ → обоснование НМЦК → приложения → контракты → прочее. Порядок
задумывался, чтобы при обрыве осталось самое ценное, и оправдался на данных:
125 находок из 176 пришли из приоритета 0, ещё 41 — из приоритета 1.

**Бюджет веса на закупку.** Лимита на файл мало: он ловит «один огромный файл»,
но не «тысяча средних от одного заказчика» — а случилось именно второе. Бюджет
расходуется в порядке приоритета, поэтому ТЗ и обоснование проходят всегда, а
обрезается тяжёлый хвост.

**Тома многотомных архивов.** Распаковать том по отдельности нельзя: `rarfile`
требует все тома сразу на диске, а вложения качаются по одному в память. Лимит
на файл не спасал — том ровно 50 МБ, аккуратно под порогом.

**Подписи и сертификаты.** `.sig`, `.p7s` и прочее — не документы.

Модуль чистый: ни SQL, ни сети, ни времени. Он отвечает на вопрос «что из этого
брать», а не «как это скачать».
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

#: Приоритет по имени файла и виду документа. Порядок проверки значим:
#: побеждает первый подошедший шаблон.
PRIORITY_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (0, re.compile(r"тех\w*\s*зад|\bТЗ\b|описани\w+\s+объект|техническ\w+\s+часть", re.I)),
    (1, re.compile(r"обоснован|НМЦ[КЦ]|расч[ёе]т", re.I)),
    (2, re.compile(r"извещени|документаци|приложени|смет|ведомост", re.I)),
    (3, re.compile(r"контракт|договор|заявк|инструкц|деклараци", re.I)),
)

#: Приоритет документа, не подошедшего ни под один шаблон.
DEFAULT_PRIORITY = 9

#: Том многотомного архива. Первый том тоже пропускается: без остальных он
#: разворачивается в обрезанный мусор.
MULTIVOLUME_RE = re.compile(
    r"\.part\d+\.(rar|zip|7z)$|\.[rz]\d{2,}$|\.7z\.\d{3,}$|\.zip\.\d{3,}$",
    re.IGNORECASE,
)

#: Криптоподписи и сертификаты — не документы, качать их незачем.
SIGNATURE_EXTENSIONS = frozenset({"sig", "p7s", "sgn", "cer", "crt", "der"})

#: Замер на живых данных: из 176 находок 173 пришли из файлов меньше 1 МБ, а
#: 930 разобранных файлов крупнее 30 МБ не дали ни одной. 60 МБ — с запасом.
DEFAULT_MAX_FILE_MB = 60

#: Потолок на закупку. Главный рычаг: в прогоне дал −90% трафика при сохранении
#: 97% файлов; в лимит упирались 49 закупок из 14 486.
DEFAULT_MAX_TENDER_MB = 30

MB = 1024 * 1024


class SkipReason(StrEnum):
    """Почему вложение не берут. Хранится рядом с документом ради воронки.

    Без разбивки по причинам «разобрано 115 тыс. из 198 тыс.» не говорит
    ничего: непонятно, то ли документы отсеяны осмысленно, то ли до них просто
    не дошли.
    """

    MULTIVOLUME = "multivolume"
    TOO_LARGE = "too_large"
    TENDER_BUDGET = "tender_budget"
    SIGNATURE = "signature"
    LOW_PRIORITY = "low_priority"
    NO_SOURCE = "no_source"

    @property
    def is_final(self) -> bool:
        """Отказ навсегда или до следующих настроек?

        Различие принципиальное. Том многотомного архива не станет пригодным
        оттого, что подняли бюджет, — это свойство самого файла. А «не влезло в
        бюджет», «слишком крупный» и «низкий приоритет» — свойства сегодняшних
        настроек, и помечать такие вложения отказом навсегда значит сделать
        обзорный проход необратимым: полный прогон их больше не увидит.

        Ретроспектива формулирует это правилом «отбор — запросом, а не пометкой
        в таблице»: невыбранное остаётся ждать.
        """
        return self in {SkipReason.MULTIVOLUME, SkipReason.SIGNATURE, SkipReason.NO_SOURCE}


@dataclass(frozen=True, slots=True)
class Candidate:
    """Вложение глазами политики допуска — только метаданные, без содержимого."""

    document_id: int
    file_name: str | None = None
    doc_kind_name: str | None = None
    file_size: int | None = None
    source_url: str | None = None
    #: Уже разобранные тоже расходуют бюджет, но заново не решаются.
    processed: bool = False

    @property
    def extension(self) -> str:
        name = (self.file_name or "").lower()
        return name.rsplit(".", 1)[-1] if "." in name else ""


@dataclass(frozen=True, slots=True)
class Decision:
    candidate: Candidate
    priority: int
    accepted: bool
    reason: SkipReason | None = None


def priority_of(file_name: str | None, doc_kind_name: str | None) -> int:
    """Чем раньше документ разбирают, тем ценнее он считается."""
    label = f"{file_name or ''} {doc_kind_name or ''}"
    for rank, pattern in PRIORITY_PATTERNS:
        if pattern.search(label):
            return rank
    return DEFAULT_PRIORITY


def is_multivolume(file_name: str | None) -> bool:
    return bool(MULTIVOLUME_RE.search(file_name or ""))


def is_signature(file_name: str | None) -> bool:
    name = (file_name or "").lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    return extension in SIGNATURE_EXTENSIONS


@dataclass(frozen=True, slots=True)
class AdmissionPolicy:
    """Решает судьбу всех вложений закупки разом.

    Разом — потому что бюджет общий: судьба конкретного файла зависит от того,
    что уже израсходовали более приоритетные. Решать по одному файлу за раз
    здесь просто нечем.
    """

    max_file_bytes: int = DEFAULT_MAX_FILE_MB * MB
    max_tender_bytes: int = DEFAULT_MAX_TENDER_MB * MB
    #: Обзорный проход: взять только самое ценное. Отсечённое не помечается
    #: отказом навсегда — следующий проход без ограничения его подберёт.
    max_priority: int = DEFAULT_PRIORITY

    def plan(self, candidates: Sequence[Candidate]) -> list[Decision]:
        """Решения по вложениям одной закупки, в порядке разбора.

        На вход идут **все** вложения закупки, включая разобранные: иначе
        возобновлённый прогон выдал бы закупке новый бюджет, и лимит перестал
        бы что-либо ограничивать. Разобранные бюджет тратят, но решения по ним
        не принимаются и наружу они не возвращаются.
        """
        ordered = sorted(
            candidates, key=lambda c: (priority_of(c.file_name, c.doc_kind_name), c.document_id)
        )

        spent = 0
        decisions: list[Decision] = []

        for candidate in ordered:
            priority = priority_of(candidate.file_name, candidate.doc_kind_name)
            size = candidate.file_size or 0

            if candidate.processed:
                # Уже разобранное считаем израсходованным независимо от того,
                # прошло бы оно по сегодняшним правилам или нет.
                spent += size
                continue

            reason = self._reject(candidate, priority, size, spent)
            if reason is None:
                spent += size

            decisions.append(
                Decision(
                    candidate=candidate,
                    priority=priority,
                    accepted=reason is None,
                    reason=reason,
                )
            )

        return decisions

    def _reject(
        self, candidate: Candidate, priority: int, size: int, spent: int
    ) -> SkipReason | None:
        if not candidate.source_url:
            return SkipReason.NO_SOURCE
        if is_signature(candidate.file_name):
            return SkipReason.SIGNATURE
        if is_multivolume(candidate.file_name):
            return SkipReason.MULTIVOLUME
        if priority > self.max_priority:
            return SkipReason.LOW_PRIORITY
        if size > self.max_file_bytes:
            return SkipReason.TOO_LARGE
        # Размер неизвестен — пропускаем: ЕИС не всегда отдаёт его в метаданных,
        # и считать такой файл бесконечно большим значило бы терять документы
        # на ровном месте. В бюджет он войдёт нулём, что чуть щедрее правды.
        if size and spent + size > self.max_tender_bytes:
            return SkipReason.TENDER_BUDGET
        return None

"""Общий SQL каталога: колонки, условия отбора и слияние выдач.

Вынесено из репозиториев, потому что список, поиск и (в дальнейшем) фасеты
обязаны отбирать закупки одинаково. Разъехавшиеся условия — это выдача, в
которой счётчик фасета не сходится со списком.
"""

from __future__ import annotations

import re

from sqlalchemy import Row, Select, and_, func, or_, select

from libs.shared.db.schema import Tender, TenderDocument
from libs.shared.db.tender_criteria import TenderCriteria, predicates
from services.api.domain.models import TenderFilter, TenderSummary
from services.api.domain.pagination import Cursor, SortKey, SortSpec, SortValue

# Пользовательский ввод не должен превращаться в синтаксис tsquery.
TSQUERY_OPERATORS = re.compile(r"[&|!()<>:*\"'\\]+")

RRF_K = 60


def clean_query(query: str) -> str:
    return " ".join(TSQUERY_OPERATORS.sub(" ", query).split())


# Счёт документов коррелированным подзапросом, а не отдельным запросом на строку:
# иначе страница из 20 закупок стоит 21 обращение к базе.
_DOCUMENT_COUNT = (
    select(func.count())
    .select_from(TenderDocument)
    .where(TenderDocument.tender_id == Tender.id)
    .correlate(Tender)
    .scalar_subquery()
    .label("document_count")
)


def summary_columns() -> Select:
    return select(
        Tender.id,
        Tender.reg_num,
        Tender.name,
        Tender.description,
        Tender.price,
        Tender.currency,
        Tender.customer_name,
        Tender.customer_inn,
        Tender.okpd2_code,
        Tender.okpd2_name,
        Tender.region_code,
        Tender.publish_date,
        Tender.start_date,
        Tender.end_date,
        Tender.prev_end_date,
        Tender.status,
        Tender.documents_status,
        _DOCUMENT_COUNT,
    )


def to_criteria(filters: TenderFilter) -> TenderCriteria:
    """Доменный фильтр шлюза → нейтральные критерии отбора.

    Отображение живёт здесь, на границе инфраструктуры: `domain` не должен
    знать ни про SQLAlchemy, ни про общий модуль отбора.
    """
    return TenderCriteria(
        text=filters.query,
        okpd2_prefixes=(filters.okpd2_prefix,) if filters.okpd2_prefix else (),
        regions=tuple(filters.regions),
        customer_inns=(filters.customer_inn,) if filters.customer_inn else (),
        price_min=filters.price_min,
        price_max=filters.price_max,
        published_since=filters.published_since,
        published_until=filters.published_until,
        only_active=filters.only_active,
        deadline_changed=filters.deadline_changed,
        documents_status=filters.documents_status,
        has_text=filters.has_text,
        filter_id=filters.filter_id,
        filter_verdicts=filters.filter_verdicts,
    )


def named_conditions(filters: TenderFilter) -> dict[str, object]:
    """Условия отбора, помеченные именем параметра запроса.

    Имя нужно подсказке на пустой выдаче: чтобы сказать «уберите `region` — без
    него нашлось бы 240», надо уметь собрать те же условия без одного из них.
    """
    return dict(predicates(to_criteria(filters)))


def conditions(filters: TenderFilter, without: str | None = None) -> list:
    predicates = named_conditions(filters)
    if without is not None:
        predicates.pop(without, None)
    return list(predicates.values()) or [True]


def to_summary(row: Row) -> TenderSummary:
    return TenderSummary(
        tender_id=row.id,
        reg_num=row.reg_num,
        name=row.name,
        description=row.description,
        price=row.price,
        currency=row.currency,
        customer_name=row.customer_name,
        customer_inn=row.customer_inn,
        okpd2_code=row.okpd2_code,
        okpd2_name=row.okpd2_name,
        region_code=row.region_code,
        publish_date=row.publish_date,
        start_date=row.start_date,
        end_date=row.end_date,
        prev_end_date=row.prev_end_date,
        status=row.status,
        documents_status=row.documents_status,
        document_count=row.document_count or 0,
    )


# Релевантности у строки каталога нет — сортировать по ней можно только выдачу
# поиска, поэтому здесь она сводится к дате публикации.
SORT_COLUMNS = {
    "published": Tender.publish_date,
    "relevance": Tender.publish_date,
    "price": Tender.price,
    "deadline": Tender.end_date,
    # Категорийные поля: по ним же работает и группировка (`?group=`).
    # Региона по названию в `tenders` нет — только код субъекта, поэтому
    # порядок здесь кодовый. См. web/docs/API-GAPS.md.
    "okpd": Tender.okpd2_code,
    "customer": Tender.customer_name,
    "region": Tender.region_code,
}

#: Человекочитаемая подпись группы, если ключ группировки — это код.
#: Регион в `tenders` названия не имеет, поэтому в шапке остаётся код, а имя
#: субъекта подставляет клиент по справочнику.
GROUP_LABELS = {
    "okpd": Tender.okpd2_name,
    "customer": Tender.customer_name,
}

#: Откуда брать значение ключа в отданной строке — для снятия курсора.
_ROW_FIELDS = {
    "published": "publish_date",
    "relevance": "publish_date",
    "price": "price",
    "deadline": "end_date",
    "okpd": "okpd2_code",
    "customer": "customer_name",
    "region": "region_code",
}


def sort_column(key: SortKey):
    return SORT_COLUMNS[key.field]


def order_by(sort: SortSpec) -> list:
    """Порядок по всем ключам и всегда — добор по id.

    Добор нужен не для красоты: значения ключей не уникальны, и без него
    строки с одинаковым регионом меняются местами между запросами, а курсор
    перестаёт быть надёжным. Направление добора всегда возрастающее —
    ровно то же, что клиент дописывает к своей строке сортировки, и на одно
    место рассинхрона меньше.
    """
    clauses = []
    for key in sort.keys:
        column = sort_column(key)
        clauses.append(column.asc().nullslast() if key.ascending else column.desc().nullslast())
    clauses.append(Tender.id.asc())
    return clauses


def _equal_to(key: SortKey, value: SortValue):
    column = sort_column(key)
    return column.is_(None) if value is None else column == value


def _after(key: SortKey, value: SortValue):
    """«Строго дальше по порядку» для одного ключа при NULLS LAST.

    NULL-ы стоят в хвосте: строка со значением идёт раньше любой строки с
    NULL, а из хвоста возврата к значениям уже нет — поэтому «дальше NULL-а»
    по этому ключу не существует ничего.
    """
    column = sort_column(key)
    if value is None:
        return None
    beyond = column > value if key.ascending else column < value
    return or_(beyond, column.is_(None))


def keyset_condition(cursor: Cursor):
    """Предикат «строго после позиции курсора» по всем ключам сразу.

    Лексикографика разворачивается в дизъюнкцию: либо первый ключ уже дальше,
    либо он равен и дальше второй, и так до добора по id. Записать это одним
    кортежным сравнением нельзя — направления ключей могут различаться, а
    NULLS LAST кортежное сравнение не понимает.
    """
    keys = cursor.sort.keys
    branches = []
    equalities = []

    for key, value in zip(keys, cursor.values, strict=True):
        beyond = _after(key, value)
        if beyond is not None:
            branches.append(and_(*equalities, beyond) if equalities else beyond)
        equalities.append(_equal_to(key, value))

    # Все ключи совпали — различает только добор.
    branches.append(and_(*equalities, Tender.id > cursor.tender_id))
    return or_(*branches)


def cursor_of(row: Row, sort: SortSpec) -> Cursor:
    return Cursor(
        sort=sort,
        values=tuple(getattr(row, _ROW_FIELDS[key.field]) for key in sort.keys),
        tender_id=row.id,
    )


def fuse(lexical: list[int], semantic: list[int]) -> list[int]:
    """Reciprocal Rank Fusion: смешивает два списка по позициям.

    Оценки лексического и векторного поиска несопоставимы напрямую, поэтому
    складываются ранги, а не веса.
    """
    scores: dict[int, float] = {}
    for position, tender_id in enumerate(lexical, start=1):
        scores[tender_id] = scores.get(tender_id, 0.0) + 1.0 / (RRF_K + position)
    for position, tender_id in enumerate(semantic, start=1):
        scores[tender_id] = scores.get(tender_id, 0.0) + 1.0 / (RRF_K + position)
    return sorted(scores, key=lambda tid: scores[tid], reverse=True)

"""Единственный ответ на вопрос «какие закупки подходят под эти условия».

Раньше ответов было два, и они расходились. Каталог сверял только первый код
ОКПД2 и недобирал; движок фильтров искал подстроку в склейке всех кодов и
перебирал — префикс `20.11` находил `26.20.11.110`, и LLM-судья получал ноутбуки
в кандидаты фильтра по газам.

Правило отбора — свойство схемы, а не какого-то одного сервиса, поэтому живёт
рядом со схемой. Сервисы держат свои доменные объекты (`TenderFilter`,
`FilterSpec`) и отображают их в нейтральные критерии на границе инфраструктуры:
так `domain` остаётся без SQLAlchemy, а знание об отборе не двоится.

Модуль умеет одно: превращать критерии в именованные предикаты. Ни запросов, ни
сессий, ни пагинации.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, exists, func, or_, select

from libs.shared.db.schema import (
    DocumentText,
    ResearchVerdict,
    SavedFilter,
    Tender,
)


@dataclass(frozen=True, slots=True)
class TenderCriteria:
    """Условия отбора в форме, не принадлежащей ни одному сервису.

    Осознанная выдумка: у шлюза и у движка фильтров свои доменные объекты, и
    сводить их друг к другу значило бы связать сервисы. Оба сводятся сюда.
    """

    text: str | None = None
    okpd2_prefixes: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    customer_inns: tuple[str, ...] = ()
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    published_since: date | None = None
    published_until: date | None = None
    only_active: bool = False
    deadline_changed: bool = False
    documents_status: str | None = None
    has_text: bool | None = None
    tender_ids: tuple[int, ...] = ()
    filter_id: int | None = None
    #: Какие вердикты считать прошедшими фильтр. Пустой кортеж — все.
    #: Не булев флаг: «покажи, что фильтр отклонил» — вопрос, который задают, а
    #: `matched_only=False` смешал бы отклонённые с прошедшими в одну кучу.
    filter_verdicts: tuple[str, ...] = ("confirmed",)
    extra: dict[str, ColumnElement[bool]] = field(default_factory=dict)


def predicates(criteria: TenderCriteria) -> dict[str, ColumnElement[bool]]:
    """Именованные условия отбора.

    Имя совпадает с параметром запроса: по нему подсказка на пустой выдаче
    собирает те же условия без одного из них, а фасеты — без правок при
    появлении нового условия.
    """
    result: dict[str, ColumnElement[bool]] = {}

    if criteria.text:
        # Полнотекстовый индекс, а не ILIKE: русская морфология иначе не
        # переживает падеж — «мебель» обязана находить «мебели».
        result["q"] = Tender.search_tsv.bool_op("@@")(
            func.websearch_to_tsquery("russian", criteria.text)
        )
    if criteria.okpd2_prefixes:
        result["okpd2"] = or_(*(_okpd2_prefix(p) for p in criteria.okpd2_prefixes))
    if criteria.regions:
        result["region"] = Tender.region_code.in_(criteria.regions)
    if criteria.customer_inns:
        result["customer_inn"] = Tender.customer_inn.in_(criteria.customer_inns)
    if criteria.price_min is not None:
        result["price_min"] = Tender.price >= criteria.price_min
    if criteria.price_max is not None:
        result["price_max"] = Tender.price <= criteria.price_max
    if criteria.published_since:
        result["since"] = Tender.publish_date >= datetime.combine(
            criteria.published_since, time.min
        )
    if criteria.published_until:
        result["until"] = Tender.publish_date < datetime.combine(
            criteria.published_until + timedelta(days=1), time.min
        )
    if criteria.only_active:
        result["only_active"] = or_(Tender.end_date.is_(None), Tender.end_date >= func.now())
    if criteria.deadline_changed:
        result["deadline_changed"] = and_(
            Tender.prev_end_date.is_not(None), Tender.prev_end_date != Tender.end_date
        )
    if criteria.documents_status:
        result["documents_status"] = Tender.documents_status == criteria.documents_status
    if criteria.has_text is not None:
        result["has_text"] = _has_text(criteria.has_text)
    if criteria.tender_ids:
        result["tender_ids"] = Tender.id.in_(criteria.tender_ids)
    if criteria.filter_id is not None:
        result["filter_id"] = _passed_filter(criteria.filter_id, criteria.filter_verdicts)

    result.update(criteria.extra)
    return result


def _okpd2_prefix(prefix: str) -> ColumnElement[bool]:
    """Совпадение префикса с любым кодом извещения — по началу кода.

    Извещение несёт несколько кодов, и нужный не обязан быть первым, поэтому
    проверяются оба поля. Но именно по началу: `LIKE '%20.11%'` по склейке
    кодов находит `26.20.11.110` и `45.20.11.519`, где префикс попадает в
    середину чужого кода.
    """
    code = func.unnest(Tender.okpd2_codes).column_valued("code")
    return or_(
        Tender.okpd2_code.like(f"{prefix}%"),
        exists(select(1).where(code.like(f"{prefix}%"))),
    )


def _has_text(expected: bool) -> ColumnElement[bool]:
    """Есть ли у закупки хоть один документ с извлечённым текстом.

    Отдельно от `documents_status`: тот агрегирует состояние обработки вложений
    и расходится с фактом наличия текста в обе стороны.
    """
    present = exists(select(1).where(DocumentText.tender_id == Tender.id))
    return present if expected else ~present


def _passed_filter(
    filter_id: int, confidences: tuple[str, ...]
) -> ColumnElement[bool]:
    """Закупки, разобранные по сохранённому критерию.

    Связь идёт через **версию критерия**, а не через идентификатор фильтра:
    вердикт принадлежит паре «закупка + критерий», а не запуску и не карточке
    фильтра. Благодаря этому правка шаблонов обесценивает прежние решения сама
    собой — новая версия просто не находит старых вердиктов.

    Вердикты перечисляются, а не сводятся к «только прошедшие»: аналитику нужно
    уметь спросить и то, что фильтр отклонил, — иначе проверить его работу
    можно только по тому, что он пропустил.
    """
    version = (
        select(SavedFilter.spec["version"].astext)
        .where(SavedFilter.id == filter_id)
        .scalar_subquery()
    )
    verdicts = select(ResearchVerdict.tender_id).where(
        ResearchVerdict.criteria_version == version
    )
    if confidences:
        verdicts = verdicts.where(ResearchVerdict.confidence.in_(confidences))
    return Tender.id.in_(verdicts.scalar_subquery())

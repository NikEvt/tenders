"""Каталог закупок: список, поиск, карточка."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query

from services.api.domain.models import DocumentsStatus, TenderFilter
from services.api.presentation.deps import (
    CatalogDep,
    CatalogFacets,
    CatalogGroups,
    GetTender,
    SearchDep,
    Similar,
    TenderEvents,
)
from services.api.presentation.pagination import PageParams
from services.api.presentation.schemas import (
    FacetsOut,
    GroupsOut,
    PageOut,
    SimilarOut,
    TenderDetailOut,
    TenderEventsOut,
)

router = APIRouter(tags=["Каталог"])


def build_filter(
    q: str | None,
    price_min: Decimal | None,
    price_max: Decimal | None,
    okpd2: str | None,
    region: list[str] | None,
    customer_inn: str | None,
    since: date | None,
    until: date | None,
    only_active: bool,
    deadline_changed: bool,
    documents_status: DocumentsStatus | None,
    has_text: bool | None,
    filter_id: int | None,
) -> TenderFilter:
    return TenderFilter(
        query=q,
        price_min=price_min,
        price_max=price_max,
        okpd2_prefix=okpd2,
        regions=region or [],
        customer_inn=customer_inn,
        published_since=since,
        published_until=until,
        only_active=only_active,
        deadline_changed=deadline_changed,
        documents_status=documents_status,
        has_text=has_text,
        filter_id=filter_id,
    )


@router.get("/tenders", response_model=PageOut)
async def list_tenders(
    catalog: CatalogDep,
    page: PageParams,
    q: str | None = None,
    price_min: Decimal | None = None,
    price_max: Decimal | None = None,
    okpd2: str | None = Query(default=None, description="Префикс кода ОКПД2"),
    region: list[str] | None = Query(default=None),  # noqa: B008
    customer_inn: str | None = None,
    since: date | None = None,
    until: date | None = None,
    only_active: bool = False,
    deadline_changed: bool = Query(default=False, description="Срок подачи сдвигался"),
    documents_status: DocumentsStatus | None = None,
    has_text: bool | None = Query(
        default=None, description="Есть ли у закупки распознанный текст документов"
    ),
    filter_id: int | None = Query(default=None, description="Только прошедшие LLM-фильтр"),
) -> PageOut:
    filters = build_filter(
        q, price_min, price_max, okpd2, region, customer_inn, since, until,
        only_active, deadline_changed, documents_status, has_text, filter_id,
    )
    return PageOut.of(await catalog.list(filters, page))


@router.get("/tenders/search", response_model=PageOut)
async def search_tenders(
    search: SearchDep,
    page: PageParams,
    q: str = Query(min_length=2, description="Запрос: лексика + смысл"),
    price_min: Decimal | None = None,
    price_max: Decimal | None = None,
    okpd2: str | None = None,
    region: list[str] | None = Query(default=None),  # noqa: B008
    since: date | None = None,
    until: date | None = None,
    only_active: bool = True,
) -> PageOut:
    """Гибридный поиск: находит и по точным словам, и по смыслу.

    Ищет в том числе по тексту приложенной документации — часть требований
    звучит только в ТЗ.
    """
    filters = build_filter(
        None, price_min, price_max, okpd2, region, None, since, until,
        only_active, False, None, None, None,
    )
    return PageOut.of(await search.search(q, filters, page))


@router.get("/tenders/facets", response_model=FacetsOut)
async def tender_facets(
    use_case: CatalogFacets,
    q: str | None = None,
    price_min: Decimal | None = None,
    price_max: Decimal | None = None,
    okpd2: str | None = None,
    region: list[str] | None = Query(default=None),  # noqa: B008
    customer_inn: str | None = None,
    since: date | None = None,
    until: date | None = None,
    only_active: bool = False,
    deadline_changed: bool = False,
    documents_status: DocumentsStatus | None = None,
    has_text: bool | None = Query(
        default=None, description="Есть ли у закупки распознанный текст документов"
    ),
    filter_id: int | None = None,
    explain_empty: bool = Query(
        default=False, description="Посчитать, какое условие отсекает больше всего"
    ),
) -> FacetsOut:
    """Счётчики по всей выдаче запроса, а не по текущей странице.

    Параметры те же, что у `/tenders`: фасеты обязаны описывать ровно ту
    выдачу, которую видит пользователь.

    Фасета «способ определения поставщика» здесь нет: ЕИС не передаёт его в
    `epNotificationEF2020`, и в `tenders` такой колонки не существует.
    """
    filters = build_filter(
        q, price_min, price_max, okpd2, region, customer_inn, since, until,
        only_active, deadline_changed, documents_status, has_text, filter_id,
    )
    facets, hint = await use_case.execute(filters, explain_empty)
    return FacetsOut.of(facets, hint)


@router.get("/tenders/groups", response_model=GroupsOut)
async def tender_groups(
    use_case: CatalogGroups,
    group: str = Query(description="Поле группировки: okpd | customer | region"),
    q: str | None = None,
    price_min: Decimal | None = None,
    price_max: Decimal | None = None,
    okpd2: str | None = None,
    region: list[str] | None = Query(default=None),  # noqa: B008
    customer_inn: str | None = None,
    since: date | None = None,
    until: date | None = None,
    only_active: bool = False,
    deadline_changed: bool = False,
    documents_status: DocumentsStatus | None = None,
    has_text: bool | None = Query(
        default=None, description="Есть ли у закупки распознанный текст документов"
    ),
    filter_id: int | None = None,
) -> GroupsOut:
    """Оглавление сгруппированного списка: счётчик и сумма НМЦК на группу.

    Считается по всей выдаче теми же условиями, что и `/tenders` — иначе
    сумма в шапке группы разойдётся со строками под ней.

    Порядок групп совпадает с порядком строк при `sort=<group>:asc,…`, так
    что клиенту достаточно вставлять шапку при смене ключа группы.
    """
    filters = build_filter(
        q, price_min, price_max, okpd2, region, customer_inn, since, until,
        only_active, deadline_changed, documents_status, has_text, filter_id,
    )
    return GroupsOut.of(group, await use_case.execute(filters, group))


@router.get("/tenders/{reg_num}", response_model=TenderDetailOut)
async def get_tender(reg_num: str, use_case: GetTender) -> TenderDetailOut:
    return TenderDetailOut.of(await use_case.execute(reg_num))


@router.get("/tenders/{reg_num}/similar", response_model=SimilarOut)
async def similar_tenders(
    reg_num: str,
    use_case: Similar,
    limit: int = Query(default=6, ge=1, le=50),
) -> SimilarOut:
    """Похожие закупки по «карточному» эмбеддингу.

    Пустой список — законный ответ: у свежей закупки вектора ещё нет.
    """
    return SimilarOut.of(await use_case.execute(reg_num, limit))


@router.get("/tenders/{reg_num}/events", response_model=TenderEventsOut)
async def tender_events(reg_num: str, use_case: TenderEvents) -> TenderEventsOut:
    """Событийный след закупки: что публиковалось, что дошло, что застряло.

    Статус выводится из outbox и таблицы обработанных, отдельной колонки нет:
    заводить её ради экрана значило бы дублировать то, что уже следует из данных.
    """
    return TenderEventsOut.of(await use_case.execute(reg_num))

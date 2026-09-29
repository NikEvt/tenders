"""Каталог и поиск через API-шлюз."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from libs.shared.db.schema import (
    DocumentChunk,
    DocumentText,
    ResearchHit,
    ResearchRun,
    ResearchVerdict,
    SavedFilter,
    Tender,
    TenderDocument,
)
from services.api.domain.models import TenderFilter
from services.api.domain.pagination import PageRequest, SortKey, SortSpec, decode_cursor
from services.api.infrastructure.db.catalog_repository import SqlCatalogRepository
from services.api.infrastructure.db.document_repository import SqlDocumentRepository
from services.api.infrastructure.db.facets_repository import SqlFacetsRepository
from services.api.infrastructure.db.queries import conditions
from services.api.infrastructure.db.search_repository import SqlSearchRepository

PREFIX = "TEST-API-"

#: Потолок страниц в обходе курсором. Считается от размера корпуса, а не
#: константой: корпус растёт с каждой выгрузкой, и фиксированный потолок
#: однажды уже превратил рабочий тест в падающий — обход просто не успевал
#: дойти до конца.
CURSOR_PAGE_SIZE = 150
CURSOR_PAGE_SLACK = 5


@pytest.fixture
async def catalog(session_factory):
    """Каталог из трёх закупок: две активные, одна с истёкшим сроком."""
    now = datetime.now(UTC)
    rows = [
        {
            "reg_num": f"{PREFIX}GAS",
            "name": "Поставка газа в баллонах",
            "description": "Кислород технический",
            "price": Decimal("950000"),
            "customer_name": "ГКУ Больница",
            "customer_inn": "7700000001",
            "okpd2_code": "20.11.11",
            "okpd2_name": "Газы промышленные",
            "region_code": "77",
            "publish_date": now - timedelta(days=2),
            "end_date": now + timedelta(days=10),
        },
        {
            "reg_num": f"{PREFIX}FURNITURE",
            "name": "Поставка офисной мебели",
            "description": "Столы и стулья",
            "price": Decimal("400000"),
            "customer_name": "Администрация",
            "customer_inn": "5000000001",
            "okpd2_code": "31.01.11",
            "region_code": "50",
            "publish_date": now - timedelta(days=1),
            "end_date": now + timedelta(days=5),
        },
        {
            "reg_num": f"{PREFIX}EXPIRED",
            "name": "Поставка газа технического",
            "price": Decimal("700000"),
            "customer_inn": "7700000009",
            "okpd2_code": "20.11.11",
            "region_code": "77",
            "publish_date": now - timedelta(days=40),
            "end_date": now - timedelta(days=2),
            # Срок подачи сдвигался — это отдельный фильтр в интерфейсе.
            "prev_end_date": now - timedelta(days=10),
        },
    ]

    async with session_factory() as session, session.begin():
        ids = {}
        for row in rows:
            tender_id = await session.scalar(
                Tender.__table__.insert().values(**row).returning(Tender.id)
            )
            ids[row["reg_num"]] = tender_id

        document_id = await session.scalar(
            TenderDocument.__table__.insert()
            .values(
                tender_id=ids[f"{PREFIX}FURNITURE"],
                attachment_id="TZ",
                file_name="ТЗ.pdf",
                # Копии файла система не хранит — остаётся ссылка на оригинал.
                source_url="https://zakupki.gov.ru/file.html?uid=TZ",
                extraction_status="done",
                page_count=4,
                ocr_used=True,
            )
            .returning(TenderDocument.id)
        )
        await session.execute(
            DocumentText.__table__.insert().values(
                document_id=document_id,
                tender_id=ids[f"{PREFIX}FURNITURE"],
                content="Мебель должна выдерживать обработку хлоргексидином.",
                char_count=52,
            )
        )
        await session.execute(
            DocumentChunk.__table__.insert().values(
                document_id=document_id,
                tender_id=ids[f"{PREFIX}FURNITURE"],
                chunk_index=0,
                text="Мебель должна выдерживать обработку хлоргексидином.",
                page_from=2,
            )
        )

        filter_id = await session.scalar(
            SavedFilter.__table__.insert()
            .values(
                name="Газ",
                # Версия критерия — она и связывает фильтр с вердиктами.
                spec={
                    "name": "Газ",
                    "version": "тест-v1",
                    "terms": [{"name": "газ", "pattern": "газ"}],
                },
            )
            .returning(SavedFilter.id)
        )
        # Вердикты движка отбора: карточка закупки читает их, а не таблицу
        # прежнего движка фильтров.
        for reg, confidence, reason in (
            (f"{PREFIX}GAS", "confirmed", "поставка газа"),
            (f"{PREFIX}FURNITURE", "rejected", "название объекта"),
        ):
            await session.execute(
                ResearchVerdict.__table__.insert().values(
                    tender_id=ids[reg],
                    criteria_version="тест-v1",
                    prompt_version="hits-judge-v1",
                    confidence=confidence,
                    reason=reason,
                    score=0.9 if confidence == "confirmed" else 0.05,
                    decided_by="rules",
                )
            )
        await session.execute(
            ResearchRun.__table__.insert().values(
                id=990001,
                name="тест",
                criteria_version="тест-v1",
                criteria={},
                status="done",
            )
        )
        await session.execute(
            ResearchHit.__table__.insert().values(
                run_id=990001,
                tender_id=ids[f"{PREFIX}FURNITURE"],
                term="мебель",
                role="primary",
                quote="Мебель должна выдерживать обработку хлоргексидином.",
                match_start=0,
                match_end=6,
                file_name="ТЗ.pdf",
            )
        )

    yield {"ids": ids, "filter_id": filter_id, "document_id": document_id}

    async with session_factory() as session, session.begin():
        await session.execute(delete(ResearchRun).where(ResearchRun.id == 990001))
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))
        await session.execute(delete(SavedFilter).where(SavedFilter.id == filter_id))


async def _page_budget(session_factory, page_size: int) -> int:
    """Сколько страниц хватит, чтобы обойти корпус, плюс запас.

    Запас нужен на строки, добавленные другими фикстурами по ходу прогона;
    он же остаётся защитой от бесконечного цикла, если курсор встанет.
    """
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(Tender)) or 0
    return total // max(page_size, 1) + CURSOR_PAGE_SLACK


def repository(session_factory) -> SqlCatalogRepository:
    return SqlCatalogRepository(session_factory)


def search_repository(session_factory) -> SqlSearchRepository:
    # Без эмбеддера: проверяем лексическую часть гибридного поиска.
    return SqlSearchRepository(session_factory, repository(session_factory), embedder=None)


def documents(session_factory) -> SqlDocumentRepository:
    return SqlDocumentRepository(session_factory)


def reg_nums(page) -> set[str]:
    return {t.reg_num for t in page.items if t.reg_num.startswith(PREFIX)}


@pytest.mark.asyncio
async def test_listing_is_paginated_with_total(session_factory, catalog) -> None:
    page = await repository(session_factory).list(TenderFilter(), PageRequest(limit=2))

    assert len(page.items) == 2
    assert page.total >= 3
    assert page.total_pages >= 2


@pytest.mark.asyncio
async def test_price_and_region_filters(session_factory, catalog) -> None:
    page = await repository(session_factory).list(
        TenderFilter(price_max=Decimal("500000"), regions=["50"]), PageRequest(limit=50)
    )
    assert reg_nums(page) == {f"{PREFIX}FURNITURE"}


@pytest.mark.asyncio
async def test_only_active_excludes_expired(session_factory, catalog) -> None:
    page = await repository(session_factory).list(
        TenderFilter(only_active=True, okpd2_prefix="20.11"), PageRequest(limit=50)
    )
    assert f"{PREFIX}EXPIRED" not in reg_nums(page)
    assert f"{PREFIX}GAS" in reg_nums(page)


@pytest.mark.asyncio
async def test_deadline_changed_filter(session_factory, catalog) -> None:
    # Сужаем до ОКПД2 фикстуры: со сдвинутым сроком в общей базе живут сотни
    # настоящих закупок, и на странице в 50 строк своя просто не помещалась.
    page = await repository(session_factory).list(
        TenderFilter(deadline_changed=True, okpd2_prefix="20.11"),
        PageRequest(limit=50),
    )
    assert reg_nums(page) == {f"{PREFIX}EXPIRED"}
    # Признак вычисляется из prev_end_date, а не приходит из базы.
    assert all(item.deadline_changed for item in page.items)


@pytest.mark.asyncio
async def test_filter_id_returns_only_matched(session_factory, catalog) -> None:
    """Выдача по ИИ-фильтру должна содержать только прошедшие проверку закупки."""
    page = await repository(session_factory).list(
        TenderFilter(filter_id=catalog["filter_id"]),
        PageRequest(limit=50),
    )
    assert reg_nums(page) == {f"{PREFIX}GAS"}


@pytest.mark.asyncio
async def test_filter_id_can_show_what_was_rejected(session_factory, catalog) -> None:
    """Проверить фильтр по тому, что он отсёк, — отдельный и нужный вопрос."""
    page = await repository(session_factory).list(
        TenderFilter(filter_id=catalog["filter_id"], filter_verdicts=("rejected",)),
        PageRequest(limit=50),
    )
    assert reg_nums(page) == {f"{PREFIX}FURNITURE"}


@pytest.mark.asyncio
async def test_filter_id_can_show_everything_it_judged(session_factory, catalog) -> None:
    page = await repository(session_factory).list(
        TenderFilter(filter_id=catalog["filter_id"], filter_verdicts=()),
        PageRequest(limit=50),
    )
    assert reg_nums(page) == {f"{PREFIX}GAS", f"{PREFIX}FURNITURE"}


@pytest.mark.asyncio
async def test_search_applies_the_saved_filter(session_factory, catalog) -> None:
    """Условие, показанное в интерфейсе, обязано действовать и в поиске."""
    page = await search_repository(session_factory).search(
        "газ",
        TenderFilter(filter_id=catalog["filter_id"]),
        PageRequest(limit=20),
    )
    assert f"{PREFIX}FURNITURE" not in reg_nums(page)


@pytest.mark.asyncio
async def test_search_finds_text_inside_documents(session_factory, catalog) -> None:
    """Требование звучит только в ТЗ — в карточке слова «хлоргексидин» нет."""
    page = await search_repository(session_factory).search(
        "хлоргексидином", TenderFilter(only_active=True), PageRequest(limit=20)
    )
    assert f"{PREFIX}FURNITURE" in reg_nums(page)
    assert page.items[0].relevance is not None


@pytest.mark.asyncio
async def test_search_survives_operator_characters(session_factory, catalog) -> None:
    """Пользователь может ввести что угодно — поиск не должен падать."""
    page = await search_repository(session_factory).search(
        "газ &&& !!! ()", TenderFilter(), PageRequest(limit=20)
    )
    assert isinstance(page.total, int)


@pytest.mark.asyncio
async def test_detail_includes_documents_and_verdicts(session_factory, catalog) -> None:
    detail = await repository(session_factory).get(f"{PREFIX}FURNITURE")

    assert detail is not None
    assert detail.summary.document_count == 1
    assert detail.documents[0].file_name == "ТЗ.pdf"
    assert detail.documents[0].ocr_used is True
    assert detail.documents[0].has_text is True
    verdict = detail.verdicts[0]
    assert verdict["confidence"] == "rejected"
    # Видно, во что обошлось решение: правила бесплатны, модель — нет.
    assert verdict["decided_by"] == "rules"
    # Цитата приезжает со смещением — иначе её негде подсветить.
    hit = verdict["hits"][0]
    assert hit["quote"][hit["match_start"] : hit["match_end"]] == "Мебель"


@pytest.mark.asyncio
async def test_missing_tender_returns_none(session_factory, catalog) -> None:
    assert await repository(session_factory).get("НЕТ-ТАКОГО") is None


@pytest.mark.asyncio
async def test_document_key_and_text(session_factory, catalog) -> None:
    repo = documents(session_factory)
    found = await repo.source(catalog["document_id"])

    # Копии вложения система не держит — ссылка ведёт в ЕИС.
    assert found is not None
    assert found[0].startswith("https://")

    # Текст ещё не перенесён в хранилище: лежит в базе, и это законный вариант,
    # пока миграция 0007 не сняла колонку.
    location = await repo.text_location(catalog["document_id"])
    assert location is not None
    assert location.inline is not None and "хлоргексидином" in location.inline


# ─── Волна 1: сортировка, курсор, фасеты ──────────────────────────────────────


def facets_repository(session_factory) -> SqlFacetsRepository:
    return SqlFacetsRepository(session_factory)


@pytest.mark.asyncio
async def test_sort_by_price(session_factory, catalog) -> None:
    ascending = await repository(session_factory).list(
        TenderFilter(okpd2_prefix="20.11"),
        PageRequest(limit=50, sort=SortSpec(field="price", ascending=True)),
    )
    prices = [t.price for t in ascending.items if t.reg_num.startswith(PREFIX)]

    assert prices == sorted(prices)
    assert prices[0] == Decimal("700000.00")


@pytest.mark.asyncio
async def test_cursor_walks_every_row_exactly_once(session_factory, catalog) -> None:
    """Ключевое свойство keyset-пагинации: без пропусков и без повторов.

    Проверяется на всей таблице, а не на трёх строках фикстуры: именно на
    объёме и проявляются ошибки в предикате «строго после этой строки».
    """
    repo = repository(session_factory)
    sort = SortSpec(field="published", ascending=False)
    filters = TenderFilter()

    seen: list[str] = []
    request = PageRequest(limit=CURSOR_PAGE_SIZE, sort=sort)
    for _ in range(await _page_budget(session_factory, CURSOR_PAGE_SIZE)):
        page = await repo.list(filters, request)
        seen.extend(t.reg_num for t in page.items)
        if page.next_cursor is None:
            break
        request = PageRequest(
            limit=CURSOR_PAGE_SIZE, cursor=decode_cursor(page.next_cursor, sort), sort=sort
        )
    else:
        pytest.fail("Обход не завершился: курсор не дошёл до конца выдачи")

    assert len(seen) == len(set(seen)), "курсор выдал строку дважды"
    # Все строки фикстуры встретились ровно по одному разу.
    ours = [reg_num for reg_num in seen if reg_num.startswith(PREFIX)]
    assert sorted(ours) == sorted(
        [f"{PREFIX}GAS", f"{PREFIX}FURNITURE", f"{PREFIX}EXPIRED"]
    )


@pytest.mark.asyncio
async def test_sort_by_customer_puts_rows_without_one_last(session_factory, catalog) -> None:
    """Категорийная сортировка и NULLS LAST.

    Проверяется на всей выдаче, а не на трёх строках фикстуры: свойство
    «пустые в хвосте» — про порядок целиком, и на подвыборке оно ничего
    не значит.
    """
    page = await repository(session_factory).list(
        TenderFilter(),
        PageRequest(limit=1000, sort=SortSpec(field="customer", ascending=True)),
    )
    names = [t.customer_name for t in page.items]
    filled = [name for name in names if name is not None]

    # Ни одного заполненного имени после первого пустого.
    assert None not in names[: len(filled)]
    assert names[len(filled) :] == [None] * (len(names) - len(filled))

    # Сам алфавитный порядок здесь не сверяется: его задаёт collation базы, и
    # пересортировка в Python сравнивала бы кодовые точки с правилами локали.
    # Что категорийный ключ не чередуется, проверяет соседний тест.


@pytest.mark.asyncio
async def test_group_key_leads_the_order(session_factory, catalog) -> None:
    """Группировка — это тот же запрос с ключом группы впереди.

    Строки одной категории идут подряд, а внутри категории работает
    выбранная сортировка, а не порядок вставки.
    """
    page = await repository(session_factory).list(
        TenderFilter(),
        PageRequest(
            limit=1000,
            sort=SortSpec(
                field="okpd",
                ascending=True,
                rest=(SortKey(field="price", ascending=False),),
            ),
        ),
    )

    # Категория не чередуется: встретив её второй раз, мы бы увидели повтор.
    codes = [t.okpd2_code for t in page.items]
    seen: set[str | None] = set()
    for code, following in zip(codes, [*codes[1:], object()], strict=True):
        if code != following:
            assert code not in seen, f"категория {code} встретилась дважды"
            seen.add(code)

    # Внутри каждой категории цена не возрастает.
    for index, item in enumerate(page.items[1:], start=1):
        previous = page.items[index - 1]
        if previous.okpd2_code != item.okpd2_code:
            continue
        if previous.price is None or item.price is None:
            continue
        assert previous.price >= item.price


@pytest.mark.asyncio
async def test_cursor_walks_every_row_once_under_a_group_key(session_factory, catalog) -> None:
    """Ключевое свойство keyset-пагинации, но уже на составном ключе.

    Именно здесь ломается наивная реализация: предикат «строго после» для
    нескольких ключей — это дизъюнкция, а не покомпонентное сравнение, и
    на поле с малым числом значений (ОКПД2) ошибка сразу даёт повторы.
    """
    repo = repository(session_factory)
    sort = SortSpec(
        field="okpd",
        ascending=True,
        rest=(SortKey(field="price", ascending=False),),
    )
    filters = TenderFilter()

    seen: list[str] = []
    GROUPED_PAGE = 37
    request = PageRequest(limit=GROUPED_PAGE, sort=sort)
    for _ in range(await _page_budget(session_factory, GROUPED_PAGE)):
        page = await repo.list(filters, request)
        seen.extend(t.reg_num for t in page.items)
        if page.next_cursor is None:
            break
        request = PageRequest(limit=37, cursor=decode_cursor(page.next_cursor, sort), sort=sort)
    else:
        pytest.fail("Обход не завершился: курсор не дошёл до конца выдачи")

    assert len(seen) == len(set(seen)), "курсор выдал строку дважды"

    # Сравнивать надо ровно с тем же множеством строк, что обошёл курсор.
    # Фиксированный `limit=1000` работал, пока таблица была меньше тысячи строк,
    # и разошёлся, как только в базе появилась настоящая выгрузка: курсор
    # обходил больше, чем отдавала одна offset-страница.
    by_offset = await repo.list(filters, PageRequest(limit=len(seen), sort=sort))
    assert seen == [t.reg_num for t in by_offset.items], "курсор и offset разошлись в порядке"


@pytest.mark.asyncio
async def test_group_headers_agree_with_the_rows_under_them(session_factory, catalog) -> None:
    """Шапка считается по всей выдаче — и обязана сойтись со строками.

    Расходящиеся счётчик и сумма хуже отсутствующих: они выглядят
    достоверно. Поэтому сверяются с самой выдачей, а не с константой.
    """
    filters = TenderFilter(okpd2_prefix="20.11")
    page = await repository(session_factory).list(
        filters,
        PageRequest(limit=1000, sort=SortSpec(field="okpd", ascending=True)),
    )
    buckets = await facets_repository(session_factory).groups(filters, "okpd")

    expected_counts: dict[str, int] = {}
    expected_sums: dict[str, Decimal] = {}
    for item in page.items:
        key = item.okpd2_code or ""
        expected_counts[key] = expected_counts.get(key, 0) + 1
        if item.price is not None:
            expected_sums[key] = expected_sums.get(key, Decimal(0)) + item.price

    assert {b.key: b.count for b in buckets} == expected_counts
    assert {b.key: b.total_price for b in buckets if b.total_price is not None} == expected_sums

    gas = next(b for b in buckets if b.key == "20.11.11")
    assert gas.label == "Газы промышленные"


@pytest.mark.asyncio
async def test_groups_follow_the_same_order_as_the_list(session_factory, catalog) -> None:
    """Иначе шапки шли бы в одном порядке, а строки под ними — в другом."""
    filters = TenderFilter()
    buckets = await facets_repository(session_factory).groups(filters, "okpd")
    page = await repository(session_factory).list(
        filters,
        PageRequest(limit=1000, sort=SortSpec(field="okpd", ascending=True)),
    )

    from_rows: list[str] = []
    for item in page.items:
        key = item.okpd2_code or ""
        if not from_rows or from_rows[-1] != key:
            from_rows.append(key)

    # Первая страница короче выдачи — сверяем начало списка шапок.
    assert [b.key for b in buckets][: len(from_rows)] == from_rows


@pytest.mark.asyncio
async def test_cursor_and_offset_agree(session_factory, catalog) -> None:
    repo = repository(session_factory)
    sort = SortSpec(field="price", ascending=False)
    filters = TenderFilter(okpd2_prefix="20.11")

    first = await repo.list(filters, PageRequest(limit=1, sort=sort))
    assert first.next_cursor is not None

    by_cursor = await repo.list(
        filters, PageRequest(limit=1, cursor=decode_cursor(first.next_cursor, sort), sort=sort)
    )
    by_offset = await repo.list(filters, PageRequest(limit=1, offset=1, sort=sort))

    assert [t.reg_num for t in by_cursor.items] == [t.reg_num for t in by_offset.items]


@pytest.mark.asyncio
async def _matching(session_factory, filters: TenderFilter, column) -> int:
    """Сколько строк выдачи несут это поле — по всей выборке, а не по странице.

    Фасеты считаются по всей выдаче, поэтому и сверять их надо с ней. Сверка со
    страницей держалась, только пока выдача была короче страницы: на корпусе в
    сто тысяч извещений условие `20.11` даёт больше пятидесяти строк, и тест
    начинал падать на росте данных, а не на дефекте. Та же ошибка уже была в
    обходе курсором — там она исправлена так же.
    """
    async with session_factory() as session:
        return await session.scalar(
            select(func.count())
            .select_from(Tender)
            .where(*conditions(filters), column.is_not(None))
        )


@pytest.mark.asyncio
async def test_facets_agree_with_listing(session_factory, catalog) -> None:
    """Счётчик фасета и число «найдено» обязаны сходиться — иначе врут оба."""
    filters = TenderFilter(okpd2_prefix="20.11")

    page = await repository(session_factory).list(filters, PageRequest(limit=50))
    facets = await facets_repository(session_factory).facets(filters)

    assert facets.total == page.total
    # Строки без региона в фасет не попадают, поэтому сумма не больше общего числа.
    # Хвост фасета обрезан `FACET_LIMIT`, поэтому сумма не превышает выдачу.
    with_region = await _matching(session_factory, filters, Tender.region_code)
    assert 0 < sum(b.count for b in facets.regions) <= with_region
    regions = {b.key: b.count for b in facets.regions}
    assert regions["77"] >= 2


@pytest.mark.asyncio
async def test_price_histogram_covers_all_priced_rows(session_factory, catalog) -> None:
    filters = TenderFilter(okpd2_prefix="20.11")

    facets = await facets_repository(session_factory).facets(filters)
    priced = await _matching(session_factory, filters, Tender.price)

    # Ни одна строка не теряется: максимум попадает в последний столбец,
    # а не выпадает за границу гистограммы.
    assert sum(b.count for b in facets.price_histogram) == priced


@pytest.mark.asyncio
async def test_restrictive_names_the_condition_that_cuts_most(session_factory, catalog) -> None:
    # Код «99» субъектом не является, поэтому строк с ним в корпусе нет и
    # быть не может. Раньше здесь стоял регион «50», и подсказка меняла ответ,
    # едва в базе появлялись настоящие подмосковные закупки.
    filters = TenderFilter(okpd2_prefix="20.11", regions=["99"])

    hint = await facets_repository(session_factory).restrictive(filters)

    # Ни одной закупки в регионе «99» нет — выдача пустая, и виноват регион.
    assert hint is not None
    assert hint.param == "region"
    assert hint.dropped > 0


@pytest.mark.asyncio
async def test_restrictive_is_none_without_conditions(session_factory, catalog) -> None:
    assert await facets_repository(session_factory).restrictive(TenderFilter()) is None


@pytest.mark.asyncio
async def test_search_does_not_return_the_whole_corpus(session_factory, catalog) -> None:
    """Векторная ветка обязана отсекать по близости, а не отдавать всех подряд.

    До введения порога запрос «мебель» возвращал 302 закупки из 302 имеющих
    эмбеддинг: `SEMANTIC_POOL` больше корпуса, и «ближайшие» оказывались всеми.
    Проверяется без эмбеддера — значит, векторной ветки нет вовсе, и выдача
    ограничена лексикой; это нижняя граница здравого смысла.
    """
    page = await search_repository(session_factory).search(
        "мебель", TenderFilter(), PageRequest(limit=200)
    )

    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(Tender))

    assert page.total < total, "поиск вернул весь каталог"


"""Отбор по префиксу ОКПД2 — ровно один раз и ровно так.

Раньше реализаций было две: каталог сверял только первый код извещения, движок
фильтров искал подстроку в склейке всех кодов. Первое недобирало, второе
перебирало — из-за второго судья получал ноутбуки (`26.20.11.110`) в кандидаты
фильтра с префиксом `20.11`. Тест сравнивал их между собой.

Сравнивать больше не с чем: движок фильтров переписан и своей реализации отбора
не имеет — он пользуется тем же `libs/shared/db/tender_criteria.py`. Инвариант
«две реализации согласны» выполняется теперь не проверкой, а тем, что вторая
реализация исчезла. Здесь осталось то, что по-прежнему можно нарушить правкой:
сами правила совпадения префикса.
"""

from __future__ import annotations

import pytest
from sqlalchemy import and_, delete, select

from libs.shared.db.schema import Tender
from services.api.domain.models import TenderFilter
from services.api.infrastructure.db.queries import conditions as catalog_conditions

PREFIX = "TEST-MATCH-"

# Каждая строка подобрана под конкретную ошибку отбора.
FIXTURE = [
    # Обычный случай: код в обоих полях. Находят обе реализации.
    ("PLAIN", "20.11.11", ["20.11.11"], "Поставка кислорода технического"),
    # Нужный код стоит не первым. Каталог его не видит.
    ("SECOND", "62.02.30", ["62.02.30", "62.01.11"], "Разработка программного обеспечения"),
    # «20.11» лежит внутри другого кода. Подстрочный поиск ловит это ошибочно.
    ("INSIDE", "26.20.15.140", ["26.20.15.140", "26.20.11.110"], "Поставка ноутбуков"),
    # То же, но совпадение попадает на границу склейки через запятую.
    ("GLUED", "45.20.11.519", ["45.20.11.519"], "Ремонт помещений"),
    # Морфология: в названии «мебели», запрос будет «мебель».
    ("MORPH", "31.01.11", ["31.01.11"], "Поставка офисной мебели для нужд учреждения"),
]

# Ожидаемый ответ на префикс — по началу кода, а не по вхождению подстроки.
EXPECTED = {
    "20.11": {"PLAIN"},
    "62.01": {"SECOND"},
    "26.20": {"INSIDE"},
    "31.01": {"MORPH"},
}


@pytest.fixture
async def catalog(session_factory):
    async with session_factory() as session, session.begin():
        for suffix, code, codes, name in FIXTURE:
            await session.execute(
                Tender.__table__.insert().values(
                    reg_num=f"{PREFIX}{suffix}",
                    name=name,
                    okpd2_code=code,
                    okpd2_codes=codes,
                    region_code="77",
                )
            )
    yield
    async with session_factory() as session, session.begin():
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))


async def _matching(session_factory, predicates: list) -> set[str]:
    """Реестровые номера строк фикстуры, прошедшие условия."""
    async with session_factory() as session:
        rows = await session.scalars(
            select(Tender.reg_num).where(
                and_(*predicates), Tender.reg_num.like(f"{PREFIX}%")
            )
        )
    return {reg_num.removeprefix(PREFIX) for reg_num in rows.all()}


def _catalog(prefix: str) -> list:
    return catalog_conditions(TenderFilter(okpd2_prefix=prefix))


@pytest.mark.parametrize("prefix", sorted(EXPECTED))
@pytest.mark.asyncio
async def test_catalog_matches_any_code_by_prefix(session_factory, catalog, prefix) -> None:
    """Префикс ОКПД2 совпадает с любым кодом извещения, а не только с первым."""
    assert await _matching(session_factory, _catalog(prefix)) == EXPECTED[prefix]


@pytest.mark.asyncio
async def test_prefix_does_not_match_inside_another_code(session_factory, catalog) -> None:
    """`20.11` не должен находить `26.20.11.110` и `45.20.11.519`.

    Именно из-за этого совпадения судья получал ноутбуки в кандидаты фильтра
    «Газ в баллонах».
    """
    found = await _matching(session_factory, _catalog("20.11"))
    assert "INSIDE" not in found, "найден код внутри другого кода"
    assert "GLUED" not in found, "найдено совпадение на склейке"


@pytest.mark.asyncio
async def test_text_filter_survives_morphology(session_factory, catalog) -> None:
    """Запрос в начальной форме обязан находить словоформу в тексте.

    В названии стоит «мебели»; `ILIKE '%мебель%'` его не находит, и каталог
    отдаёт пустую выдачу там, где закупка есть.
    """
    found = await _matching(session_factory, catalog_conditions(TenderFilter(query="мебель")))
    assert found == {"MORPH"}

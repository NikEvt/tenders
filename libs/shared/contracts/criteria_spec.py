"""Спецификация критерия отбора — контракт между сервисами.

Критерий рождается в `llm-service` (компиляция свободного текста), лежит в
`saved_filters.spec` и применяется движком отбора. Три участника, один формат —
значит это контракт, и место ему рядом с событиями, а не внутри чьего-то домена.

Здесь только **форма**: строки шаблонов, роли, окна. Компиляция шаблонов,
поиск и решения живут в `services/research/domain/` — сюда они не переезжают,
иначе `libs.shared` превратится в свалку доменной логики.

Формат заменил прежний `FilterSpec` (ключевые слова + семантический запрос +
критерий для судьи). Причина в замере: точность держится не на ключевых словах,
а на правилах по контексту, и вывести их из списка слов невозможно.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, WithJsonSchema

# Pydantic описывает Decimal строковым паттерном с look-ahead, а серверы
# структурного вывода компилируют схему в грамматику и на look-around падают.
# Деньги остаются Decimal в Python — модели отдаём простое число.
Money = Annotated[Decimal | None, WithJsonSchema({"type": ["number", "null"]})]


class TermSpec(BaseModel):
    """Термин: что искать в тексте.

    `role` решает, значит ли термин что-нибудь сам по себе. Вспомогательный не
    значит: закупка, где сработали только такие, отвергается целиком. Замер на
    размеченном наборе: шесть медицинских закупок из двадцати ложных сработали
    ровно на вспомогательном «потребление кислорода», и ни одна подтверждённая
    на нём одном не держалась.
    """

    name: str
    #: Регулярное выражение. Применяется без учёта регистра.
    pattern: str
    role: Literal["primary", "supporting"] = "primary"


class ContextRuleSpec(BaseModel):
    """Правило по окружению совпадения.

    `window` — сколько символов вокруг совпадения смотреть. У правил отказа он
    должен быть узким: «ХПК Мариинского театра» опознаётся по слову в трёх
    словах от аббревиатуры, а на всей цитате в ±220 символов найдётся что
    угодно. `null` — смотреть цитату целиком.
    """

    name: str
    pattern: str
    verdict: Literal["confirmed", "rejected"] = "rejected"
    window: int | None = None


class StructuralSpec(BaseModel):
    """Дешёвые условия, которые проверяются запросом к базе.

    Отделены от терминов намеренно: они не про текст, а про карточку, и стоят
    ничего. Сузить корпус ими до чтения документов — самая дешёвая экономия из
    возможных.
    """

    regions: list[str] = Field(default_factory=list)
    customer_inns: list[str] = Field(default_factory=list)
    price_min: Money = None
    price_max: Money = None
    only_active: bool = False


class CriteriaSpec(BaseModel):
    """Полное описание того, что ищут."""

    name: str = ""
    terms: list[TermSpec] = Field(default_factory=list)
    context_rules: list[ContextRuleSpec] = Field(default_factory=list)
    #: Предфильтр по карточке извещения: сужает круг до закупок, где упоминание
    #: вообще возможно. Намеренно широкий — пропущенная закупка не вернётся, а
    #: лишняя стоит одного чтения.
    card_pattern: str | None = None
    #: Коды ОКПД2, при которых тема возможна даже при нейтральном названии.
    okpd2_prefixes: list[str] = Field(default_factory=list)
    #: Структурные условия по карточке — бюджет, регион, заказчик.
    structural: StructuralSpec = Field(default_factory=StructuralSpec)
    #: Версия критерия — часть ключа кэша вердиктов. Правка шаблонов обязана
    #: обесценить прежние решения, а не смешаться с ними.
    version: str = "v1"

    @property
    def is_usable(self) -> bool:
        """Критерий без основных терминов не найдёт ничего.

        Проверяется до сохранения: фильтр, который молча ничего не находит,
        неотличим от фильтра, под который ничего не подошло.
        """
        return any(term.role == "primary" for term in self.terms)

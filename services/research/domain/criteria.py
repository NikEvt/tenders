"""Из чего состоит критерий отбора.

Regex находит последовательность букв, а не смысл, и на трёхбуквенных
аббревиатурах это проявляется в полный рост: в прогоне ХПК/БПК треть суммы
сырого результата оказалась мусором. Поэтому критерий — не один шаблон, а три
взаимодействующие части.

**Термины с ролями.** «ХПК» и «БПК» — основные: их достаточно, чтобы закупку
стоило рассматривать. «Потребление кислорода» — вспомогательный: в одиночку он
не значит ничего. Это не догадка, а замер по размеченному набору: из 20
отклонённых закупок **шесть** сработали только на нём и все шесть оказались
медицинскими, а из 56 подтверждённых на нём одном не держится **ни одна**.

**Правила по контексту.** Рядом с совпадением почти всегда видно, о чём речь:
`мг/дм³`, `ПДК`, `сточные воды` — химия воды; `кровля`, `цех`, `СИЗО`,
`театра` — название организации; `блок питания` — маркировка изделия. Простое
правило по окружению отсекает почти весь мусор, оставляя человеку и модели
только спорное.

**Предфильтр по карточке.** Скачать документы всех извещений невозможно: за
семь месяцев по четырём регионам это больше миллиона файлов. Предфильтр сужает
круг до закупок, где упоминание вообще возможно. Он намеренно широкий:
пропущенная закупка не вернётся, а лишняя стоит одного скачивания.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Границы слова
# ─────────────────────────────────────────────────────────────────────────────

# `\b` здесь не годится: он считает границей стык кириллицы с латиницей и
# поймал бы «ХПК» внутри слова, набранного вперемешку. Цифры границей не
# считаются — «БПК5» и «ХПК20» должны совпадать.
NOT_LETTER_BEFORE = r"(?<![А-Яа-яЁёA-Za-z])"
NOT_LETTER_AFTER = r"(?![А-Яа-яЁёA-Za-z])"

# «БПКполн» и «ХПКполн» — общепринятая запись без пробела. Буква сразу после
# аббревиатуры в остальных случаях означает другое слово («ХПКомбинат»),
# поэтому допускаются только известные суффиксы, а не любой хвост.
SUFFIX = r"(?:\s*[-–]?\s*(?:полн\w*|п\.|[₅₂₀0-9]{1,2}))?"


class TermRole(StrEnum):
    """Что термин значит сам по себе."""

    #: Достаточен, чтобы закупку стоило рассматривать.
    PRIMARY = "primary"
    #: Усиливает основной, но в одиночку не значит ничего.
    SUPPORTING = "supporting"


class Confidence(StrEnum):
    """Что контекст говорит о находке."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    #: Контекст молчит — решать модели.
    DISPUTED = "disputed"


@dataclass(frozen=True, slots=True)
class TermPattern:
    name: str
    pattern: re.Pattern[str]
    role: TermRole = TermRole.PRIMARY


@dataclass(frozen=True, slots=True)
class ContextRule:
    """Что означает окружение совпадения.

    `window` — сколько символов вокруг совпадения смотреть. Узкое окно у правил
    отказа не случайно: «ХПК Мариинского театра» опознаётся по слову в трёх
    словах от аббревиатуры, а на всей цитате в ±220 символов найдётся и «отходы»,
    и «опасности», и что угодно ещё.
    """

    name: str
    pattern: re.Pattern[str]
    verdict: Confidence
    window: int | None = None


@dataclass(frozen=True, slots=True)
class Structural:
    """Условия по карточке — их проверяет база, а не движок.

    Отделены от терминов, потому что стоят ничего: сузить корпус запросом до
    чтения документов дешевле любой другой экономии.
    """

    regions: tuple[str, ...] = ()
    customer_inns: tuple[str, ...] = ()
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    only_active: bool = False


@dataclass(frozen=True, slots=True)
class Criteria:
    """Полное описание того, что ищут."""

    name: str
    terms: tuple[TermPattern, ...]
    context_rules: tuple[ContextRule, ...] = ()
    #: Предфильтр по карточке извещения.
    card_pattern: re.Pattern[str] | None = None
    #: Коды ОКПД2, при которых тема возможна даже при нейтральном названии.
    okpd2_prefixes: tuple[str, ...] = ()
    #: Условия по карточке: бюджет, регион, заказчик.
    structural: Structural = field(default_factory=lambda: Structural())
    #: Ширина цитаты в обе стороны от совпадения.
    quote_radius: int = 220
    #: Больше пяти цитат из одного документа ничего не добавляют к решению.
    max_hits_per_document: int = 5
    #: Версия критериев — часть ключа кэша вердиктов. Правка шаблонов обязана
    #: обесценить прежние решения, а не смешаться с ними.
    version: str = "v1"

    extra: dict[str, str] = field(default_factory=dict)

    @property
    def primary_terms(self) -> tuple[TermPattern, ...]:
        return tuple(t for t in self.terms if t.role is TermRole.PRIMARY)


# ─────────────────────────────────────────────────────────────────────────────
# Критерий ХПК/БПК — тот самый, по которому считался размеченный набор
# ─────────────────────────────────────────────────────────────────────────────

#: Внутри аббревиатуры **нет** необязательного пробела.
#:
#: Он там был и стоил трёх ложных срабатываний на 56 млн ₽ — самый дорогой
#: дефект прогона по деньгам. `Б\s?П\s?К` находил «д. 22**б ПК** "Зарайский"» в
#: списке адресов, а `Х\s?П\s?К` — «блок из 2-**х ПК**4-1013442321» в перечне
#: светильников. Пробела внутри ХПК/БПК не бывает.
CHEMICAL_OXYGEN_DEMAND = re.compile(
    NOT_LETTER_BEFORE + r"[ХXхx][Пп][КKкk]" + SUFFIX + NOT_LETTER_AFTER
)
BIOCHEMICAL_OXYGEN_DEMAND = re.compile(
    NOT_LETTER_BEFORE + r"[Бб][Пп][КKкk]" + SUFFIX + NOT_LETTER_AFTER
)

#: Развёрнутая формулировка. Ловит ТЗ, где аббревиатура не используется, но
#: сама по себе почти всегда указывает на медицину — отсюда роль.
OXYGEN_CONSUMPTION = re.compile(
    r"(?:хим\w*|биохим\w*|биологич\w*)?[\s.]*потреблени\w*\s+кислород\w*",
    re.IGNORECASE,
)

#: Химия воды: рядом с такими словами ХПК/БПК означают именно показатель.
WATER_CHEMISTRY = re.compile(
    r"мг\s*/\s*дм|мг\s*/\s*л|ПДК|предельно\s*допустим"
    r"|сточн|стоков|стоки|фильтрат|пермеат|очистн|водоотвед|водоснабж|водоём|водоем"
    r"|взвешенн\w+\s+веществ|нитрат|нитрит|аммони|фосфат|сульфат|нефтепродукт|сероводород"
    r"|отбор\w*\s+проб|пробоотбор|количественн\w+\s+химическ\w+\s+анализ"
    r"|лаборатор|гидрохим|санитарно-?гигиен|рыбохозяйствен"
    r"|стандартн\w+\s+образц|ГСО\b|раствор\w*\s+состава"
    r"|водородн\w+\s+показател|минерализаци|жёсткость|жесткость",
    re.IGNORECASE,
)

#: Название организации или объекта. Узкое окно: эти слова стоят вплотную к
#: аббревиатуре, а на всей цитате найдётся что угодно.
OBJECT_NAME = re.compile(
    r"кровл|капитальн\w+\s+ремонт|текущ\w+\s+ремонт|здани|помещени|цех|корпус"
    r"|СИЗО|ФКУ|ФСИН|театр|филиал|университет|комбинат"
    r"|по\s+адресу|автопогрузчик|вентиляци|кондиционировани"
    r"|сварщик|электроустановок|прачечн|гладильн|сушильн|отжимн",
    re.IGNORECASE,
)

#: Маркировка изделия: «Блок питания БПК-01».
PRODUCT_MARKING = re.compile(
    r"блок\w*\s+питани|светильник|розетк|извещател|шкаф\w*\s+управлени", re.IGNORECASE
)

#: Предфильтр по карточке: вода, стоки, экология, лаборатория, реагенты, приборы.
WATER_RELATED_CARD = re.compile(
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

#: ОКПД2, при которых тема возможна даже при нейтральном названии.
#:   36/37 вода и стоки · 38/39 отходы и рекультивация · 71.20 испытания
#:   20.13/20.14/20.59 реактивы · 26.51/26.60 приборы · 43.22 сантехработы
WATER_RELATED_OKPD2 = (
    "36.", "37.", "38.", "39.", "71.20", "71.12", "20.59", "20.13", "20.14",
    "26.51", "26.60", "43.22", "42.21", "35.30", "86.90",
)


#: Ширина окна для правил отказа. Три-четыре слова — ровно столько, сколько
#: занимает «ХПК Мариинского театра» или «кровли БПК ФКУ СИЗО-12».
NARROW_WINDOW = 60


OXYGEN_DEMAND_CRITERIA = Criteria(
    name="ХПК/БПК",
    terms=(
        TermPattern("ХПК", CHEMICAL_OXYGEN_DEMAND, TermRole.PRIMARY),
        TermPattern("БПК", BIOCHEMICAL_OXYGEN_DEMAND, TermRole.PRIMARY),
        TermPattern("потребление кислорода", OXYGEN_CONSUMPTION, TermRole.SUPPORTING),
    ),
    context_rules=(
        ContextRule("название объекта", OBJECT_NAME, Confidence.REJECTED, NARROW_WINDOW),
        ContextRule("маркировка изделия", PRODUCT_MARKING, Confidence.REJECTED, NARROW_WINDOW),
        ContextRule("химия воды", WATER_CHEMISTRY, Confidence.CONFIRMED),
    ),
    card_pattern=WATER_RELATED_CARD,
    okpd2_prefixes=WATER_RELATED_OKPD2,
    version="хпк-бпк-v2",
)


# ─────────────────────────────────────────────────────────────────────────────
# Критерий из сохранённой спецификации
# ─────────────────────────────────────────────────────────────────────────────

#: Встроенные критерии, доступные по имени. Тот, что проверен на размеченном
#: наборе, живёт здесь и переопределению из спецификации не подлежит.
BUILTIN: dict[str, Criteria] = {}


class CriteriaError(ValueError):
    """Спецификация не складывается в критерий."""


def criteria_from_spec(spec: dict[str, Any]) -> Criteria:
    """Собирает критерий из сохранённой спецификации.

    Спецификация — то, что пользователь описал в конструкторе фильтра: термины
    регулярными выражениями, правила по контексту и предфильтр по карточке.

    Битый шаблон — это ошибка спецификации, а не повод уронить прогон: критерий
    без одного термина искал бы не то, что просили, и молчать об этом нельзя.
    """
    name = str(spec.get("name") or "критерий")

    builtin = spec.get("builtin")
    if builtin:
        if builtin not in BUILTIN:
            raise CriteriaError(f"неизвестный встроенный критерий: {builtin}")
        return BUILTIN[str(builtin)]

    terms: list[TermPattern] = []
    for raw in spec.get("terms") or ():
        term_name = str(raw.get("name") or "").strip()
        pattern = raw.get("pattern")
        if not term_name or not pattern:
            raise CriteriaError("у термина должны быть имя и шаблон")
        terms.append(
            TermPattern(
                name=term_name,
                pattern=_compile(pattern, term_name),
                role=TermRole(raw.get("role") or TermRole.PRIMARY),
            )
        )

    if not terms:
        raise CriteriaError("критерий без терминов ничего не найдёт")

    rules: list[ContextRule] = []
    for raw in spec.get("context_rules") or ():
        rule_name = str(raw.get("name") or "правило")
        rules.append(
            ContextRule(
                name=rule_name,
                pattern=_compile(raw.get("pattern"), rule_name),
                verdict=Confidence(raw.get("verdict") or Confidence.REJECTED),
                window=raw.get("window"),
            )
        )

    raw_structural = spec.get("structural") or {}
    structural = Structural(
        regions=tuple(raw_structural.get("regions") or ()),
        customer_inns=tuple(raw_structural.get("customer_inns") or ()),
        price_min=_money(raw_structural.get("price_min")),
        price_max=_money(raw_structural.get("price_max")),
        only_active=bool(raw_structural.get("only_active")),
    )

    card = spec.get("card_pattern")
    return Criteria(
        name=name,
        terms=tuple(terms),
        context_rules=tuple(rules),
        card_pattern=_compile(card, "предфильтр") if card else None,
        okpd2_prefixes=tuple(spec.get("okpd2_prefixes") or ()),
        structural=structural,
        quote_radius=int(spec.get("quote_radius") or 220),
        max_hits_per_document=int(spec.get("max_hits_per_document") or 5),
        version=str(spec.get("version") or "v1"),
    )


def _money(value: object) -> Decimal | None:
    """Деньги приходят числом из JSON; мусор молча в ноль не превращаем."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        raise CriteriaError(f"неверная сумма: {value!r}") from None


def _compile(pattern: object, where: str) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern.strip():
        raise CriteriaError(f"пустой шаблон: {where}")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise CriteriaError(f"неверный шаблон ({where}): {exc}") from exc


BUILTIN[OXYGEN_DEMAND_CRITERIA.name] = OXYGEN_DEMAND_CRITERIA

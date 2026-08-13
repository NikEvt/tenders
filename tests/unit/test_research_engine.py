"""Ядро отбора: шаблоны, находки, уверенность.

Главный тест здесь — не про регулярные выражения, а про результат целиком:
движок прогоняется по размеченному набору из прогона ХПК/БПК и обязан
воспроизвести решение человека. 56 подтверждённых не должны потеряться,
20 отклонённых не должны пройти.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.research.domain.confidence import judge_hit, judge_tender
from services.research.domain.criteria import (
    OXYGEN_DEMAND_CRITERIA,
    Confidence,
    TermRole,
)
from services.research.domain.hits import find_hits, is_card_candidate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CRITERIA = OXYGEN_DEMAND_CRITERIA


def hits_of(text: str):
    return find_hits(text, CRITERIA)


def terms_of(text: str) -> list[str]:
    return [hit.term for hit in hits_of(text)]


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads((FIXTURES / "hpk_golden.json").read_text(encoding="utf-8"))


def verdict_for(tender: dict):
    """Прогоняет движок по цитатам закупки так же, как он шёл бы по документам."""
    hits = []
    for hit in tender["hits"]:
        hits.extend(find_hits(hit["quote"], CRITERIA, file_name=hit["file_name"]))
    return judge_tender(hits, CRITERIA)


# ─── Приёмка по размеченному набору ───────────────────────────────────────────


class TestAgainstTheLabelledSet:
    """Оракул: решение человека по 76 закупкам прогона."""

    def test_no_confirmed_tender_is_lost(self, golden: dict) -> None:
        """Полнота важнее точности: пропущенная закупка не вернётся."""
        lost = [
            tender["reg_num"]
            for tender in golden["tenders"]
            if tender["label"] == "confirmed"
            and verdict_for(tender).confidence is Confidence.REJECTED
        ]
        assert lost == []

    def test_every_false_positive_is_rejected_without_the_model(
        self, golden: dict
    ) -> None:
        """Все 20 ложных срабатываний отсекаются правилами, без токенов."""
        survived = [
            (tender["reg_num"], tender["reject_class"])
            for tender in golden["tenders"]
            if tender["label"] == "rejected"
            and verdict_for(tender).confidence is not Confidence.REJECTED
        ]
        assert survived == []

    def test_most_confirmed_need_no_model_either(self, golden: dict) -> None:
        """Судью зовут только к спорному, иначе экономии не получится.

        Замер на наборе: 48 из 56 решаются контекстом, к модели уходит 8.
        Порог намеренно мягче замера — тест охраняет порядок величины, а не
        конкретное число, которое сдвинется от любой правки шаблонов.
        """
        confirmed = [t for t in golden["tenders"] if t["label"] == "confirmed"]
        decided = [
            t for t in confirmed if verdict_for(t).confidence is Confidence.CONFIRMED
        ]
        assert len(decided) >= len(confirmed) * 0.7

    @pytest.mark.parametrize(
        ("reject_class", "expected_reason"),
        [
            ("template_artifact", "совпадений нет"),
            ("medicine", "только вспомогательный термин без ХПК/БПК"),
            ("object_name", "название объекта"),
            ("product_marking", "маркировка изделия"),
        ],
    )
    def test_each_class_is_rejected_for_the_right_reason(
        self, golden: dict, reject_class: str, expected_reason: str
    ) -> None:
        """Совпасть числом мало — отсекать должен тот механизм, что задуман.

        Иначе класс, случайно отсечённый чужим правилом, развалится от правки,
        к нему отношения не имеющей.
        """
        wrong = [
            (tender["reg_num"], verdict_for(tender).reason)
            for tender in golden["tenders"]
            if tender["reject_class"] == reject_class
            and verdict_for(tender).reason != expected_reason
        ]
        assert wrong == []


# ─── Шаблоны ──────────────────────────────────────────────────────────────────


class TestPatternsWithoutTheOptionalSpace:
    """Самый дорогой дефект прогона: `\\s?` внутри аббревиатуры, 56 млн ₽."""

    @pytest.mark.parametrize(
        "text",
        [
            "РОССИЯ, Московская область, д. 22б ПК «Зарайский», участок 3",
            "блок из 2-х ПК4-1013442321, светильник",
            "корпус 5 б ПК 12",
        ],
    )
    def test_space_inside_the_abbreviation_is_not_a_match(self, text: str) -> None:
        assert terms_of(text) == []

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("ХПК не более 30 мг/дм3", ["ХПК"]),
            ("БПК5 составляет 2.1", ["БПК"]),
            ("БПК-5 и ХПК", ["БПК", "ХПК"]),
            ("БПКполн", ["БПК"]),
            ("показатель БПК₅", ["БПК"]),
            ("ХПК20 в пробе", ["ХПК"]),
        ],
    )
    def test_real_forms_are_matched(self, text: str, expected: list[str]) -> None:
        assert sorted(terms_of(text)) == sorted(expected)

    @pytest.mark.parametrize("text", ["ХПКомбинат", "БПКрасный", "ХПКабель"])
    def test_a_letter_right_after_means_another_word(self, text: str) -> None:
        assert terms_of(text) == []

    def test_latin_lookalikes_are_matched(self) -> None:
        """После OCR подмена кириллицы латиницей — обычное дело."""
        assert terms_of("XПK не более 30") == ["ХПК"]

    def test_mixed_alphabet_word_is_not_split(self) -> None:
        """`\\b` считает границей стык кириллицы с латиницей — поэтому его нет."""
        assert terms_of("aБПКb") == []


class TestSupportingTerm:
    def test_oxygen_consumption_is_supporting(self) -> None:
        hits = hits_of("Измеряемые параметры: VO2 (потребление кислорода), мл/мин")
        assert [hit.role for hit in hits] == [TermRole.SUPPORTING]

    def test_abbreviations_are_primary(self) -> None:
        assert all(hit.role is TermRole.PRIMARY for hit in hits_of("ХПК и БПК"))


# ─── Находки ──────────────────────────────────────────────────────────────────


class TestHits:
    def test_quote_carries_context_on_both_sides(self) -> None:
        text = "а" * 500 + " ХПК " + "б" * 500
        hit = hits_of(text)[0]

        assert "а" in hit.quote and "б" in hit.quote
        assert hit.matched == "ХПК"

    def test_match_offsets_allow_highlighting(self) -> None:
        """Без подсветки превью показывает левый контекст и вводит в заблуждение."""
        hit = hits_of("норматив по показателю БПК5 в сточной воде")[0]

        assert hit.highlighted() == "норматив по показателю >>>БПК5<<< в сточной воде"

    def test_whitespace_is_collapsed(self) -> None:
        """Текст из PDF приходит с переносами посреди предложения."""
        hit = hits_of("показатель\n\n  ХПК   в\tпробе")[0]
        assert hit.quote == "показатель ХПК в пробе"

    def test_overlapping_matches_collapse_into_one(self) -> None:
        """«ХПК» внутри «химическое потребление кислорода» — одна находка."""
        hits = hits_of("химическое потребление кислорода")
        assert len(hits) == 1

    def test_hits_per_document_are_capped(self) -> None:
        hits = hits_of(" ".join(["ХПК"] * 50))
        assert len(hits) == CRITERIA.max_hits_per_document

    def test_source_offset_points_into_the_original_text(self) -> None:
        text = "Раздел 3.\n\n\nПоказатель ХПК"
        hit = hits_of(text)[0]
        assert text[hit.source_offset : hit.source_offset + 3] == "ХПК"

    def test_empty_text_yields_nothing(self) -> None:
        assert hits_of("") == []
        assert hits_of("   \n  ") == []

    def test_file_and_page_are_carried_through(self) -> None:
        hit = find_hits("ХПК", CRITERIA, file_name="ТЗ.pdf", page=4)[0]
        assert hit.file_name == "ТЗ.pdf"
        assert hit.page == 4


# ─── Уверенность ──────────────────────────────────────────────────────────────


class TestContextRules:
    @pytest.mark.parametrize(
        "text",
        [
            "Капитальный ремонт кровли БПК ФКУ СИЗО-12",
            "оборудования, расположенного в цехах ХПК Мариинского театра",
            'текущий ремонт узла ввода электросети в здание "БПК" филиала',
            "Капитальный ремонт БПК по адресу: г. Санкт-Петербург",
        ],
    )
    def test_object_names_are_rejected(self, text: str) -> None:
        assert judge_hit(hits_of(text)[0], CRITERIA).confidence is Confidence.REJECTED

    def test_product_marking_is_rejected(self) -> None:
        hit = hits_of("Блок питания БПК-01 | 26.20.40.110")[0]
        assert judge_hit(hit, CRITERIA).confidence is Confidence.REJECTED

    @pytest.mark.parametrize(
        "text",
        [
            "ХПК не более 30 мг/дм3 в сточных водах",
            "БПК5 при отборе проб фильтрата полигона",
            "превышение ПДК по показателю ХПК",
            "количественный химический анализ сточных вод: БПК, взвешенные вещества",
        ],
    )
    def test_water_chemistry_is_confirmed(self, text: str) -> None:
        assert judge_hit(hits_of(text)[0], CRITERIA).confidence is Confidence.CONFIRMED

    def test_unknown_context_goes_to_the_model(self) -> None:
        assert judge_hit(hits_of("ХПК")[0], CRITERIA).confidence is Confidence.DISPUTED

    def test_object_name_wins_over_a_distant_chemistry_word(self) -> None:
        """Правила отказа смотрят узкое окно — иначе их забивает дальний шум.

        «Утилизация отходов с объектов ХПК Мариинского театра»: слово «отходов»
        относится к предмету закупки, а не к аббревиатуре.
        """
        text = (
            "Оказание услуг по транспортированию и утилизации отходов III класса "
            "опасности с объектов ХПК Мариинского театра"
        )
        assert judge_hit(hits_of(text)[0], CRITERIA).confidence is Confidence.REJECTED


class TestTenderVerdict:
    def test_one_confirmed_hit_is_enough(self) -> None:
        """Показатель, упомянутый по делу хоть где-то, делает закупку релевантной."""
        hits = hits_of("ремонт кровли БПК СИЗО") + hits_of("ХПК не более 30 мг/дм3")
        assert judge_tender(hits, CRITERIA).confidence is Confidence.CONFIRMED

    def test_all_rejected_hits_reject_the_tender(self) -> None:
        hits = hits_of("ремонт кровли БПК СИЗО") + hits_of("здание БПК филиала")
        assert judge_tender(hits, CRITERIA).confidence is Confidence.REJECTED

    def test_supporting_term_alone_is_not_enough(self) -> None:
        """Шесть закупок в наборе, все медицинские."""
        hits = hits_of("VO2peak — максимальное потребление кислорода при ЧСС")
        verdict = judge_tender(hits, CRITERIA)

        assert verdict.confidence is Confidence.REJECTED
        assert "вспомогательный" in verdict.reason

    def test_supporting_term_does_not_outvote_the_primary(self) -> None:
        """Иначе «потребление кислорода» в медицинском ТЗ перетянуло бы решение."""
        hits = hits_of("ХПК не более 30 мг/дм3") + hits_of("потребление кислорода, VO2")
        assert judge_tender(hits, CRITERIA).confidence is Confidence.CONFIRMED

    def test_no_hits_means_rejected(self) -> None:
        assert judge_tender([], CRITERIA).confidence is Confidence.REJECTED


# ─── Предфильтр по карточке ───────────────────────────────────────────────────


class TestCardPrefilter:
    def test_reproduces_the_run_on_six_hundred_cards(self) -> None:
        """Характеризация: предфильтр переносится как есть и сдвинуться не должен."""
        sample = json.loads(
            (FIXTURES / "hpk_prefilter_sample.json").read_text(encoding="utf-8")
        )["tenders"]

        diverged = [
            tender["reg_num"]
            for tender in sample
            if is_card_candidate(
                tender["name"],
                tender["description"],
                tender["okpd2_codes"],
                tender["okpd2_names"],
                CRITERIA,
            )
            is not tender["is_candidate"]
        ]
        assert diverged == []

    def test_okpd2_alone_is_enough(self) -> None:
        """Тема возможна и при нейтральном названии — код это выдаёт."""
        assert is_card_candidate("Оказание услуг", None, ["37.00.11"], [], CRITERIA)

    def test_unrelated_card_is_filtered_out(self) -> None:
        assert not is_card_candidate(
            "Поставка офисной мебели", "Столы и стулья", ["31.01.11"], [], CRITERIA
        )

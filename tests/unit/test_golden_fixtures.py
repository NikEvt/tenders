"""Целостность эталонного набора ХПК/БПК.

Набор — оракул приёмки движка отбора: по нему меряется и полнота (56
подтверждённых), и точность (20 отклонённых с классами). Оракул, который
испортился незаметно, хуже отсутствующего: тесты продолжают гореть зелёным, а
меряют не то. Поэтому у самого набора есть тесты.

Пересобирается скриптом `scripts/build_golden_fixtures.py` из результатов
прогона 11–12 августа 2026.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

#: Классы ложных срабатываний из ретроспективы. Пятого быть не должно: новый
#: класс — это либо ошибка разметки, либо повод обновить правила по контексту.
REJECT_CLASSES = {"medicine", "template_artifact", "object_name", "product_marking"}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden() -> dict:
    return _load("hpk_golden.json")


def test_golden_holds_the_documented_verdict_counts(golden: dict) -> None:
    """56 подтверждённых и 20 отклонённых — числа из ретроспективы."""
    labels = [tender["label"] for tender in golden["tenders"]]
    assert labels.count("confirmed") == 56
    assert labels.count("rejected") == 20
    assert golden["meta"]["confirmed"] == 56
    assert golden["meta"]["rejected"] == 20


def test_every_tender_carries_at_least_one_hit(golden: dict) -> None:
    """Закупка попала в разметку только потому, что где-то нашлось совпадение.

    Закупка без цитаты не поддаётся ни проверке человеком, ни оценке движка —
    в наборе такой быть не может.
    """
    without_hits = [t["reg_num"] for t in golden["tenders"] if not t["hits"]]
    assert without_hits == []


def test_rejected_tenders_are_classified(golden: dict) -> None:
    rejected = [t for t in golden["tenders"] if t["label"] == "rejected"]
    assert {t["reject_class"] for t in rejected} <= REJECT_CLASSES
    assert all(t["reject_reason"] for t in rejected)


def test_confirmed_tenders_carry_no_reject_reason(golden: dict) -> None:
    confirmed = [t for t in golden["tenders"] if t["label"] == "confirmed"]
    assert all(t["reject_class"] is None and t["reject_reason"] is None for t in confirmed)


def test_registration_numbers_are_unique(golden: dict) -> None:
    numbers = [tender["reg_num"] for tender in golden["tenders"]]
    assert len(numbers) == len(set(numbers))


def test_quotes_actually_contain_something_to_judge(golden: dict) -> None:
    """Цитата — единственный вход судьи, пустая делает закупку неоценимой."""
    for tender in golden["tenders"]:
        for hit in tender["hits"]:
            assert hit["quote"].strip(), tender["reg_num"]
            assert hit["term"].strip(), tender["reg_num"]


def test_the_three_template_artifacts_are_present(golden: dict) -> None:
    """Самый дорогой дефект прогона: `\\s?` внутри аббревиатуры, 56 млн ₽.

    Эти три закупки — причина, по которой из шаблона убирается необязательный
    пробел. Если они пропадут из набора, правка потеряет доказательство.
    """
    artifacts = [t for t in golden["tenders"] if t["reject_class"] == "template_artifact"]
    assert len(artifacts) == 3


def test_funnel_denominators_are_present() -> None:
    """Знаменатели воронки: без них «ноль находок» ничего не значит."""
    funnel = _load("hpk_funnel.json")
    assert funnel["tenders_total"] == 149860
    assert funnel["hits_total"] == 333
    assert funnel["tenders_with_hits"] == 76
    # Разобранное — только часть очереди, и это принципиально: выводы «в этом
    # приоритете находок нет» законны лишь там, где знаменатель ненулевой.
    assert funnel["attachments_by_status"]["pending"] > 0


def test_prefilter_sample_is_balanced() -> None:
    sample = _load("hpk_prefilter_sample.json")["tenders"]
    candidates = sum(1 for tender in sample if tender["is_candidate"])
    assert candidates == 300
    assert len(sample) == 600


def test_admission_sample_covers_every_priority_class() -> None:
    sample = _load("hpk_admission_sample.json")["attachments"]
    assert {attachment["priority"] for attachment in sample} == {0, 1, 2, 3, 9}

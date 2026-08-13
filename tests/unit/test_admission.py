"""Политика допуска вложений.

Числа в тестах не выдуманы: это сценарии из прогона ХПК/БПК, включая четыре
закупки, которые принесли 84 ГБ томами по 50 МБ. Приоритеты сверяются с
`hpk_admission_sample.json` — 300 настоящих вложений с приоритетом, который им
присвоил прогон.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.docs_worker.domain.admission import (
    MB,
    AdmissionPolicy,
    Candidate,
    SkipReason,
    is_multivolume,
    is_signature,
    priority_of,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def accepted(decisions) -> list[int]:
    return [d.candidate.document_id for d in decisions if d.accepted]


def reasons(decisions) -> dict[int, SkipReason | None]:
    return {d.candidate.document_id: d.reason for d in decisions}


class TestPriority:
    @pytest.mark.parametrize(
        ("file_name", "expected"),
        [
            ("Техническое задание.docx", 0),
            ("ТЗ.pdf", 0),
            ("Описание объекта закупки.docx", 0),
            ("Обоснование НМЦК.xlsx", 1),
            ("расчет цены.xlsx", 1),
            ("Извещение.docx", 2),
            ("Приложение №3.pdf", 2),
            ("Смета.xlsx", 2),
            ("Проект контракта.docx", 3),
            ("Инструкция участникам.docx", 3),
            ("Фотография площадки.jpg", 9),
        ],
    )
    def test_documents_are_ranked_by_what_they_are(self, file_name: str, expected: int) -> None:
        assert priority_of(file_name, None) == expected

    def test_document_kind_counts_when_the_name_says_nothing(self) -> None:
        """У ЕИС вид документа отдельным полем, и часто он информативнее имени."""
        assert priority_of("file001.pdf", "Техническое задание") == 0
        assert priority_of("file002.pdf", None) == 9

    def test_matches_the_priorities_of_the_real_run(self) -> None:
        """Сверка с 300 настоящими вложениями: перенос не должен сдвинуть порядок."""
        sample = json.loads(
            (FIXTURES / "hpk_admission_sample.json").read_text(encoding="utf-8")
        )["attachments"]

        mismatched = [
            item
            for item in sample
            if priority_of(item["file_name"], item["doc_kind_name"]) != item["priority"]
        ]
        assert mismatched == [], f"разошлись приоритеты у {len(mismatched)} из {len(sample)}"


class TestMultivolume:
    @pytest.mark.parametrize(
        "file_name",
        [
            "ПСД.part01.rar",
            "ПСД.part12.rar",
            "Документация.r01",
            "Документация.z15",
            "Проект.7z.001",
            "Архив.zip.002",
        ],
    )
    def test_volumes_are_recognised(self, file_name: str) -> None:
        assert is_multivolume(file_name)

    @pytest.mark.parametrize(
        "file_name", ["Документация.zip", "Проект.rar", "Архив.7z", "ТЗ.pdf"]
    )
    def test_ordinary_archives_are_not_volumes(self, file_name: str) -> None:
        assert not is_multivolume(file_name)

    def test_the_84_gigabyte_case(self) -> None:
        """Закупка с 550 томами по 50 МБ: не должно скачаться ни одного.

        Каждый том аккуратно под лимитом на файл — именно поэтому лимита на
        файл здесь и не хватало.
        """
        volumes = [
            Candidate(
                document_id=i,
                file_name=f"Проектная документация.part{i:03d}.rar",
                file_size=50 * MB,
                source_url=f"https://zakupki.gov.ru/file?uid={i}",
            )
            for i in range(1, 551)
        ]
        decisions = AdmissionPolicy().plan(volumes)

        assert accepted(decisions) == []
        assert all(d.reason is SkipReason.MULTIVOLUME for d in decisions)

    def test_volumes_do_not_eat_the_budget_of_useful_documents(self) -> None:
        """Тома отсекаются до бюджета, иначе ТЗ осталось бы без места."""
        candidates = [
            Candidate(document_id=1, file_name="ПСД.part01.rar", file_size=50 * MB,
                      source_url="u1"),
            Candidate(document_id=2, file_name="ПСД.part02.rar", file_size=50 * MB,
                      source_url="u2"),
            Candidate(document_id=3, file_name="Техническое задание.docx",
                      file_size=2 * MB, source_url="u3"),
        ]
        decisions = AdmissionPolicy().plan(candidates)
        assert accepted(decisions) == [3]


class TestSignatures:
    @pytest.mark.parametrize("name", ["контракт.pdf.sig", "тз.docx.p7s", "cert.cer"])
    def test_signatures_are_skipped(self, name: str) -> None:
        assert is_signature(name)

    def test_signature_never_reaches_the_network(self) -> None:
        decisions = AdmissionPolicy().plan(
            [Candidate(document_id=1, file_name="контракт.pdf.sig", file_size=2000,
                       source_url="u")]
        )
        assert reasons(decisions) == {1: SkipReason.SIGNATURE}


class TestTenderBudget:
    def test_budget_is_spent_in_priority_order(self) -> None:
        """ТЗ и обоснование проходят, тяжёлый хвост обрезается."""
        candidates = [
            Candidate(document_id=1, file_name="Альбом чертежей.pdf", file_size=25 * MB,
                      source_url="u1"),
            Candidate(document_id=2, file_name="Техническое задание.docx",
                      file_size=10 * MB, source_url="u2"),
            Candidate(document_id=3, file_name="Обоснование НМЦК.xlsx",
                      file_size=10 * MB, source_url="u3"),
        ]
        decisions = AdmissionPolicy(max_tender_bytes=30 * MB).plan(candidates)

        assert sorted(accepted(decisions)) == [2, 3]
        assert reasons(decisions)[1] is SkipReason.TENDER_BUDGET

    def test_already_processed_documents_still_consume_the_budget(self) -> None:
        """Иначе возобновлённый прогон выдавал бы закупке новый бюджет.

        Ровно этот дефект делал лимит декоративным: перезапуск обнулял счёт.
        """
        candidates = [
            Candidate(document_id=1, file_name="Техническое задание.docx",
                      file_size=28 * MB, source_url="u1", processed=True),
            Candidate(document_id=2, file_name="Приложение.pdf", file_size=10 * MB,
                      source_url="u2"),
        ]
        decisions = AdmissionPolicy(max_tender_bytes=30 * MB).plan(candidates)

        # Разобранное наружу не возвращается, но место уже занято.
        assert [d.candidate.document_id for d in decisions] == [2]
        assert reasons(decisions) == {2: SkipReason.TENDER_BUDGET}

    def test_unknown_size_is_let_through(self) -> None:
        """ЕИС не всегда отдаёт размер; считать такой файл огромным — терять его."""
        decisions = AdmissionPolicy(max_tender_bytes=1 * MB).plan(
            [Candidate(document_id=1, file_name="ТЗ.docx", file_size=None, source_url="u")]
        )
        assert accepted(decisions) == [1]

    def test_oversized_single_file_is_cut(self) -> None:
        decisions = AdmissionPolicy(max_file_bytes=60 * MB).plan(
            [Candidate(document_id=1, file_name="Альбом.pdf", file_size=80 * MB,
                       source_url="u")]
        )
        assert reasons(decisions) == {1: SkipReason.TOO_LARGE}


class TestOverviewPass:
    def test_low_priority_is_cut_when_asked(self) -> None:
        candidates = [
            Candidate(document_id=1, file_name="Техническое задание.docx", file_size=MB,
                      source_url="u1"),
            Candidate(document_id=2, file_name="Проект контракта.docx", file_size=MB,
                      source_url="u2"),
        ]
        decisions = AdmissionPolicy(max_priority=1).plan(candidates)

        assert accepted(decisions) == [1]
        assert reasons(decisions)[2] is SkipReason.LOW_PRIORITY

    def test_full_pass_takes_what_the_overview_left(self) -> None:
        """Обзорный проход не имеет права сделать полный невозможным."""
        candidates = [
            Candidate(document_id=1, file_name="Техническое задание.docx", file_size=MB,
                      source_url="u1"),
            Candidate(document_id=2, file_name="Проект контракта.docx", file_size=MB,
                      source_url="u2"),
        ]
        assert accepted(AdmissionPolicy().plan(candidates)) == [1, 2]


class TestSkipsAreFinalOrNot:
    """Отказ навсегда и отказ до следующих настроек — разные вещи.

    Смешать их значит сделать обзорный проход необратимым: отсечённое по
    приоритету больше никогда не попадёт в полный прогон.
    """

    @pytest.mark.parametrize(
        "reason", [SkipReason.MULTIVOLUME, SkipReason.SIGNATURE, SkipReason.NO_SOURCE]
    )
    def test_properties_of_the_file_are_final(self, reason: SkipReason) -> None:
        assert reason.is_final

    @pytest.mark.parametrize(
        "reason",
        [SkipReason.TOO_LARGE, SkipReason.TENDER_BUDGET, SkipReason.LOW_PRIORITY],
    )
    def test_consequences_of_settings_are_not(self, reason: SkipReason) -> None:
        assert not reason.is_final


class TestMissingSource:
    def test_document_without_a_link_cannot_be_fetched(self) -> None:
        decisions = AdmissionPolicy().plan(
            [Candidate(document_id=1, file_name="ТЗ.docx", file_size=MB, source_url=None)]
        )
        assert reasons(decisions) == {1: SkipReason.NO_SOURCE}


class TestOrdering:
    def test_decisions_come_back_in_processing_order(self) -> None:
        """Порядок решений — это и есть порядок разбора: сначала ценное."""
        candidates = [
            Candidate(document_id=1, file_name="Прочее.pdf", file_size=MB, source_url="u1"),
            Candidate(document_id=2, file_name="Проект контракта.docx", file_size=MB,
                      source_url="u2"),
            Candidate(document_id=3, file_name="Техническое задание.docx", file_size=MB,
                      source_url="u3"),
        ]
        decisions = AdmissionPolicy().plan(candidates)
        assert [d.priority for d in decisions] == [0, 3, 9]
        assert accepted(decisions) == [3, 2, 1]

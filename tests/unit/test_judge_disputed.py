"""Судья по находкам: правила решают, модель разбирает остаток."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services.research.application.ports import (
    ModelUnavailable,
    TenderCandidate,
    TenderVerdict,
)
from services.research.application.use_cases.judge_disputed import (
    JudgeDisputedUseCase,
    verify_evidence,
)
from services.research.domain.criteria import OXYGEN_DEMAND_CRITERIA as CRITERIA
from services.research.domain.criteria import Confidence
from services.research.domain.hits import find_hits
from services.research.domain.verdict import EvidenceItem, ModelVerdict

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class FakeModel:
    """Модель, которая говорит заранее известное и помнит, о чём её спрашивали."""

    def __init__(
        self,
        verdict: ModelVerdict | None = None,
        unavailable_after: int | None = None,
        fail_on: set[int] | None = None,
    ) -> None:
        self.verdict = verdict or ModelVerdict(match=True, score=0.9, reasoning="подходит")
        self.prompts: list[str] = []
        self.unavailable_after = unavailable_after
        self.fail_on = fail_on or set()
        self.running = 0
        self.peak = 0
        self.delay = 0.0

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def judge(self, system: str, user: str) -> ModelVerdict:
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            self.prompts.append(user)
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.unavailable_after is not None and len(self.prompts) > self.unavailable_after:
                raise ModelUnavailable("503 от провайдера")
            if len(self.prompts) in self.fail_on:
                raise RuntimeError("невалидный JSON")
            return self.verdict
        finally:
            self.running -= 1


class FakeStore:
    def __init__(self, known: dict[int, TenderVerdict] | None = None) -> None:
        self.known = known or {}
        self.saved: list[TenderVerdict] = []

    async def stored(self, tender_ids, criteria_version, prompt_version):
        return {tid: self.known[tid] for tid in tender_ids if tid in self.known}

    async def save(self, verdicts, criteria_version, prompt_version, model) -> None:
        self.saved.extend(verdicts)


def candidate(tender_id: int, text: str, **kwargs) -> TenderCandidate:
    return TenderCandidate(
        tender_id=tender_id,
        reg_num=f"REG-{tender_id}",
        hits=find_hits(text, CRITERIA, file_name="ТЗ.docx"),
        **kwargs,
    )


CONFIRMED_TEXT = "ХПК не более 30 мг/дм3 в сточных водах"
REJECTED_TEXT = "Капитальный ремонт кровли БПК ФКУ СИЗО-12"
DISPUTED_TEXT = "Поставка стандартов. Показатель ХПК"


class TestRulesDecideFirst:
    async def test_model_is_not_called_for_confident_cases(self) -> None:
        """Ради этого этап и существует: не звать модель попусту."""
        model = FakeModel()
        use_case = JudgeDisputedUseCase(CRITERIA, model)

        outcome = await use_case.execute(
            [candidate(1, CONFIRMED_TEXT), candidate(2, REJECTED_TEXT)]
        )

        assert model.prompts == []
        assert outcome.funnel.confirmed_by_rules == 1
        assert outcome.funnel.rejected_by_rules == 1
        assert {v.decided_by for v in outcome.verdicts} == {"rules"}

    async def test_only_disputed_reach_the_model(self) -> None:
        model = FakeModel()
        use_case = JudgeDisputedUseCase(CRITERIA, model)

        outcome = await use_case.execute(
            [
                candidate(1, CONFIRMED_TEXT),
                candidate(2, REJECTED_TEXT),
                candidate(3, DISPUTED_TEXT),
            ]
        )

        assert len(model.prompts) == 1
        assert outcome.funnel.disputed == 1
        assert outcome.funnel.asked_model == 1

    async def test_funnel_adds_up(self) -> None:
        """Сумма по этапам обязана сходиться с общим числом."""
        use_case = JudgeDisputedUseCase(CRITERIA, FakeModel())
        outcome = await use_case.execute(
            [
                candidate(1, CONFIRMED_TEXT),
                candidate(2, REJECTED_TEXT),
                candidate(3, DISPUTED_TEXT),
            ]
        )
        assert outcome.funnel.check()
        assert outcome.funnel.total == 3


class TestPrompt:
    async def test_match_is_highlighted(self) -> None:
        """Без подсветки модель видит левый контекст, как когда-то человек."""
        model = FakeModel()
        await JudgeDisputedUseCase(CRITERIA, model).execute([candidate(1, DISPUTED_TEXT)])

        assert ">>>ХПК<<<" in model.prompts[0]

    async def test_hits_are_numbered_with_their_source(self) -> None:
        model = FakeModel()
        await JudgeDisputedUseCase(CRITERIA, model).execute([candidate(1, DISPUTED_TEXT)])

        assert "[1] ТЗ.docx" in model.prompts[0]

    async def test_card_is_included(self) -> None:
        model = FakeModel()
        await JudgeDisputedUseCase(CRITERIA, model).execute(
            [
                candidate(
                    1,
                    DISPUTED_TEXT,
                    name="Поставка стандартных образцов",
                    customer_name="Центр гигиены",
                    okpd2_code="20.59.52",
                )
            ]
        )

        assert "Поставка стандартных образцов" in model.prompts[0]
        assert "Центр гигиены" in model.prompts[0]

    async def test_supporting_hits_are_not_listed_separately(self) -> None:
        """Вспомогательная находка отдельным пунктом не идёт: она ничего не решает.

        В окружение основной находки она при этом попадает и попадать должна —
        цитата на то и цитата, чтобы показывать контекст.
        """
        model = FakeModel()
        await JudgeDisputedUseCase(CRITERIA, model).execute(
            [candidate(1, "Показатель ХПК. Также потребление кислорода по методике")]
        )

        listed = model.prompts[0].split("=== НАЙДЕННЫЕ УПОМИНАНИЯ ===")[1]
        assert listed.count("[1]") == 1
        assert "[2]" not in listed
        assert ">>>ХПК<<<" in listed


class TestEvidenceVerification:
    def test_fabricated_quotes_are_dropped(self) -> None:
        """Модель охотно цитирует правдоподобный, но отсутствующий текст."""
        hits = find_hits(CONFIRMED_TEXT, CRITERIA)
        verdict = ModelVerdict(
            match=True,
            evidence=[EvidenceItem(hit_number=1, quote="этого в цитате нет")],
        )

        assert verify_evidence(verdict, hits) == []

    def test_real_quotes_survive_with_their_source(self) -> None:
        hits = find_hits(CONFIRMED_TEXT, CRITERIA, file_name="ТЗ.docx", page=3)
        verdict = ModelVerdict(
            match=True, evidence=[EvidenceItem(hit_number=1, quote="30 мг/дм3")]
        )

        evidence = verify_evidence(verdict, hits)

        assert len(evidence) == 1
        assert evidence[0]["file_name"] == "ТЗ.docx"
        assert evidence[0]["page"] == 3

    def test_reference_to_a_nonexistent_hit_is_dropped(self) -> None:
        hits = find_hits(CONFIRMED_TEXT, CRITERIA)
        verdict = ModelVerdict(
            match=True, evidence=[EvidenceItem(hit_number=99, quote="30 мг/дм3")]
        )

        assert verify_evidence(verdict, hits) == []

    def test_empty_quote_falls_back_to_the_whole_hit(self) -> None:
        hits = find_hits(CONFIRMED_TEXT, CRITERIA)
        verdict = ModelVerdict(match=True, evidence=[EvidenceItem(hit_number=1)])

        assert verify_evidence(verdict, hits)[0]["quote"] == hits[0].quote


class TestStore:
    async def test_cached_verdict_skips_the_model(self) -> None:
        known = TenderVerdict(
            tender_id=3, confidence=Confidence.CONFIRMED, reason="из кэша",
            decided_by="model",
        )
        model = FakeModel()
        use_case = JudgeDisputedUseCase(CRITERIA, model, store=FakeStore({3: known}))

        outcome = await use_case.execute([candidate(3, DISPUTED_TEXT)])

        assert model.prompts == []
        assert outcome.funnel.from_cache == 1
        assert outcome.verdicts[0].reason == "из кэша"

    async def test_new_verdicts_are_stored(self) -> None:
        store = FakeStore()
        await JudgeDisputedUseCase(CRITERIA, FakeModel(), store=store).execute(
            [candidate(3, DISPUTED_TEXT)]
        )
        assert [v.tender_id for v in store.saved] == [3]

    async def test_verdicts_of_the_rules_are_stored_too(self) -> None:
        """Отбор каталога читает эту таблицу, а правила решают большинство."""
        store = FakeStore()
        await JudgeDisputedUseCase(CRITERIA, FakeModel(), store=store).execute(
            [
                candidate(1, CONFIRMED_TEXT),
                candidate(2, REJECTED_TEXT),
                candidate(3, DISPUTED_TEXT),
            ]
        )

        assert {v.tender_id for v in store.saved} == {1, 2, 3}
        assert sorted(v.decided_by for v in store.saved) == ["model", "rules", "rules"]

    async def test_a_run_without_disputes_still_stores(self) -> None:
        """Ранний возврат не должен уносить с собой решения правил."""
        store = FakeStore()
        outcome = await JudgeDisputedUseCase(CRITERIA, FakeModel(), store=store).execute(
            [candidate(1, CONFIRMED_TEXT), candidate(2, REJECTED_TEXT)]
        )

        assert outcome.funnel.disputed == 0
        assert {v.tender_id for v in store.saved} == {1, 2}

    async def test_dry_run_leaves_no_trace(self) -> None:
        """Пробный прогон считает воронку, но не пачкает отбор каталога."""
        store = FakeStore()
        outcome = await JudgeDisputedUseCase(
            CRITERIA, FakeModel(), store=store, dry_run=True
        ).execute(
            [candidate(1, CONFIRMED_TEXT), candidate(3, DISPUTED_TEXT)]
        )

        assert store.saved == []
        # Воронка при этом полноценная — ради неё тест и запускают.
        assert outcome.funnel.total == 2
        assert outcome.funnel.confirmed_by_rules == 1


class TestModelOutage:
    async def test_run_stops_instead_of_burning_the_queue(self) -> None:
        """Лежащая модель — не свойство закупки, перебирать очередь бессмысленно."""
        model = FakeModel(unavailable_after=1)
        use_case = JudgeDisputedUseCase(CRITERIA, model, concurrency=1)

        outcome = await use_case.execute(
            [candidate(i, DISPUTED_TEXT) for i in range(1, 11)]
        )

        assert outcome.interrupted
        # Спросили немного и перестали — а не все десять.
        assert len(model.prompts) < 10
        assert outcome.funnel.not_reached > 0

    async def test_verdicts_made_before_the_outage_survive(self) -> None:
        store = FakeStore()
        model = FakeModel(unavailable_after=2)
        use_case = JudgeDisputedUseCase(CRITERIA, model, store=store, concurrency=1)

        outcome = await use_case.execute(
            [candidate(i, DISPUTED_TEXT) for i in range(1, 8)]
        )

        assert len(store.saved) == 2
        assert len([v for v in outcome.verdicts if v.decided_by == "model"]) == 2

    async def test_one_broken_answer_does_not_stop_the_rest(self) -> None:
        """Сбой на одной закупке — её свойство, соседи не виноваты."""
        model = FakeModel(fail_on={1})
        outcome = await JudgeDisputedUseCase(CRITERIA, model, concurrency=1).execute(
            [candidate(i, DISPUTED_TEXT) for i in range(1, 4)]
        )

        assert outcome.funnel.failed == 1
        assert outcome.funnel.asked_model == 2
        assert not outcome.interrupted


class TestConcurrency:
    async def test_never_exceeds_the_limit(self) -> None:
        model = FakeModel()
        model.delay = 0.01
        use_case = JudgeDisputedUseCase(CRITERIA, model, concurrency=3)

        await use_case.execute([candidate(i, DISPUTED_TEXT) for i in range(1, 13)])

        assert model.peak <= 3

    async def test_limit_follows_the_load_level(self) -> None:
        model = FakeModel()
        model.delay = 0.01
        use_case = JudgeDisputedUseCase(CRITERIA, model, concurrency=1)
        await use_case.set_concurrency(4)

        await use_case.execute([candidate(i, DISPUTED_TEXT) for i in range(1, 9)])

        assert 1 < model.peak <= 4


class TestOnTheLabelledSet:
    """Тот же оракул, что и у ядра, но уже через полный разбор."""

    @staticmethod
    @pytest.fixture(scope="class")
    def golden() -> dict:
        return json.loads((FIXTURES / "hpk_golden.json").read_text(encoding="utf-8"))

    @staticmethod
    def candidates(golden: dict, label: str) -> list[TenderCandidate]:
        result = []
        for tender in golden["tenders"]:
            if tender["label"] != label:
                continue
            hits = []
            for hit in tender["hits"]:
                hits.extend(find_hits(hit["quote"], CRITERIA, file_name=hit["file_name"]))
            result.append(
                TenderCandidate(
                    tender_id=len(result) + 1,
                    reg_num=tender["reg_num"],
                    name=tender["name"],
                    hits=hits,
                )
            )
        return result

    async def test_no_false_positive_ever_reaches_the_model(self, golden: dict) -> None:
        """Все 20 отсекаются правилами — модель на них не тратится."""
        model = FakeModel()
        outcome = await JudgeDisputedUseCase(CRITERIA, model).execute(
            self.candidates(golden, "rejected")
        )

        assert model.prompts == []
        assert outcome.funnel.rejected_by_rules == 20

    async def test_confirmed_tenders_survive_the_full_pass(self, golden: dict) -> None:
        """Модель отвечает «подходит» — все 56 обязаны дойти до результата."""
        outcome = await JudgeDisputedUseCase(CRITERIA, FakeModel()).execute(
            self.candidates(golden, "confirmed")
        )

        confirmed = [
            v for v in outcome.verdicts if v.confidence is Confidence.CONFIRMED
        ]
        assert len(confirmed) == 56
        assert outcome.funnel.check()

    async def test_model_is_asked_about_a_small_minority(self, golden: dict) -> None:
        model = FakeModel()
        await JudgeDisputedUseCase(CRITERIA, model).execute(
            self.candidates(golden, "confirmed") + self.candidates(golden, "rejected")
        )
        assert len(model.prompts) <= 12


class FakeProgress:
    """Порт прогресса, который помнит все доклады."""

    def __init__(self, breaks: bool = False) -> None:
        self.reports: list[tuple[int, int]] = []
        self.breaks = breaks

    async def report(self, processed: int, total: int) -> None:
        if self.breaks:
            raise RuntimeError("база недоступна")
        self.reports.append((processed, total))


class TestProgress:
    """Судья — самая долгая фаза прогона, и она обязана быть видна.

    Пока докладов не было, шкала доходила до конца обхода корпуса и стояла там
    минуты: то есть утверждала, что прогон закончен, посреди работы модели.
    """

    async def test_every_candidate_is_reported(self) -> None:
        progress = FakeProgress()
        await JudgeDisputedUseCase(
            CRITERIA, FakeModel(), concurrency=1, progress=progress
        ).execute([candidate(i, DISPUTED_TEXT) for i in range(1, 6)])

        # Открывающий доклад плюс по одному на закупку.
        assert progress.reports == [(0, 5), (1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]

    async def test_the_opening_report_precedes_the_first_answer(self) -> None:
        """Фаза переключается до первого обращения к модели, а не после.

        Иначе экран показывал бы законченный обход корпуса всё то время, пока
        не вернётся первый вердикт, — а это минута и больше.
        """
        progress = FakeProgress()
        model = FakeModel()
        model.delay = 0.01
        await JudgeDisputedUseCase(
            CRITERIA, model, concurrency=1, progress=progress
        ).execute([candidate(1, DISPUTED_TEXT)])

        assert progress.reports[0] == (0, 1)

    async def test_progress_climbs_without_gaps(self) -> None:
        progress = FakeProgress()
        await JudgeDisputedUseCase(
            CRITERIA, FakeModel(), concurrency=4, progress=progress
        ).execute([candidate(i, DISPUTED_TEXT) for i in range(1, 13)])

        processed = [p for p, _ in progress.reports]
        assert processed == list(range(0, 13))

    async def test_failures_are_counted_as_progress_too(self) -> None:
        """Сбой на закупке — тоже пройденный шаг: полоса не имеет права встать."""
        progress = FakeProgress()
        outcome = await JudgeDisputedUseCase(
            CRITERIA, FakeModel(fail_on={1}), concurrency=1, progress=progress
        ).execute([candidate(i, DISPUTED_TEXT) for i in range(1, 4)])

        assert outcome.funnel.failed == 1
        assert progress.reports[-1] == (3, 3)

    async def test_a_broken_tracker_does_not_sink_the_run(self) -> None:
        """Инвариант 5: вспомогательное не роняет основное."""
        outcome = await JudgeDisputedUseCase(
            CRITERIA, FakeModel(), concurrency=1, progress=FakeProgress(breaks=True)
        ).execute([candidate(i, DISPUTED_TEXT) for i in range(1, 4)])

        assert outcome.funnel.asked_model == 3

    async def test_progress_is_optional(self) -> None:
        """Старые вызовы без порта остаются валидными."""
        outcome = await JudgeDisputedUseCase(CRITERIA, FakeModel()).execute(
            [candidate(1, DISPUTED_TEXT)]
        )

        assert outcome.funnel.asked_model == 1

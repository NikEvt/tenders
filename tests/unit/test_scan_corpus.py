"""Проход критерия по корпусу: предфильтр, чтение текстов, воронка."""

from __future__ import annotations

from collections.abc import AsyncIterator

from services.research.application.ports import CorpusDocument, CorpusTender
from services.research.application.use_cases.scan_corpus import ScanCorpusUseCase
from services.research.domain.criteria import OXYGEN_DEMAND_CRITERIA as CRITERIA


class FakeCorpus:
    def __init__(self, tenders, documents=None) -> None:
        self._tenders = tenders
        self._documents = documents or {}
        self.documents_asked: list[int] = []

    async def tenders(self, regions, since, until) -> AsyncIterator[CorpusTender]:
        for tender in self._tenders:
            yield tender

    async def documents(self, tender_id: int):
        self.documents_asked.append(tender_id)
        return self._documents.get(tender_id, [])

    async def count_tenders(self, regions, since, until) -> int:
        return len(self._tenders)


class FakeTexts:
    def __init__(self, texts: dict[str, str], broken: set[str] | None = None) -> None:
        self.texts = texts
        self.broken = broken or set()
        self.reads: list[str] = []

    async def read(self, text_key: str) -> str:
        self.reads.append(text_key)
        if text_key in self.broken:
            raise OSError("объект недоступен")
        return self.texts[text_key]


class FakeProgress:
    def __init__(self, breaks: bool = False) -> None:
        self.reports: list[tuple[int, int]] = []
        self.breaks = breaks

    async def report(self, processed: int, total: int) -> None:
        if self.breaks:
            raise RuntimeError("база недоступна")
        self.reports.append((processed, total))


class FakeHits:
    def __init__(self) -> None:
        self.saved: dict[int, list] = {}

    async def save(self, run_id, tender_id, hits) -> None:
        self.saved.setdefault(tender_id, []).extend(hits)


WATER = CorpusTender(
    tender_id=1,
    reg_num="R-1",
    name="Оказание услуг по химическому анализу сточных вод",
    okpd2_codes=("71.20.11",),
)
FURNITURE = CorpusTender(
    tender_id=2, reg_num="R-2", name="Поставка офисной мебели", okpd2_codes=("31.01.11",)
)


class TestPrefilter:
    async def test_unrelated_tenders_are_not_read_at_all(self) -> None:
        """Предфильтр экономит не разбор, а чтение: до документов дело не доходит."""
        corpus = FakeCorpus([FURNITURE])
        texts = FakeTexts({})

        stats = await ScanCorpusUseCase(CRITERIA, corpus, texts).execute()

        assert stats.tenders_candidate == 0
        assert corpus.documents_asked == []
        assert texts.reads == []

    async def test_related_tender_is_scanned(self) -> None:
        corpus = FakeCorpus(
            [WATER], {1: [CorpusDocument(10, "texts/aa/x.txt", "ТЗ.docx")]}
        )
        texts = FakeTexts({"texts/aa/x.txt": "Показатель ХПК не более 30 мг/дм3"})

        stats = await ScanCorpusUseCase(CRITERIA, corpus, texts).execute()

        assert stats.tenders_candidate == 1
        assert stats.hits_found == 1
        assert stats.tenders_with_hits == 1


class TestHits:
    async def test_card_itself_can_produce_a_hit(self) -> None:
        """Упоминание в названии — такая же находка, документы не обязательны."""
        tender = CorpusTender(
            tender_id=3,
            reg_num="R-3",
            name="Анализ сточных вод: ХПК, БПК5",
            okpd2_codes=("71.20.11",),
        )
        stats = await ScanCorpusUseCase(CRITERIA, FakeCorpus([tender]), FakeTexts({})).execute()

        assert stats.hits_found >= 1

    async def test_documents_without_text_are_skipped(self) -> None:
        corpus = FakeCorpus([WATER], {1: [CorpusDocument(10, None, "скан.pdf")]})
        texts = FakeTexts({})

        stats = await ScanCorpusUseCase(CRITERIA, corpus, texts).execute()

        assert texts.reads == []
        assert stats.documents_scanned == 0

    async def test_hits_are_saved_per_tender(self) -> None:
        corpus = FakeCorpus([WATER], {1: [CorpusDocument(10, "k", "ТЗ.docx")]})
        texts = FakeTexts({"k": "ХПК не более 30 мг/дм3"})
        hits = FakeHits()

        await ScanCorpusUseCase(CRITERIA, corpus, texts, hits=hits).execute(run_id=7)

        assert list(hits.saved) == [1]

    async def test_hit_count_per_tender_is_capped(self) -> None:
        documents = {1: [CorpusDocument(i, f"k{i}", f"д{i}.docx") for i in range(10)]}
        texts = FakeTexts({f"k{i}": "ХПК в сточных водах" for i in range(10)})

        stats = await ScanCorpusUseCase(
            CRITERIA, FakeCorpus([WATER], documents), texts
        ).execute()

        assert stats.hits_found <= CRITERIA.max_hits_per_document


class TestResilience:
    async def test_unreadable_object_does_not_break_the_pass(self) -> None:
        """Недоступный объект — не повод обрывать проход."""
        documents = {1: [CorpusDocument(10, "broken"), CorpusDocument(11, "good", "ТЗ.docx")]}
        texts = FakeTexts({"good": "ХПК не более 30 мг/дм3"}, broken={"broken"})

        stats = await ScanCorpusUseCase(
            CRITERIA, FakeCorpus([WATER], documents), texts
        ).execute()

        assert stats.documents_unreadable == 1
        assert stats.documents_scanned == 1
        assert stats.hits_found == 1


class TestFunnel:
    async def test_denominators_are_reported(self) -> None:
        """«Находок нет» без знаменателя не значит ничего.

        Знаменатель считается по тем же закупкам, что и числитель, — по
        кандидатам. Отдельный запрос по всему корпусу считал другую популяцию
        и завышал «не прочитано» в разы.
        """
        documents = {
            1: [CorpusDocument(10, "k", "ТЗ.docx"), CorpusDocument(11, None, "скан.pdf")],
            # Документы не-кандидата в знаменатель попадать не должны.
            2: [CorpusDocument(20, None, "смета.pdf")],
        }
        corpus = FakeCorpus([WATER, FURNITURE], documents)

        stats = await ScanCorpusUseCase(
            CRITERIA, corpus, FakeTexts({"k": "ХПК не более 30 мг/дм3"})
        ).execute()

        assert stats.tenders_total == 2
        assert stats.tenders_candidate == 1
        assert stats.documents_scanned == 1
        # То, до чего не дошли, видно отдельным числом — и сопоставимо с прочитанным.
        assert stats.documents_pending == 1

    async def test_progress_opens_and_closes(self) -> None:
        """Первый и последний доклад идут всегда: иначе полоса не появится."""
        progress = FakeProgress()

        await ScanCorpusUseCase(
            CRITERIA, FakeCorpus([WATER, FURNITURE]), FakeTexts({}), progress=progress
        ).execute()

        assert progress.reports[0] == (0, 2)
        assert progress.reports[-1] == (2, 2)

    async def test_progress_is_throttled(self) -> None:
        """Запись на каждую закупку при корпусе в сотни тысяч — своя же беда."""
        tenders = [
            CorpusTender(tender_id=i, reg_num=f"R-{i}", name="Поставка мебели")
            for i in range(1, 121)
        ]
        progress = FakeProgress()

        await ScanCorpusUseCase(
            CRITERIA, FakeCorpus(tenders), FakeTexts({}), progress=progress
        ).execute()

        # 0, 50, 100 и закрывающий 120 — а не сто двадцать записей подряд.
        assert [p for p, _ in progress.reports] == [0, 50, 100, 120]

    async def test_a_broken_progress_does_not_sink_the_scan(self) -> None:
        """Вспомогательное не роняет основное."""
        corpus = FakeCorpus([WATER], {1: [CorpusDocument(10, "k", "ТЗ.docx")]})

        stats = await ScanCorpusUseCase(
            CRITERIA,
            corpus,
            FakeTexts({"k": "ХПК не более 30 мг/дм3"}),
            progress=FakeProgress(breaks=True),
        ).execute()

        assert stats.hits_found == 1

    async def test_zero_hits_is_reported_with_its_denominator(self) -> None:
        corpus = FakeCorpus([WATER], {1: [CorpusDocument(10, "k", "ТЗ.docx")]})
        texts = FakeTexts({"k": "Поставка канцелярских товаров"})

        stats = await ScanCorpusUseCase(CRITERIA, corpus, texts).execute()

        assert stats.hits_found == 0
        # Ноль находок при одном прочитанном документе — это вывод.
        assert stats.documents_scanned == 1

"""Прогон критерия по накопленному корпусу.

Находки считаются из **сохранённого текста**, а не на лету во время скачивания.
Разница видна не сразу, но она принципиальная: разовый скрипт выбрасывал текст
после regex, и любая переклассификация требовала повторной выкачки — 84 ГБ
трафика ради правки одного шаблона. Теперь правка шаблона стоит одного прохода
по хранилищу.

Побочное следствие, ради которого это и сделано: `docs-worker` ничего не знает
ни про ХПК, ни про БПК, ни про предмет поиска вообще. Он извлекает текст,
движок ищет — и добавление нового критерия не трогает обработку документов.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date

from libs.shared.logging import get_logger
from services.research.application.ports import (
    CorpusDocument,
    CorpusPort,
    CorpusTender,
    HitRepositoryPort,
    ResearchRunPort,
    ScanStats,
    TenderCandidate,
    TextStoragePort,
)
from services.research.domain.criteria import Criteria
from services.research.domain.hits import Hit, find_hits, is_card_candidate

log = get_logger(__name__)


class ScanCorpusUseCase:
    """Ищет находки в текстах закупок-кандидатов.

    Controller: владеет порядком и параллельностью чтения, но не знает ни про
    SQL, ни про объектное хранилище.
    """

    def __init__(
        self,
        criteria: Criteria,
        corpus: CorpusPort,
        texts: TextStoragePort,
        hits: HitRepositoryPort | None = None,
        runs: ResearchRunPort | None = None,
        readers: int = 4,
    ) -> None:
        self._criteria = criteria
        self._corpus = corpus
        self._texts = texts
        self._hits = hits
        self._runs = runs
        self._readers = max(int(readers), 1)

    async def execute(
        self,
        run_id: int | None = None,
        regions: Sequence[str] | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> ScanStats:
        stats = ScanStats()
        stats.tenders_total = await self._corpus.count_tenders(regions, since, until)

        limit = asyncio.Semaphore(self._readers)

        async for tender in self._corpus.tenders(regions, since, until):
            # Предфильтр по карточке: скачивать и читать документы всех
            # извещений невозможно, а упоминание в большинстве из них
            # невозможно по смыслу.
            if not is_card_candidate(
                tender.name,
                tender.description,
                tender.okpd2_codes,
                tender.okpd2_names,
                self._criteria,
            ):
                continue

            stats.tenders_candidate += 1
            hits = await self._scan_tender(tender, stats, limit)
            if not hits:
                continue

            stats.tenders_with_hits += 1
            stats.hits_found += len(hits)

            candidate = TenderCandidate(
                tender_id=tender.tender_id,
                reg_num=tender.reg_num,
                name=tender.name,
                description=tender.description,
                customer_name=tender.customer_name,
                okpd2_code=tender.okpd2_code,
                hits=hits,
            )
            stats.candidates.append(candidate)

            if self._hits is not None and run_id is not None:
                await self._hits.save(run_id, tender.tender_id, hits)

        stats.documents_pending = await self._corpus.count_unscanned(regions, since, until)

        if self._runs is not None and run_id is not None:
            await self._runs.update_funnel(run_id, stats)

        log.info(
            "research.scan_finished",
            tenders=stats.tenders_total,
            candidates=stats.tenders_candidate,
            documents=stats.documents_scanned,
            pending=stats.documents_pending,
            hits=stats.hits_found,
        )
        return stats

    async def _scan_tender(
        self, tender: CorpusTender, stats: ScanStats, limit: asyncio.Semaphore
    ) -> list[Hit]:
        """Находки по карточке и по всем читаемым документам закупки."""
        hits = find_hits(
            f"{tender.name or ''} {tender.description or ''}", self._criteria
        )

        documents = await self._corpus.documents(tender.tender_id)
        if not documents:
            return hits[: self._criteria.max_hits_per_document]

        async def read(document: CorpusDocument) -> list[Hit]:
            async with limit:
                return await self._scan_document(document, stats)

        for found in await asyncio.gather(*(read(d) for d in documents)):
            hits.extend(found)

        return hits[: self._criteria.max_hits_per_document]

    async def _scan_document(self, document: CorpusDocument, stats: ScanStats) -> list[Hit]:
        if not document.text_key:
            return []
        try:
            text = await self._texts.read(document.text_key)
        except Exception as exc:
            # Недоступный объект — не повод обрывать проход: остальные
            # документы к нему отношения не имеют.
            stats.documents_unreadable += 1
            log.warning(
                "research.text_unreadable",
                document_id=document.document_id,
                error=str(exc),
            )
            return []

        stats.documents_scanned += 1
        return find_hits(
            text,
            self._criteria,
            file_name=document.file_name,
            page=None,
        )

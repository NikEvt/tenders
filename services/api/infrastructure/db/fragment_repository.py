"""Поиск по фрагментам документации.

Единица выдачи здесь — чанк, а не закупка: пользователь ищет формулировку в ТЗ
(«гарантия не менее трёх лет») и хочет увидеть саму фразу, а не карточку, внутри
которой она где-то есть.

Три режима существуют потому, что они находят разное. Лексический берёт точные
термины и артикулы, векторный — смысл без общих слов, `rrf` объединяет их по
рангам. Разложение оценок отдаётся наружу: по нему видно, почему фрагмент
оказался в выдаче.
"""

from __future__ import annotations

import re

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.contracts.ports import EmbedderPort
from libs.shared.db.schema import DocumentChunk, Tender, TenderDocument
from libs.shared.logging import get_logger
from services.api.application.ports.documents import FragmentSearchPort
from services.api.domain.documents import (
    Fragment,
    FragmentPage,
    FragmentScores,
    SearchMode,
)
from services.api.infrastructure.db.queries import RRF_K, clean_query

log = get_logger(__name__)

# Из каждого источника берём с запасом: слияние переупорядочит, и хвост одного
# списка может оказаться в голове итогового.
POOL = 300
# Слова короче трёх букв подсвечивать бессмысленно — они есть в любом тексте.
MIN_HIGHLIGHT_CHARS = 3


class SqlFragmentRepository(FragmentSearchPort):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: EmbedderPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder

    async def search(
        self, query: str, mode: SearchMode, page: int, page_size: int
    ) -> FragmentPage:
        cleaned = clean_query(query)
        if not cleaned:
            return FragmentPage(items=[], total=0, page=page, page_size=page_size)

        async with self._session_factory() as session:
            lexical = (
                await self._lexical(session, cleaned) if mode in ("lexical", "rrf") else {}
            )
            vector = (
                await self._semantic(session, cleaned) if mode in ("semantic", "rrf") else {}
            )
            ordered, fused = _merge(lexical, vector, mode)

            total = len(ordered)
            window = ordered[page * page_size : (page + 1) * page_size]
            if not window:
                return FragmentPage(items=[], total=total, page=page, page_size=page_size)

            rows = (
                await session.execute(self._columns().where(DocumentChunk.id.in_(window)))
            ).all()

        by_id = {row.chunk_id: row for row in rows}
        terms = _terms(cleaned)
        items = [
            _to_fragment(
                by_id[chunk_id],
                terms,
                lexical.get(chunk_id),
                vector.get(chunk_id),
                fused[chunk_id],
            )
            for chunk_id in window
            if chunk_id in by_id
        ]
        return FragmentPage(items=items, total=total, page=page, page_size=page_size)

    @staticmethod
    def _columns() -> Select:
        return (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.document_id,
                DocumentChunk.tender_id,
                DocumentChunk.text,
                DocumentChunk.char_start,
                DocumentChunk.char_end,
                TenderDocument.file_name.label("document_name"),
                Tender.reg_num,
                Tender.name.label("tender_name"),
                Tender.price.label("tender_price"),
            )
            .join(TenderDocument, TenderDocument.id == DocumentChunk.document_id)
            .join(Tender, Tender.id == DocumentChunk.tender_id)
        )

    async def _lexical(self, session: AsyncSession, query: str) -> dict[int, float]:
        tsquery = func.websearch_to_tsquery("russian", query)
        rank = func.ts_rank(DocumentChunk.search_tsv, tsquery)
        rows = (
            await session.execute(
                select(DocumentChunk.id, rank.label("rank"))
                .where(DocumentChunk.search_tsv.bool_op("@@")(tsquery))
                .order_by(rank.desc())
                .limit(POOL)
            )
        ).all()
        return {row.id: float(row.rank) for row in rows}

    async def _semantic(self, session: AsyncSession, query: str) -> dict[int, float]:
        if self._embedder is None:
            return {}
        try:
            vectors = await self._embedder.embed([query], is_query=True)
        except Exception as exc:
            # Без эмбеддингов режим вырождается в пустую выдачу, а не в ошибку:
            # клиент увидит, что векторной части нет, по разложению оценок.
            log.warning("fragments.embedding_unavailable", error=str(exc))
            return {}

        distance = DocumentChunk.embedding.cosine_distance(vectors[0])
        rows = (
            await session.execute(
                select(DocumentChunk.id, distance.label("distance"))
                .where(DocumentChunk.embedding.is_not(None))
                .order_by(distance)
                .limit(POOL)
            )
        ).all()
        return {row.id: 1.0 - float(row.distance) for row in rows}


def _merge(
    lexical: dict[int, float], vector: dict[int, float], mode: SearchMode
) -> tuple[list[int], dict[int, float]]:
    """Порядок выдачи и итоговая оценка каждого фрагмента в выбранном режиме."""
    if mode == "lexical":
        scores = dict(lexical)
    elif mode == "semantic":
        scores = dict(vector)
    else:
        scores = _rrf(lexical, vector)

    ordered = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return ordered, scores


def _rrf(lexical: dict[int, float], vector: dict[int, float]) -> dict[int, float]:
    """Складываются ранги, а не оценки: ts_rank и косинус лежат в разных шкалах."""
    scores: dict[int, float] = {}
    for position, chunk_id in enumerate(
        sorted(lexical, key=lambda cid: lexical[cid], reverse=True), start=1
    ):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position)
    for position, chunk_id in enumerate(
        sorted(vector, key=lambda cid: vector[cid], reverse=True), start=1
    ):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position)
    return scores


def _terms(query: str) -> list[str]:
    return [
        term.lower()
        for term in re.findall(r"[\w-]+", query)
        if len(term) >= MIN_HIGHLIGHT_CHARS
    ]


def _highlights(text: str, terms: list[str]) -> list[tuple[int, int]]:
    """Смещения совпадений внутри текста фрагмента.

    Ищем по началу слова: русская морфология даёт «гарантию», «гарантии»,
    «гарантией» — подсвечивать надо все, а не только точную форму запроса.
    """
    if not terms:
        return []

    lowered = text.lower()
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[\w-]+", lowered):
        word = match.group()
        if any(word.startswith(term[: max(MIN_HIGHLIGHT_CHARS, len(term) - 2)]) for term in terms):
            spans.append((match.start(), match.end()))
    return spans


def _to_fragment(
    row,
    terms: list[str],
    lexical: float | None,
    vector: float | None,
    score: float,
) -> Fragment:
    # `rrf` — итоговая оценка выбранного режима: по ней отсортирована выдача.
    # `lexical`/`vector` показывают, какая часть поиска фрагмент нашла; None
    # означает «этот источник его не выдал», а не «оценка ноль».
    scores = FragmentScores(lexical=lexical, vector=vector, rrf=round(score, 6))
    return Fragment(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        tender_id=row.tender_id,
        reg_num=row.reg_num,
        tender_name=row.tender_name,
        tender_price=row.tender_price,
        document_name=row.document_name,
        text=row.text,
        char_start=row.char_start,
        char_end=row.char_end,
        scores=scores,
        highlights=_highlights(row.text, terms),
    )

"""Гибридный поиск по каталогу: лексика ⊕ смысл."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.contracts.ports import EmbedderPort
from libs.shared.db.schema import DocumentChunk, Tender, TenderEmbedding
from libs.shared.logging import get_logger
from libs.shared.search_policy import cut_tail, relative_floor, semantic_floor
from services.api.application.ports.catalog import TenderCatalogPort, TenderSearchPort
from services.api.domain.models import Page, TenderFilter
from services.api.domain.pagination import PageRequest
from services.api.infrastructure.db.queries import (
    clean_query,
    conditions,
    fuse,
    summary_columns,
    to_summary,
)

log = get_logger(__name__)

# Ограничитель стоимости, а не смысла: сколько ближайших вообще рассматривать.
# Что из них считается совпадением, решает порог близости.
SEMANTIC_POOL = 300


class SqlSearchRepository(TenderSearchPort):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        catalog: TenderCatalogPort,
        embedder: EmbedderPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        # Пустой запрос — это обычный список; логика отбора не дублируется.
        self._catalog = catalog
        self._embedder = embedder

    async def matching_ids(self, query: str, filters: TenderFilter) -> list[int]:
        """Вся выдача запроса без постраничности — материал для фасетов."""
        cleaned = clean_query(query)
        if not cleaned:
            return []
        async with self._session_factory() as session:
            lexical, semantic = await self._sources(session, cleaned, _where(filters))
        return fuse(lexical, semantic)

    async def search(self, query: str, filters: TenderFilter, page: PageRequest) -> Page:
        cleaned = clean_query(query)
        if not cleaned:
            return await self._catalog.list(filters, page)

        page_size = page.limit
        offset = page.offset

        where = _where(filters)

        async with self._session_factory() as session:
            lexical_ids, semantic_ids = await self._sources(session, cleaned, where)

            ordered = fuse(lexical_ids, semantic_ids)
            total = len(ordered)
            window = ordered[offset : offset + page_size]
            if not window:
                return Page(items=[], total=total, page=page.page, page_size=page_size)

            rows = (await session.execute(summary_columns().where(Tender.id.in_(window)))).all()

        by_id = {row.id: row for row in rows}
        summaries = []
        for position, tender_id in enumerate(window):
            row = by_id.get(tender_id)
            if row is None:
                continue
            summary = to_summary(row)
            summary.relevance = round(1.0 / (1 + position + offset), 4)
            summaries.append(summary)

        # Курсора у гибридного поиска нет: порядок RRF считается в памяти и
        # не выражается предикатом «строго после этой строки».
        return Page(items=summaries, total=total, page=page.page, page_size=page_size)

    async def _sources(
        self, session: AsyncSession, cleaned: str, where: list
    ) -> tuple[list[int], list[int]]:
        """Лексическая и векторная выдачи по отдельности, до слияния.

        Вынесено, потому что потребителей два: сам поиск и фасеты, которым
        нужны те же идентификаторы. Считать их разными путями — значит снова
        разойтись в ответах.
        """
        tsquery = func.websearch_to_tsquery("russian", cleaned)
        chunk_match = (
            select(DocumentChunk.tender_id)
            .where(DocumentChunk.search_tsv.bool_op("@@")(tsquery))
            .scalar_subquery()
        )
        lexical_ids = list(
            (
                await session.scalars(
                    select(Tender.id)
                    .where(
                        and_(*where),
                        or_(
                            Tender.search_tsv.bool_op("@@")(tsquery),
                            Tender.id.in_(chunk_match),
                        ),
                    )
                    .order_by(func.ts_rank(Tender.search_tsv, tsquery).desc())
                    .limit(SEMANTIC_POOL)
                )
            ).all()
        )

        semantic_ids: list[int] = []
        if self._embedder is not None:
            try:
                vectors = await self._embedder.embed([cleaned], is_query=True)
                distance = TenderEmbedding.embedding.cosine_distance(vectors[0])
                rows = (
                    await session.execute(
                        select(
                            TenderEmbedding.tender_id, (1 - distance).label("similarity")
                        )
                        .join(Tender, Tender.id == TenderEmbedding.tender_id)
                        .where(
                            and_(*where),
                            # Без порога «ближайшие» — это весь корпус,
                            # и выдача перестаёт что-либо значить.
                            distance <= 1 - semantic_floor(),
                        )
                        .order_by(distance)
                        .limit(SEMANTIC_POOL)
                    )
                ).all()
                # Вторая отсечка — по отставанию от лидера: длинный запрос лежит
                # ближе ко всему подряд, и абсолютного порога ему мало.
                semantic_ids = cut_tail(
                    [(r.tender_id, float(r.similarity)) for r in rows], relative_floor()
                )
            except Exception as exc:
                # Без эмбеддингов поиск деградирует до лексического, но работает.
                log.warning("api.search_embedding_unavailable", error=str(exc))

        return lexical_ids, semantic_ids


def _where(filters: TenderFilter) -> list:
    """Условия отбора без текстового предиката.

    Текст приходит отдельным аргументом и работает поисковым запросом. Если
    оставить его ещё и предикатом, он применится дважды и разными способами:
    предикат отсечёт по точному совпадению словоформ до того, как отработает
    векторная часть, и выдача сузится до лексической. Именно так фасеты
    показывали 3 там, где список показывал 8.
    """
    return conditions(filters, without="q")

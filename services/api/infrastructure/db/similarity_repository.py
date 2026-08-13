"""Похожие закупки по «карточному» эмбеддингу.

Объяснение похожести собирается детерминированно из совпавших полей, а не
моделью: пользователю нужно проверяемое «совпадает ОКПД2 и регион», а не
пересказ, за который никто не отвечает.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import Tender, TenderEmbedding
from services.api.application.ports.catalog import TenderSimilarityPort
from services.api.domain.catalog import SimilarTender
from services.api.infrastructure.db.queries import summary_columns, to_summary

# Совпадение по первым четырём знакам ОКПД2 — это один вид продукции
# (`32.50` — медицинские инструменты), дальше идёт детализация модели.
OKPD2_GROUP_CHARS = 4
# Цены считаем сопоставимыми, если различаются не более чем вдвое.
PRICE_RATIO = 2


class SqlSimilarityRepository(TenderSimilarityPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def similar(self, tender_id: int, limit: int) -> list[SimilarTender]:
        async with self._session_factory() as session:
            source_vector = await session.scalar(
                select(TenderEmbedding.embedding).where(TenderEmbedding.tender_id == tender_id)
            )
            if source_vector is None:
                # Эмбеддинг ещё не посчитан — вкладка честно останется пустой.
                return []

            source = (
                await session.execute(summary_columns().where(Tender.id == tender_id))
            ).first()

            distance = TenderEmbedding.embedding.cosine_distance(source_vector)
            rows = (
                await session.execute(
                    summary_columns()
                    .add_columns(distance.label("distance"))
                    .join(TenderEmbedding, TenderEmbedding.tender_id == Tender.id)
                    .where(Tender.id != tender_id)
                    .order_by(distance)
                    .limit(limit)
                )
            ).all()

        return [
            SimilarTender(
                tender=to_summary(row),
                similarity=round(1.0 - float(row.distance), 4),
                driver=_driver(source, row),
            )
            for row in rows
        ]


def _driver(source, candidate) -> str:
    if source is None:
        return "близкая формулировка объекта закупки"

    reasons: list[str] = []
    if _same_okpd2_group(source.okpd2_code, candidate.okpd2_code):
        reasons.append("совпадает ОКПД2")
    if source.region_code and source.region_code == candidate.region_code:
        reasons.append("тот же регион")
    if source.customer_inn and source.customer_inn == candidate.customer_inn:
        reasons.append("тот же заказчик")
    if _comparable_price(source.price, candidate.price):
        reasons.append("сопоставимая цена")

    reasons.append("близкая формулировка объекта закупки")
    return " и ".join(reasons)


def _same_okpd2_group(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left[:OKPD2_GROUP_CHARS] == right[:OKPD2_GROUP_CHARS]


def _comparable_price(left, right) -> bool:
    if not left or not right:
        return False
    high, low = max(left, right), min(left, right)
    return high <= low * PRICE_RATIO

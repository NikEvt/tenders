"""История оценок и выигранных закупок."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import Tender, TenderFeedback, WonTender
from services.api.application.ports.profile import ProfileHistoryPort
from services.api.domain.profile import RatingRecord, WinRecord, WinsSummary


class SqlProfileHistoryRepository(ProfileHistoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ratings(self, page: int, page_size: int) -> tuple[list[RatingRecord], int]:
        async with self._session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(TenderFeedback))
            rows = (
                await session.execute(
                    select(
                        TenderFeedback.id,
                        TenderFeedback.tender_id,
                        TenderFeedback.signal,
                        TenderFeedback.created_at,
                        Tender.reg_num,
                        Tender.name,
                    )
                    .join(Tender, Tender.id == TenderFeedback.tender_id)
                    .order_by(TenderFeedback.created_at.desc())
                    .limit(page_size)
                    .offset(page * page_size)
                )
            ).all()

        return [
            RatingRecord(
                signal_id=row.id,
                tender_id=row.tender_id,
                reg_num=row.reg_num,
                name=row.name,
                signal=row.signal,
                created_at=row.created_at,
            )
            for row in rows
        ], (total or 0)

    async def wins(self) -> WinsSummary:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        WonTender.tender_id,
                        WonTender.won_at,
                        WonTender.contract_price,
                        WonTender.notes,
                        Tender.reg_num,
                        Tender.name,
                    )
                    .join(Tender, Tender.id == WonTender.tender_id)
                    .order_by(WonTender.won_at.desc().nullslast())
                )
            ).all()

        items = [
            WinRecord(
                tender_id=row.tender_id,
                reg_num=row.reg_num,
                name=row.name,
                won_at=row.won_at,
                contract_price=row.contract_price,
                notes=row.notes,
            )
            for row in rows
        ]
        # Сумма считается по фактической цене контракта: НМЦК завышена почти
        # всегда, и складывать её значило бы завышать итог.
        total = sum((i.contract_price for i in items if i.contract_price), Decimal("0"))
        return WinsSummary(items=items, total_value=total)

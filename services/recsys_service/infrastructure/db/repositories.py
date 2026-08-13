"""Репозитории рекомендательной системы."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import (
    RecommendationImpression,
    RecommendationProfile,
    Tender,
    TenderEmbedding,
    TenderFeedback,
    TenderView,
    WonTender,
)
from services.recsys_service.application.ports import (
    ProfileRepositoryPort,
    RecommendationRepositoryPort,
)
from services.recsys_service.domain.models import (
    MIN_DWELL_MS_FOR_SIGNAL,
    SIGNAL_WEIGHTS,
    Profile,
    Recommendation,
    RecommendationCandidate,
    Signal,
    WeightedSignal,
)

# Профиль единственный (однопользовательский режим), но с идентификатором:
# переход на многопользовательский станет миграцией, а не переписыванием.
PROFILE_ID = 1

# Сколько последних просмотров учитывать. Просмотры годичной давности говорят
# о прошлых проектах, а не о текущих интересах.
RECENT_VIEWS_LIMIT = 500


class SqlProfileRepository(ProfileRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_signals(self) -> list[WeightedSignal]:
        async with self._session_factory() as session:
            signals: list[WeightedSignal] = []
            signals.extend(await self._won(session))
            signals.extend(await self._explicit_feedback(session))
            signals.extend(await self._views(session))

        # Один тендер мог дать и просмотр, и лайк, и выигрыш — оставляем
        # сильнейший сигнал, иначе слабые размывают вес выигранных закупок.
        strongest: dict[int, WeightedSignal] = {}
        for signal in signals:
            current = strongest.get(signal.tender_id)
            if current is None or abs(signal.weight) > abs(current.weight):
                strongest[signal.tender_id] = signal
        return list(strongest.values())

    async def _won(self, session: AsyncSession) -> list[WeightedSignal]:
        rows = (
            await session.execute(
                _signal_columns()
                .join(WonTender, WonTender.tender_id == Tender.id)
            )
        ).all()
        return [_to_signal(row, Signal.WON) for row in rows]

    async def _explicit_feedback(self, session: AsyncSession) -> list[WeightedSignal]:
        rows = (
            await session.execute(
                _signal_columns()
                .add_columns(TenderFeedback.signal)
                .join(TenderFeedback, TenderFeedback.tender_id == Tender.id)
            )
        ).all()
        result: list[WeightedSignal] = []
        for row in rows:
            try:
                signal = Signal(row.signal)
            except ValueError:
                continue
            result.append(_to_signal(row, signal))
        return result

    async def _views(self, session: AsyncSession) -> list[WeightedSignal]:
        rows = (
            await session.execute(
                _signal_columns()
                .join(TenderView, TenderView.tender_id == Tender.id)
                .where(TenderView.dwell_ms >= MIN_DWELL_MS_FOR_SIGNAL)
                .order_by(TenderView.viewed_at.desc())
                .limit(RECENT_VIEWS_LIMIT)
            )
        ).all()
        return [_to_signal(row, Signal.VIEW) for row in rows]

    async def load_profile(self) -> Profile:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(RecommendationProfile).where(RecommendationProfile.id == PROFILE_ID)
            )
        if row is None:
            return Profile()
        return Profile(
            embedding=list(row.embedding) if row.embedding is not None else None,
            okpd2_weights=row.okpd2_weights or {},
            customer_weights=row.customer_weights or {},
            price_stats=row.price_stats or {},
            signal_count=row.signal_count,
            manual_weights=row.manual_weights or {},
        )

    async def save_profile(self, profile: Profile) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(RecommendationProfile).values(
                id=PROFILE_ID,
                embedding=profile.embedding,
                okpd2_weights=profile.okpd2_weights,
                customer_weights=profile.customer_weights,
                price_stats=profile.price_stats,
                signal_count=profile.signal_count,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[RecommendationProfile.id],
                    set_={
                        "embedding": statement.excluded.embedding,
                        "okpd2_weights": statement.excluded.okpd2_weights,
                        "customer_weights": statement.excluded.customer_weights,
                        "price_stats": statement.excluded.price_stats,
                        "signal_count": statement.excluded.signal_count,
                        # manual_weights намеренно не в списке: пересборка
                        # профиля не должна затирать правки пользователя.
                        "updated_at": func.now(),
                    },
                )
            )


    async def set_manual_weight(self, key: str, weight: float | None) -> Profile:
        """Ставит или снимает ручной вес.

        `None` — сброс к вычисленному значению, а не ноль: ноль означал бы
        «этот код мне не нужен», и это другое утверждение.
        """
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(RecommendationProfile).where(RecommendationProfile.id == PROFILE_ID)
            )
            manual = dict((row.manual_weights if row else None) or {})
            if weight is None:
                manual.pop(key, None)
            else:
                manual[key] = weight

            statement = pg_insert(RecommendationProfile).values(
                id=PROFILE_ID, manual_weights=manual
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[RecommendationProfile.id],
                    set_={"manual_weights": manual, "updated_at": func.now()},
                )
            )
        return await self.load_profile()


class SqlRecommendationRepository(RecommendationRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_similar(
        self, embedding: Sequence[float], limit: int, exclude: set[int]
    ) -> list[RecommendationCandidate]:
        async with self._session_factory() as session:
            distance = TenderEmbedding.embedding.cosine_distance(list(embedding))
            statement = (
                _candidate_columns()
                .add_columns(distance.label("distance"))
                .join(TenderEmbedding, TenderEmbedding.tender_id == Tender.id)
                .where(*_active_conditions(exclude))
                .order_by(distance)
                .limit(limit)
            )
            rows = (await session.execute(statement)).all()

        # cosine_distance ∈ [0, 2]; переводим в близость ∈ [0, 1].
        return [_to_candidate(row, similarity=max(0.0, 1.0 - row.distance)) for row in rows]

    async def find_fresh(self, limit: int, exclude: set[int]) -> list[RecommendationCandidate]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    _candidate_columns()
                    .where(*_active_conditions(exclude))
                    .order_by(Tender.publish_date.desc().nullslast())
                    .limit(limit)
                )
            ).all()
        return [_to_candidate(row, similarity=0.0) for row in rows]

    async def already_seen(self) -> set[int]:
        async with self._session_factory() as session:
            shown = (await session.scalars(select(RecommendationImpression.tender_id))).all()
            rated = (await session.scalars(select(TenderFeedback.tender_id))).all()
            won = (await session.scalars(select(WonTender.tender_id))).all()
        return set(shown) | set(rated) | set(won)

    async def save_impressions(self, recommendations: Sequence[Recommendation]) -> None:
        if not recommendations:
            return
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(RecommendationImpression).values(
                [
                    {
                        "tender_id": item.candidate.tender_id,
                        "score": item.score,
                        "explanation": item.breakdown.explain(),
                    }
                    for item in recommendations
                ]
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_recommendation_impression",
                    set_={
                        "score": statement.excluded.score,
                        "explanation": statement.excluded.explanation,
                        "shown_at": func.now(),
                    },
                )
            )

    async def record_feedback(
        self, tender_id: int, signal: Signal, reason: str | None
    ) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(TenderFeedback).values(
                tender_id=tender_id, signal=signal.value, reason=reason
            )
            # Один активный сигнал на тендер: пользователь может передумать.
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_tender_feedback",
                    set_={
                        "signal": statement.excluded.signal,
                        "reason": statement.excluded.reason,
                        "updated_at": func.now(),
                    },
                )
            )

    async def delete_feedback(self, signal_id: int) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                delete(TenderFeedback).where(TenderFeedback.id == signal_id)
            )
        return bool(result.rowcount)

    async def record_view(self, tender_id: int, dwell_ms: int | None) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                pg_insert(TenderView).values(tender_id=tender_id, dwell_ms=dwell_ms)
            )

    async def record_win(
        self,
        tender_id: int,
        won_at: date | None,
        contract_price: Decimal | None,
        notes: str | None,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            statement = pg_insert(WonTender).values(
                tender_id=tender_id,
                won_at=won_at,
                contract_price=contract_price,
                notes=notes,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_won_tender",
                    set_={
                        "won_at": statement.excluded.won_at,
                        "contract_price": statement.excluded.contract_price,
                        "notes": statement.excluded.notes,
                    },
                )
            )


def _signal_columns():
    return select(
        Tender.id.label("tender_id"),
        Tender.okpd2_code,
        Tender.price,
        Tender.customer_inn,
        TenderEmbedding.embedding,
    ).outerjoin(TenderEmbedding, TenderEmbedding.tender_id == Tender.id)


def _candidate_columns():
    return select(
        Tender.id,
        Tender.reg_num,
        Tender.name,
        Tender.description,
        Tender.price,
        Tender.customer_name,
        Tender.customer_inn,
        Tender.okpd2_code,
        Tender.publish_date,
        Tender.end_date,
    )


def _active_conditions(exclude: set[int]) -> list:
    conditions = [or_(Tender.end_date.is_(None), Tender.end_date >= func.now())]
    if exclude:
        conditions.append(Tender.id.notin_(list(exclude)))
    return conditions


def _to_signal(row, signal: Signal) -> WeightedSignal:
    return WeightedSignal(
        tender_id=row.tender_id,
        signal=signal,
        weight=SIGNAL_WEIGHTS[signal],
        embedding=list(row.embedding) if row.embedding is not None else None,
        okpd2_code=row.okpd2_code,
        price=row.price,
        customer_inn=row.customer_inn,
    )


def _to_candidate(row, similarity: float) -> RecommendationCandidate:
    return RecommendationCandidate(
        tender_id=row.id,
        reg_num=row.reg_num,
        name=row.name,
        description=row.description,
        price=row.price,
        customer_name=row.customer_name,
        customer_inn=row.customer_inn,
        okpd2_code=row.okpd2_code,
        publish_date=row.publish_date,
        end_date=row.end_date.date() if row.end_date else None,
        similarity=similarity,
    )

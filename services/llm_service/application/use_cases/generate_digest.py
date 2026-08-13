"""Ежедневная ИИ-сводка новых закупок."""

from __future__ import annotations

from datetime import date

from libs.shared.contracts.events import DigestRequested
from libs.shared.logging import get_logger
from services.llm_service.application.ports import (
    DigestRepositoryPort,
    LlmPort,
    LlmUnavailable,
)
from services.llm_service.application.prompts import (
    CLUSTER_SUMMARY_SYSTEM,
    CLUSTER_SUMMARY_USER,
    DIGEST_SYSTEM,
    DIGEST_USER,
)
from services.llm_service.domain.models import DIGEST_PROMPT_VERSION, DigestInput

log = get_logger(__name__)

# Категорий за день бывает под сотню; в сводку идут крупнейшие, остальные
# схлопываются в общий счётчик.
MAX_CLUSTERS = 8
MAX_TENDERS_PER_CLUSTER = 10
MAX_TOP_TENDERS = 10


class GenerateDigestUseCase:
    """Map-reduce: резюме по категориям, затем общая сводка.

    Прямая попытка отдать модели все закупки за день не влезает в контекст и даёт
    поверхностный пересказ; разбиение по категориям сохраняет детали.
    """

    def __init__(self, llm: LlmPort, repository: DigestRepositoryPort) -> None:
        self._llm = llm
        self._repository = repository

    async def execute(self, event: DigestRequested) -> None:
        if not event.force and await self._repository.exists(event.digest_date):
            log.info("digest.already_exists", digest_date=event.digest_date.isoformat())
            return

        data = await self._repository.collect(event.digest_date)
        if data.total == 0:
            await self._repository.save(
                event.digest_date,
                f"## Главное\n\nЗа {event.digest_date.isoformat()} новых закупок не найдено.",
                {"total": 0},
                0,
                self._llm.model_name,
                DIGEST_PROMPT_VERSION,
            )
            return

        cluster_summaries = await self._summarize_clusters(data)
        summary = await self._reduce(data, cluster_summaries)

        await self._repository.save(
            digest_date=event.digest_date,
            summary_md=summary,
            sections={
                "clusters": cluster_summaries,
                "top": [
                    {"reg_num": t.reg_num, "name": t.name, "price": str(t.price)}
                    for t in data.top_by_price
                ],
                "deadline_changes": [t.reg_num for t in data.deadline_changes],
                "new_customers": data.new_customers,
            },
            tender_count=data.total,
            model=self._llm.model_name,
            prompt_version=DIGEST_PROMPT_VERSION,
        )
        log.info("digest.saved", digest_date=event.digest_date.isoformat(), total=data.total)

    async def _summarize_clusters(self, data: DigestInput) -> dict[str, str]:
        """Map-фаза: короткое резюме на категорию."""
        biggest = sorted(data.clusters.items(), key=lambda kv: len(kv[1]), reverse=True)
        summaries: dict[str, str] = {}

        for category, tenders in biggest[:MAX_CLUSTERS]:
            listing = "\n".join(
                f"- {t.name or t.description or t.reg_num} "
                f"({t.price if t.price is not None else '—'} руб., {t.customer_name or '—'})"
                for t in tenders[:MAX_TENDERS_PER_CLUSTER]
            )
            try:
                summaries[category] = await self._llm.complete(
                    system=CLUSTER_SUMMARY_SYSTEM,
                    user=CLUSTER_SUMMARY_USER.format(
                        category=category, count=len(tenders), tenders=listing
                    ),
                    max_tokens=400,
                )
            except LlmUnavailable:
                # Одна упавшая категория не должна лишать пользователя всей сводки.
                log.warning("digest.cluster_failed", category=category)
                summaries[category] = f"Закупок в категории: {len(tenders)}."

        return summaries

    async def _reduce(self, data: DigestInput, clusters: dict[str, str]) -> str:
        top = "\n".join(
            f"- {t.reg_num}: {t.name or '—'} — "
            f"{t.price if t.price is not None else '—'} руб., заказчик: {t.customer_name or '—'}"
            for t in data.top_by_price[:MAX_TOP_TENDERS]
        )
        cluster_text = "\n\n".join(f"### {name}\n{text}" for name, text in clusters.items())
        deadlines = (
            "\n".join(
                f"- {t.reg_num}: {t.name or '—'} — новый срок "
                f"{t.end_date.isoformat() if t.end_date else '—'}"
                for t in data.deadline_changes[:MAX_TOP_TENDERS]
            )
            or "Изменений нет."
        )

        try:
            return await self._llm.complete(
                system=DIGEST_SYSTEM,
                user=DIGEST_USER.format(
                    digest_date=data.digest_date.isoformat(),
                    total=data.total,
                    total_price=data.total_price,
                    top=top,
                    clusters=cluster_text,
                    deadlines=deadlines,
                ),
                max_tokens=2500,
            )
        except LlmUnavailable:
            # Модель недоступна — отдаём фактическую сводку без пересказа,
            # это полезнее пустой страницы.
            log.warning("digest.llm_unavailable, собираем сводку без модели")
            return _fallback_digest(data, top, deadlines)


def _fallback_digest(data: DigestInput, top: str, deadlines: str) -> str:
    return (
        f"## Главное\n\n"
        f"За {data.digest_date.isoformat()} опубликовано закупок: {data.total}, "
        f"суммарная НМЦК: {data.total_price} руб.\n\n"
        f"## Крупнейшие закупки\n\n{top}\n\n"
        f"## Изменившиеся сроки\n\n{deadlines}\n\n"
        f"_Текстовая сводка не сформирована: языковая модель недоступна._"
    )


def digest_date_for(today: date) -> date:
    """Сводка формируется за завершившийся день."""
    from datetime import timedelta

    return today - timedelta(days=1)

"""Ежедневная ИИ-сводка новых закупок."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from libs.shared.contracts.events import DigestRequested
from libs.shared.day_completeness import is_closed
from libs.shared.logging import get_logger
from services.llm_service.application.ports import (
    DigestRepositoryPort,
    JobTrackerPort,
    LlmPort,
    LlmUnavailable,
)
from services.llm_service.application.prompts import (
    CLUSTER_SUMMARY_SYSTEM,
    CLUSTER_SUMMARY_USER,
    DIGEST_SYSTEM,
    DIGEST_USER,
)
from services.llm_service.domain.models import (
    DIGEST_PROMPT_VERSION,
    DigestInput,
    DigestScope,
)

log = get_logger(__name__)

# Категорий за день бывает под сотню; в сводку идут крупнейшие, остальные
# схлопываются в общий счётчик.
MAX_CLUSTERS = 8
MAX_TENDERS_PER_CLUSTER = 10
MAX_TOP_TENDERS = 10

#: Сколько черновик считается свежим. Сборка — до девяти обращений к модели, и
#: пересобирать один и тот же идущий день на каждый рестарт сервиса значит
#: платить за него многократно.
DRAFT_MAX_AGE = timedelta(hours=1)

#: Фазы сборки — то, что видно на шкале ожидания. Сборка идёт минутами, и без
#: имени фазы «идёт» ничем не отличается от «встало».
PHASE_COLLECT = "сбор закупок за день"
PHASE_SUMMARIZE = "резюме по категориям"


class GenerateDigestUseCase:
    """Map-reduce: резюме по категориям, затем общая сводка.

    Прямая попытка отдать модели все закупки за день не влезает в контекст и даёт
    поверхностный пересказ; разбиение по категориям сохраняет детали.
    """

    def __init__(
        self,
        llm: LlmPort,
        repository: DigestRepositoryPort,
        jobs: JobTrackerPort | None = None,
    ) -> None:
        self._llm = llm
        self._repository = repository
        self._jobs = jobs

    async def execute(self, event: DigestRequested) -> None:
        """Собирает сводку и ведёт по ней задание.

        Идентификатор задания — идентификатор события: `POST /digest/{date}`
        уже возвращает именно его, не хватало только строки в таблице. Без неё
        экран опрашивал задание, которого нет, и пересборка не завершалась
        никогда — сборка идёт минутами, и молчать столько нельзя.
        """
        job_id = str(event.event_id)
        await self._start_job(job_id)
        try:
            result = await self._build(event)
        except Exception as exc:
            # Ошибка обязана доехать до экрана — и всё равно уйти наверх, иначе
            # ломается разбор очереди с повторами и dead-letter.
            await self._finish_job(job_id, error=str(exc))
            raise
        await self._finish_job(job_id, result=result)

    async def _build(self, event: DigestRequested) -> dict:
        if not event.force and await self._is_fresh_enough(event.digest_date):
            log.info("digest.up_to_date", digest_date=event.digest_date.isoformat())
            # Задание всё равно завершается: непринудительный запрос иначе
            # оставил бы экран с вечным «идёт сборка».
            return {"digest_date": event.digest_date.isoformat(), "skipped": True}

        data = await self._repository.collect(event.digest_date)
        if data.total == 0:
            await self._repository.save(
                event.digest_date,
                _empty_digest(data),
                {"total": 0, "scope": _scope_section(data.scope)},
                0,
                self._llm.model_name,
                DIGEST_PROMPT_VERSION,
            )
            return {"digest_date": event.digest_date.isoformat(), "tender_count": 0}

        # Шагов ровно столько, сколько обращений к модели: резюме по категориям
        # плюс сведение. Это первое место в проекте, где полоса прогресса
        # показывает число, а не бесконечный волчок.
        await self._set_total(str(event.event_id), min(len(data.clusters), MAX_CLUSTERS) + 1)

        cluster_summaries = await self._summarize_clusters(data, str(event.event_id))
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
                # Область отбора едет вместе со сводкой: «16 закупок» означает
                # разное для всего дня и для отбора по двум фильтрам.
                "scope": _scope_section(data.scope),
            },
            tender_count=data.total,
            model=self._llm.model_name,
            prompt_version=DIGEST_PROMPT_VERSION,
        )
        log.info("digest.saved", digest_date=event.digest_date.isoformat(), total=data.total)
        return {"digest_date": event.digest_date.isoformat(), "tender_count": data.total}

    async def _is_fresh_enough(self, digest_date: date) -> bool:
        """Можно ли не пересобирать сводку.

        Два случая, и они разные.

        **Окончательная** — собрана после окончания своего дня. Такую не
        пересобирают никогда: день закрыт, данные по нему больше не едут. То же
        правило, по которому краулер не считает закрытым сегодняшний суточный
        архив.

        **Свежий черновик** — собран за идущий день меньше часа назад.
        Пересобирать его на каждый рестарт сервиса значило бы платить моделью
        за один и тот же день по десять раз: сборка — это до девяти обращений.
        Час выбран так, чтобы утренняя сборка и ручная пересборка не мешали
        друг другу, а данные всё равно догонялись в течение дня.
        """
        built_at = await self._repository.built_at(digest_date)
        if built_at is None:
            return False
        if is_closed(digest_date, built_at.date()):
            return True
        return datetime.now(UTC) - built_at < DRAFT_MAX_AGE

    # ─── Учёт задания ───────────────────────────────────────────────────────
    # Отметка о начале и прогресс — вспомогательные: их отказ не повод ронять
    # сводку. Завершение и ошибка — нет: проглоченное завершение оставляет на
    # экране вечный волчок, что хуже любой ошибки.

    async def _start_job(self, job_id: str) -> None:
        """Начало сборки. Объёма работы здесь ещё нет — его узнают после сбора.

        `total = 0` уходит наружу как «неизвестно», а не как ноль: шкала в этой
        фазе неопределённая, и это честно — считать пока нечего.
        """
        if self._jobs is None:
            return
        try:
            await self._jobs.start(job_id, "digest", 0, PHASE_COLLECT)
        except Exception as exc:
            log.warning("digest.job_start_failed", job_id=job_id, error=str(exc))

    async def _set_total(self, job_id: str, total: int) -> None:
        if self._jobs is None:
            return
        try:
            await self._jobs.start(job_id, "digest", total, PHASE_SUMMARIZE)
        except Exception as exc:
            log.warning("digest.job_total_failed", job_id=job_id, error=str(exc))

    async def _report(self, job_id: str, processed: int) -> None:
        if self._jobs is None:
            return
        try:
            await self._jobs.progress(job_id, processed)
        except Exception as exc:
            log.warning("digest.job_progress_failed", job_id=job_id, error=str(exc))

    async def _finish_job(
        self, job_id: str, result: dict | None = None, error: str | None = None
    ) -> None:
        if self._jobs is None:
            return
        if error is not None:
            await self._jobs.fail(job_id, error)
        else:
            await self._jobs.finish(job_id, result or {})

    async def _summarize_clusters(
        self, data: DigestInput, job_id: str | None = None
    ) -> dict[str, str]:
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

            if job_id is not None:
                await self._report(job_id, len(summaries))

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


def _scope_section(scope: DigestScope) -> dict:
    """Область отбора в разделах сводки — чтобы клиент не выводил её сам."""
    return {
        "filters": scope.filters,
        "unrun_filters": scope.unrun_filters,
        "filtered": scope.filtered,
    }


def _empty_digest(data: DigestInput) -> str:
    """Пустая сводка обязана объяснить, почему она пустая.

    «Новых закупок не найдено» и «ни одна закупка не прошла ваши фильтры» —
    разные утверждения, и путать их нельзя: первое про рынок, второе про
    настройки. А фильтр, который ни разу не прогоняли, не приносит закупок
    вовсе, и молчать об этом значит выдать несделанную работу за вывод.
    """
    day = data.digest_date.isoformat()
    if not data.scope.filtered:
        return f"## Главное\n\nЗа {day} новых закупок не найдено."

    names = ", ".join(data.scope.filters)
    text = f"## Главное\n\nЗа {day} ни одна закупка не прошла отбор ({names})."
    if data.scope.unrun_filters:
        text += (
            f"\n\nФильтры {', '.join(data.scope.unrun_filters)} ещё ни разу не "
            "запускались: по ним нет вердиктов, поэтому они не могли ничего "
            "принести. Это не вывод о рынке."
        )
    return text


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

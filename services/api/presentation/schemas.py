"""DTO внешнего API. Отделены от доменных моделей: контракт наружу
меняется по своим причинам, а не вслед за внутренним рефакторингом."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from libs.shared.load_policy import LoadBudget
from services.api.domain.catalog import (
    FacetBucket,
    Facets,
    GroupBucket,
    RestrictiveHint,
    SimilarTender,
)
from services.api.domain.corpus import CorpusOverview, CorpusProcessing, Distribution
from services.api.domain.documents import ChunkOutline, FragmentPage
from services.api.domain.filters import SavedFilterCard
from services.api.domain.jobs import JobView
from services.api.domain.models import (
    DownloadLink,
    Page,
    TenderDetail,
    TenderDocumentInfo,
    TenderSummary,
)
from services.api.domain.monitoring import (
    CrawlerRunView,
    PipelineFunnel,
    QueuesSnapshot,
    ServiceHealth,
    TenderEvent,
)
from services.api.domain.profile import RatingRecord, WinsSummary
from services.api.domain.research import (
    MarketView,
    ResearchFunnel,
    ResearchHitView,
    ResearchRunCard,
    ResearchTenderRow,
)
from services.api.domain.settings import EffectiveSettings


class TenderOut(BaseModel):
    tender_id: int
    reg_num: str
    name: str | None
    description: str | None
    price: Decimal | None
    currency: str | None
    customer_name: str | None
    customer_inn: str | None
    okpd2_code: str | None
    okpd2_name: str | None
    region_code: str | None
    publish_date: datetime | None
    start_date: datetime | None
    end_date: datetime | None
    prev_end_date: datetime | None
    deadline_changed: bool
    status: str | None
    documents_status: str
    document_count: int
    relevance: float | None = None

    @classmethod
    def of(cls, summary: TenderSummary) -> TenderOut:
        return cls(
            tender_id=summary.tender_id,
            reg_num=summary.reg_num,
            name=summary.name,
            description=summary.description,
            price=summary.price,
            currency=summary.currency,
            customer_name=summary.customer_name,
            customer_inn=summary.customer_inn,
            okpd2_code=summary.okpd2_code,
            okpd2_name=summary.okpd2_name,
            region_code=summary.region_code,
            publish_date=summary.publish_date,
            start_date=summary.start_date,
            end_date=summary.end_date,
            prev_end_date=summary.prev_end_date,
            deadline_changed=summary.deadline_changed,
            status=summary.status,
            documents_status=summary.documents_status,
            document_count=summary.document_count,
            relevance=summary.relevance,
        )


class PageOut(BaseModel):
    items: list[TenderOut]
    total: int
    # null в курсорном режиме: номера страницы там нет, и подставлять ноль
    # значило бы сообщать клиенту неправду.
    page: int | None
    page_size: int
    total_pages: int
    next_cursor: str | None = None

    @classmethod
    def of(cls, page: Page) -> PageOut:
        return cls(
            items=[TenderOut.of(item) for item in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            total_pages=page.total_pages,
            next_cursor=page.next_cursor,
        )


class FacetBucketOut(BaseModel):
    key: str
    label: str
    count: int

    @classmethod
    def of(cls, bucket: FacetBucket) -> FacetBucketOut:
        # Доменные модели — dataclass со slots: `vars()` на них не работает.
        return cls(key=bucket.key, label=bucket.label, count=bucket.count)


class PriceBucketOut(BaseModel):
    price_from: Decimal
    price_to: Decimal
    count: int


class RestrictiveHintOut(BaseModel):
    """Какое условие отсекает больше всего и сколько нашлось бы без него."""

    param: str
    kept: int
    dropped: int


class FacetsOut(BaseModel):
    total: int
    regions: list[FacetBucketOut]
    okpd2: list[FacetBucketOut]
    customers: list[FacetBucketOut]
    price_histogram: list[PriceBucketOut]
    restrictive: RestrictiveHintOut | None = None

    @classmethod
    def of(cls, facets: Facets, hint: RestrictiveHint | None) -> FacetsOut:
        return cls(
            total=facets.total,
            regions=[FacetBucketOut.of(b) for b in facets.regions],
            okpd2=[FacetBucketOut.of(b) for b in facets.okpd2],
            customers=[FacetBucketOut.of(b) for b in facets.customers],
            price_histogram=[
                PriceBucketOut(price_from=b.price_from, price_to=b.price_to, count=b.count)
                for b in facets.price_histogram
            ],
            restrictive=(
                RestrictiveHintOut(param=hint.param, kept=hint.kept, dropped=hint.dropped)
                if hint
                else None
            ),
        )


class GroupBucketOut(BaseModel):
    key: str
    label: str
    count: int
    total_price: Decimal | None = None


class GroupsOut(BaseModel):
    """Оглавление сгруппированного списка: по шапке на группу."""

    field: str
    items: list[GroupBucketOut]

    @classmethod
    def of(cls, field: str, buckets: list[GroupBucket]) -> GroupsOut:
        return cls(
            field=field,
            items=[
                GroupBucketOut(
                    key=b.key, label=b.label, count=b.count, total_price=b.total_price
                )
                for b in buckets
            ],
        )


class SimilarTenderOut(BaseModel):
    tender: TenderOut
    similarity: float
    driver: str


class SimilarOut(BaseModel):
    items: list[SimilarTenderOut]

    @classmethod
    def of(cls, similar: list[SimilarTender]) -> SimilarOut:
        return cls(
            items=[
                SimilarTenderOut(
                    tender=TenderOut.of(s.tender), similarity=s.similarity, driver=s.driver
                )
                for s in similar
            ]
        )


class DigestDatesOut(BaseModel):
    dates: list[date]


class DocumentOut(BaseModel):
    document_id: int
    file_name: str | None
    doc_kind_name: str | None
    file_size: int | None
    extraction_status: str
    page_count: int | None
    ocr_used: bool
    char_count: int | None
    has_text: bool

    @classmethod
    def of(cls, info: TenderDocumentInfo) -> DocumentOut:
        # Поля перечислены явно: доменная модель — dataclass со slots, у неё нет
        # __dict__, и `vars(info)` на ней падает.
        return cls(
            document_id=info.document_id,
            file_name=info.file_name,
            doc_kind_name=info.doc_kind_name,
            file_size=info.file_size,
            extraction_status=info.extraction_status,
            page_count=info.page_count,
            ocr_used=info.ocr_used,
            char_count=info.char_count,
            has_text=info.has_text,
        )


class TenderDetailOut(BaseModel):
    tender: TenderOut
    documents: list[DocumentOut]
    verdicts: list[dict]

    @classmethod
    def of(cls, detail: TenderDetail) -> TenderDetailOut:
        return cls(
            tender=TenderOut.of(detail.summary),
            documents=[DocumentOut.of(d) for d in detail.documents],
            verdicts=detail.verdicts,
        )


class ChunkOutlineOut(BaseModel):
    chunk_id: int
    ordinal: int
    # null у документов, нарезанных до появления смещений: подсветить цитату
    # там нечем, и клиент узнаёт об этом из ответа, а не догадывается.
    char_start: int | None
    char_end: int | None
    page: int | None


class DocumentChunksOut(BaseModel):
    document_id: int
    chunks: list[ChunkOutlineOut]

    @classmethod
    def of(cls, document_id: int, chunks: list[ChunkOutline]) -> DocumentChunksOut:
        return cls(
            document_id=document_id,
            chunks=[
                ChunkOutlineOut(
                    chunk_id=c.chunk_id,
                    ordinal=c.ordinal,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    page=c.page,
                )
                for c in chunks
            ],
        )


class FragmentScoresOut(BaseModel):
    """Разложение оценки: видно, какая часть поиска нашла фрагмент."""

    lexical: float | None
    vector: float | None
    rrf: float


class FragmentOut(BaseModel):
    chunk_id: int
    document_id: int
    tender_id: int
    reg_num: str
    tender_name: str | None
    tender_price: Decimal | None
    document_name: str | None
    text: str
    char_start: int | None
    char_end: int | None
    highlights: list[tuple[int, int]]
    scores: FragmentScoresOut


class FragmentPageOut(BaseModel):
    items: list[FragmentOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def of(cls, found: FragmentPage) -> FragmentPageOut:
        return cls(
            items=[
                FragmentOut(
                    chunk_id=f.chunk_id,
                    document_id=f.document_id,
                    tender_id=f.tender_id,
                    reg_num=f.reg_num,
                    tender_name=f.tender_name,
                    tender_price=f.tender_price,
                    document_name=f.document_name,
                    text=f.text,
                    char_start=f.char_start,
                    char_end=f.char_end,
                    highlights=f.highlights,
                    scores=FragmentScoresOut(
                        lexical=f.scores.lexical, vector=f.scores.vector, rrf=f.scores.rrf
                    ),
                )
                for f in found.items
            ],
            total=found.total,
            page=found.page,
            page_size=found.page_size,
        )


class CompileFilterIn(BaseModel):
    query: str = Field(min_length=3, max_length=2000)


class SaveFilterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=3, max_length=2000)
    # Правки конструктора: снятый критерий судьи, убранный регион, поправленный
    # порог. Передан — сохраняется как есть, и работа пользователя не теряется.
    spec: dict | None = None


class PatchFilterIn(BaseModel):
    """Частичное изменение. Не переданное поле не трогается."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    spec: dict | None = None
    in_digest: bool | None = None
    notify: bool | None = None
    is_active: bool | None = None


class TestFilterIn(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class MatchCountOut(BaseModel):
    day: date
    count: int


class FilterOut(BaseModel):
    filter_id: int
    name: str
    query: str
    spec: dict
    in_digest: bool
    notify: bool
    is_active: bool
    created_at: datetime
    last_run_at: datetime | None
    match_counts: list[MatchCountOut]

    @classmethod
    def of(cls, card: SavedFilterCard) -> FilterOut:
        return cls(
            filter_id=card.filter_id,
            name=card.name,
            query=card.query,
            spec=card.spec,
            in_digest=card.in_digest,
            notify=card.notify,
            is_active=card.is_active,
            created_at=card.created_at,
            last_run_at=card.last_run_at,
            match_counts=[MatchCountOut(day=c.day, count=c.count) for c in card.match_counts],
        )


class CrawlIn(BaseModel):
    """Заявка на выгрузку.

    Умолчание — вчера и сегодня: ЕИС публикует с задержкой, и вчерашний архив
    к утру ещё дописывается. Пустые регионы означают «все настроенные у
    краулера»: какие именно он качает, шлюз не знает.
    """

    since: date | None = None
    until: date | None = None
    regions: list[str] = Field(default_factory=list)


class JobAcceptedOut(BaseModel):
    """Ответ на команду, которая исполняется не сразу."""

    job_id: str


class JobOut(BaseModel):
    """Состояние длительной операции.

    `total` намеренно допускает `null`: объём фазы известен не сразу — сборка
    сводки узнаёт его после кластеризации, обход корпуса после подсчёта. Ноль
    вместо `null` заставил бы клиента показать «0 %» там, где считать ещё
    нечего, то есть выдумать число.
    """

    job_id: str
    kind: str
    status: str
    phase: str | None = None
    total: int | None = None
    processed: int = 0
    result: dict | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, job: JobView) -> JobOut:
        return cls(
            job_id=job.job_id,
            kind=job.kind,
            status=job.status,
            phase=job.phase,
            total=job.total,
            processed=job.processed,
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class RunFilterIn(BaseModel):
    """Охват прогона: сроки и регионы. Критерий задан путём.

    Регионы перекрывают структурные условия критерия, а не дополняют их:
    выбранный охват должен совпадать с тем, что покажет воронка.
    """

    since: date | None = None
    until: date | None = None
    regions: list[str] = Field(default_factory=list)


class FeedbackIn(BaseModel):
    tender_id: int
    signal: str = Field(pattern="^(like|dislike|hide|shortlist)$")
    reason: str | None = Field(default=None, max_length=1000)


class ViewIn(BaseModel):
    tender_id: int
    dwell_ms: int | None = Field(default=None, ge=0)


class WinIn(BaseModel):
    tender_id: int
    won_at: date | None = None
    contract_price: Decimal | None = None
    notes: str | None = Field(default=None, max_length=2000)


class DownloadOut(BaseModel):
    url: str
    file_name: str | None
    expires_in: int

    @classmethod
    def of(cls, link: DownloadLink) -> DownloadOut:
        return cls(url=link.url, file_name=link.file_name, expires_in=link.expires_in)


# ─── Мониторинг ───────────────────────────────────────────────────────────────


class ServiceHealthOut(BaseModel):
    name: str
    status: str
    port: int | None
    p95_ms: float | None
    # Ключи разные у разных сервисов: это карточка, а не строка таблицы.
    facts: dict[str, object]


class HealthOut(BaseModel):
    services: list[ServiceHealthOut]

    @classmethod
    def of(cls, services: list[ServiceHealth]) -> HealthOut:
        return cls(
            services=[
                ServiceHealthOut(
                    name=s.name, status=s.status, port=s.port, p95_ms=s.p95_ms, facts=s.facts
                )
                for s in services
            ]
        )


class QueueStatOut(BaseModel):
    name: str
    depth: int
    consumers: int
    dead_letters: int


class RetryStageOut(BaseModel):
    stage: str
    depth: int


class DeadLetterOut(BaseModel):
    message_id: str
    event: str
    error: str | None
    retry_stage: str | None
    failed_at: datetime | None


class QueuesOut(BaseModel):
    queues: list[QueueStatOut]
    retry_ladder: list[RetryStageOut]
    dead_letters: list[DeadLetterOut]

    @classmethod
    def of(cls, snapshot: QueuesSnapshot) -> QueuesOut:
        return cls(
            queues=[
                QueueStatOut(
                    name=q.name,
                    depth=q.depth,
                    consumers=q.consumers,
                    dead_letters=q.dead_letters,
                )
                for q in snapshot.queues
            ],
            retry_ladder=[
                RetryStageOut(stage=s.stage, depth=s.depth) for s in snapshot.retry_ladder
            ],
            dead_letters=[
                DeadLetterOut(
                    message_id=d.message_id,
                    event=d.event,
                    error=d.error,
                    retry_stage=d.retry_stage,
                    failed_at=d.failed_at,
                )
                for d in snapshot.dead_letters
            ],
        )


class CrawlerRunOut(BaseModel):
    run_id: int
    target_date: str | None
    status: str
    fetched: int
    saved: int
    error_code: int | None
    error_message: str | None
    raw: dict | None
    started_at: datetime
    finished_at: datetime | None


class CrawlerRunsOut(BaseModel):
    items: list[CrawlerRunOut]

    @classmethod
    def of(cls, runs: list[CrawlerRunView]) -> CrawlerRunsOut:
        return cls(
            items=[
                CrawlerRunOut(
                    run_id=r.run_id,
                    target_date=r.target_date,
                    status=r.status,
                    fetched=r.fetched,
                    saved=r.saved,
                    error_code=r.error_code,
                    error_message=r.error_message,
                    raw=r.raw,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                )
                for r in runs
            ]
        )


class PipelineStageOut(BaseModel):
    stage: str
    count: int


class DocumentPipelineOut(BaseModel):
    funnel: list[PipelineStageOut]
    failures: list[PipelineStageOut]
    #: Причины, по которым вложения не взяли. Объясняют разрыв между
    #: «скачано» и «извлечён текст», который иначе выглядит поломкой.
    skip_reasons: list[PipelineStageOut]

    @classmethod
    def of(cls, funnel: PipelineFunnel) -> DocumentPipelineOut:
        return cls(
            # Список, а не объект: этапы идут по порядку конвейера, и порядок —
            # часть смысла воронки.
            funnel=[
                PipelineStageOut(stage="downloaded", count=funnel.downloaded),
                PipelineStageOut(stage="extracted", count=funnel.extracted),
                PipelineStageOut(stage="ocr", count=funnel.ocr),
                PipelineStageOut(stage="chunked", count=funnel.chunked),
                PipelineStageOut(stage="embedded", count=funnel.embedded),
            ],
            failures=[PipelineStageOut(stage=s, count=c) for s, c in funnel.failures],
            skip_reasons=[
                PipelineStageOut(stage=s, count=c) for s, c in funnel.skip_reasons
            ],
        )


class TenderEventOut(BaseModel):
    message_id: str
    event: str
    occurred_at: datetime
    status: str
    attempt: int
    retry_stage: str | None
    error: str | None


class TenderEventsOut(BaseModel):
    items: list[TenderEventOut]

    @classmethod
    def of(cls, events: list[TenderEvent]) -> TenderEventsOut:
        return cls(
            items=[
                TenderEventOut(
                    message_id=e.message_id,
                    event=e.event,
                    occurred_at=e.occurred_at,
                    status=e.status,
                    attempt=e.attempt,
                    retry_stage=e.retry_stage,
                    error=e.error,
                )
                for e in events
            ]
        )


# ─── Настройки ────────────────────────────────────────────────────────────────


class CertificateOut(BaseModel):
    subject: str
    fingerprint: str
    not_after: date | None


class SettingsOut(BaseModel):
    llm: dict[str, object]
    crawler: dict[str, object]
    embedding: dict[str, object]
    certificates: list[CertificateOut]
    eis_token: dict[str, object]
    restart_required_keys: list[str]

    @classmethod
    def of(cls, settings: EffectiveSettings) -> SettingsOut:
        return cls(
            llm={
                "base_url": settings.llm.base_url,
                "model": settings.llm.model,
                "auth_scheme": settings.llm.auth_scheme,
                "reasoning_effort": settings.llm.reasoning_effort,
                "judge_reasoning_effort": settings.llm.judge_reasoning_effort,
            },
            crawler={
                "regions": settings.crawler.regions,
                "document_types": settings.crawler.document_types,
                "interval_minutes": settings.crawler.interval_minutes,
            },
            embedding=settings.embedding,
            certificates=[
                CertificateOut(
                    subject=c.subject, fingerprint=c.fingerprint, not_after=c.not_after
                )
                for c in settings.certificates
            ],
            eis_token={
                "masked": settings.eis_token.masked,
                "rotated_at": (
                    settings.eis_token.rotated_at.isoformat()
                    if settings.eis_token.rotated_at
                    else None
                ),
            },
            restart_required_keys=settings.restart_required_keys,
        )


# ─── Профиль ──────────────────────────────────────────────────────────────────


class RatingOut(BaseModel):
    signal_id: int
    tender_id: int
    reg_num: str
    name: str | None
    signal: str
    created_at: datetime


class RatingHistoryOut(BaseModel):
    items: list[RatingOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def of(
        cls, records: list[RatingRecord], total: int, page: int, page_size: int
    ) -> RatingHistoryOut:
        return cls(
            items=[
                RatingOut(
                    signal_id=r.signal_id,
                    tender_id=r.tender_id,
                    reg_num=r.reg_num,
                    name=r.name,
                    signal=r.signal,
                    created_at=r.created_at,
                )
                for r in records
            ],
            total=total,
            page=page,
            page_size=page_size,
        )


class WinOut(BaseModel):
    tender_id: int
    reg_num: str
    name: str | None
    won_at: date | None
    contract_price: Decimal | None
    notes: str | None


class WinsOut(BaseModel):
    items: list[WinOut]
    # Считается по цене контракта, а не по НМЦК: последняя завышена почти всегда.
    total_value: Decimal

    @classmethod
    def of(cls, summary: WinsSummary) -> WinsOut:
        return cls(
            items=[
                WinOut(
                    tender_id=w.tender_id,
                    reg_num=w.reg_num,
                    name=w.name,
                    won_at=w.won_at,
                    contract_price=w.contract_price,
                    notes=w.notes,
                )
                for w in summary.items
            ],
            total_value=summary.total_value,
        )


class WeightPatchIn(BaseModel):
    facet: str = "okpd2"
    key: str = Field(min_length=1, max_length=64)
    # null — сброс к вычисленному значению, а не ноль: ноль означал бы
    # «этот код мне не нужен», и это другое утверждение.
    weight: float | None = None


class LoadLevelIn(BaseModel):
    """Заявка на смену уровня нагрузки.

    Уровень проверяется здесь, а не в сценарии: пользователь, попросивший
    седьмой уровень, должен получить отказ, а не молчаливое приведение к
    среднему. Приведение уместно при чтении настройки, где альтернатива —
    не подняться вовсе.
    """

    level: Literal[1, 2, 3]


class LoadLevelOut(BaseModel):
    """Действующий уровень и потолки, которые из него следуют.

    Потолки посчитаны по числу ядер. Поправку на память накладывает тот, кто
    разбирает: у docs-worker свой лимит, и при тесном он опустит пул ниже.
    Это справка о заявленном уровне, а не отчёт о применённом.
    """

    level: int
    extraction_workers: int
    docs_prefetch: int
    embedding_prefetch: int
    crawl_workers: int
    llm_concurrency: int
    eis_rps: float
    omp_threads: int

    @classmethod
    def of(cls, budget: LoadBudget) -> LoadLevelOut:
        return cls(
            level=int(budget.level),
            extraction_workers=budget.extraction_workers,
            docs_prefetch=budget.docs_prefetch,
            embedding_prefetch=budget.embedding_prefetch,
            crawl_workers=budget.crawl_workers,
            llm_concurrency=budget.llm_concurrency,
            eis_rps=budget.eis_rps,
            omp_threads=budget.omp_threads,
        )


# ─── Исследования ─────────────────────────────────────────────────────────────


class ResearchFunnelOut(BaseModel):
    """Воронка прогона — ветвление, а не каскад.

    `documents_pending` и `not_reached` отдаются всегда, даже нулями: это
    знаменатели. «Находок нет» читается только рядом с «прочитано столько-то»,
    а «спорных 8, решено 5» — рядом с «до трёх не дошли».
    """

    tenders_total: int
    tenders_candidate: int
    documents_scanned: int
    documents_pending: int
    hits_found: int
    reviewed: int
    rejected_by_rules: int
    confirmed_by_rules: int
    disputed: int
    from_cache: int
    asked_model: int
    not_reached: int
    failed: int

    @classmethod
    def of(cls, funnel: ResearchFunnel) -> ResearchFunnelOut:
        return cls(**{field: getattr(funnel, field) for field in cls.model_fields})


class ResearchRunOut(BaseModel):
    run_id: int
    name: str
    criteria_version: str
    status: str
    regions: list[str]
    date_from: date | None
    date_to: date | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    confirmed: int
    rejected: int
    funnel: ResearchFunnelOut

    @classmethod
    def of(cls, card: ResearchRunCard) -> ResearchRunOut:
        return cls(
            run_id=card.run_id,
            name=card.name,
            criteria_version=card.criteria_version,
            status=card.status,
            regions=card.regions,
            date_from=card.date_from,
            date_to=card.date_to,
            started_at=card.started_at,
            finished_at=card.finished_at,
            error_message=card.error_message,
            confirmed=card.confirmed,
            rejected=card.rejected,
            funnel=ResearchFunnelOut.of(card.funnel),
        )


class ResearchHitOut(BaseModel):
    """Цитата вместе с границами совпадения внутри неё.

    Границы — не украшение: без них обрезка длинной цитаты показывает один
    левый контекст, и совпадение оказывается за кадром.
    """

    term: str
    role: str
    quote: str
    match_start: int
    match_end: int
    file_name: str | None
    page: int | None

    @classmethod
    def of(cls, hit: ResearchHitView) -> ResearchHitOut:
        """Поля перечислены поимённо намеренно.

        `vars(hit)` здесь падал: доменная цитата объявлена со `slots=True` и
        `__dict__` у неё нет. Перенос по именам заодно не даёт новому полю
        домена молча просочиться наружу — контракт расширяют осознанно.
        """
        return cls(
            term=hit.term,
            role=hit.role,
            quote=hit.quote,
            match_start=hit.match_start,
            match_end=hit.match_end,
            file_name=hit.file_name,
            page=hit.page,
        )


class ResearchTenderOut(BaseModel):
    tender_id: int
    reg_num: str
    name: str | None
    price: Decimal | None
    region_code: str | None
    customer_name: str | None
    customer_inn: str | None
    okpd2_code: str | None
    confidence: str
    reason: str | None
    decided_by: str
    score: float
    hits: list[ResearchHitOut]

    @classmethod
    def of(cls, row: ResearchTenderRow) -> ResearchTenderOut:
        return cls(
            tender_id=row.tender_id,
            reg_num=row.reg_num,
            name=row.name,
            price=row.price,
            region_code=row.region_code,
            customer_name=row.customer_name,
            customer_inn=row.customer_inn,
            okpd2_code=row.okpd2_code,
            confidence=row.confidence,
            reason=row.reason,
            decided_by=row.decided_by,
            score=row.score,
            hits=[ResearchHitOut.of(hit) for hit in row.hits],
        )


class ResearchTendersOut(BaseModel):
    items: list[ResearchTenderOut]
    total: int
    page: int
    page_size: int


class MarketBucketOut(BaseModel):
    key: str
    label: str
    count: int
    total: Decimal
    average: Decimal | None


class MarketOut(BaseModel):
    """Разрезы рынка.

    `median_price` отдаётся рядом со `average_price`, а не вместо: у НМЦК
    тяжёлый правый хвост, и одно среднее описывает рынок, которого нет.
    `top_share` показывает этот хвост числом.
    """

    total_count: int
    priced_count: int
    total_value: Decimal
    median_price: Decimal | None
    average_price: Decimal | None
    top_share: float
    by_region: list[MarketBucketOut]
    by_customer: list[MarketBucketOut]
    by_okpd2: list[MarketBucketOut]

    @classmethod
    def of(cls, view: MarketView) -> MarketOut:
        bucket = lambda b: MarketBucketOut(  # noqa: E731
            key=b.key, label=b.label, count=b.count, total=b.total, average=b.average
        )
        return cls(
            total_count=view.total_count,
            priced_count=view.priced_count,
            total_value=view.total_value,
            median_price=view.median_price,
            average_price=view.average_price,
            top_share=view.top_share,
            by_region=[bucket(b) for b in view.by_region],
            by_customer=[bucket(b) for b in view.by_customer],
            by_okpd2=[bucket(b) for b in view.by_okpd2],
        )


# ─── Вкладка «Данные» ─────────────────────────────────────────────────────────


class DayBucketOut(BaseModel):
    """День на гистограмме публикаций.

    `crawled` отличает «в этот день ничего не публиковали» от «этот день мы не
    выгружали». Без этого различия дыра в покрытии читалась бы как факт о
    рынке.
    """

    day: date
    count: int
    crawled: bool


class SliceOut(BaseModel):
    key: str
    label: str
    count: int


class DistributionOut(BaseModel):
    """Верхушка разреза плюс хвост.

    `others` и `unknown` обязательны: сумма показанного, хвоста и «без
    признака» равна `total`. Без них двенадцать столбиков читаются как весь
    корпус.
    """

    top: list[SliceOut]
    others: int
    unknown: int
    total: int

    @classmethod
    def of(cls, distribution: Distribution) -> DistributionOut:
        return cls(
            top=[SliceOut(key=s.key, label=s.label, count=s.count) for s in distribution.top],
            others=distribution.others,
            unknown=distribution.unknown,
            total=distribution.total,
        )


class CorpusOverviewOut(BaseModel):
    """Состав корпуса за период. Период один на все разрезы — см. use case."""

    since: date
    until: date
    total: int
    total_all_time: int
    earliest: date | None
    latest: date | None
    by_day: list[DayBucketOut]
    by_region: DistributionOut
    by_okpd2: DistributionOut

    @classmethod
    def of(cls, view: CorpusOverview) -> CorpusOverviewOut:
        return cls(
            since=view.since,
            until=view.until,
            total=view.total,
            total_all_time=view.total_all_time,
            earliest=view.earliest,
            latest=view.latest,
            by_day=[
                DayBucketOut(day=d.day, count=d.count, crawled=d.crawled) for d in view.by_day
            ],
            by_region=DistributionOut.of(view.by_region),
            by_okpd2=DistributionOut.of(view.by_okpd2),
        )


class EmbeddingProgressOut(BaseModel):
    chunks_total: int
    chunks_embedded: int
    tenders_total: int
    tenders_embedded: int
    #: `null` — брокер не ответил. Это факт о брокере, а не ноль работы.
    queue_depth: int | None


class TodayIngestOut(BaseModel):
    """Ход сегодняшней выгрузки.

    `final` всегда `false`: суточный архив ЕИС дописывается до полуночи, и
    сегодняшний день не считается закрытым никогда. Поле есть, чтобы клиент не
    выводил это правило сам и не ошибся.
    """

    day: date
    runs_succeeded: int
    runs_failed: int
    runs_running: int
    saved: int
    published_today: int
    last_run_at: datetime | None
    final: bool = False


class CorpusProcessingOut(BaseModel):
    embeddings: EmbeddingProgressOut
    today: TodayIngestOut
    documents_downloaded: int
    documents_extracted: int

    @classmethod
    def of(cls, view: CorpusProcessing) -> CorpusProcessingOut:
        return cls(
            embeddings=EmbeddingProgressOut(
                chunks_total=view.embeddings.chunks_total,
                chunks_embedded=view.embeddings.chunks_embedded,
                tenders_total=view.embeddings.tenders_total,
                tenders_embedded=view.embeddings.tenders_embedded,
                queue_depth=view.embeddings.queue_depth,
            ),
            today=TodayIngestOut(
                day=view.today.day,
                runs_succeeded=view.today.runs_succeeded,
                runs_failed=view.today.runs_failed,
                runs_running=view.today.runs_running,
                saved=view.today.saved,
                published_today=view.today.published_today,
                last_run_at=view.today.last_run_at,
            ),
            documents_downloaded=view.documents_downloaded,
            documents_extracted=view.documents_extracted,
        )

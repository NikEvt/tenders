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
from services.api.domain.documents import ChunkOutline, FragmentPage
from services.api.domain.filters import SavedFilterCard
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


class RunFilterIn(BaseModel):
    since: date | None = None
    tender_ids: list[int] = Field(default_factory=list)


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

    Потолки посчитаны для машины шлюза: у воркера с другим лимитом памяти
    размер пула может отличаться, поэтому это справка, а не гарантия.
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

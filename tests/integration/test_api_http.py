"""Снимок HTTP-контракта шлюза: статусы и форма ответа каждого маршрута.

Порты подменены заглушками, поэтому тест не требует ни Postgres, ни MinIO, ни
соседних сервисов — он проверяет ровно то, что отдаёт presentation-слой.

Смысл файла — сеть безопасности под рефакторинг: пока хендлеры переезжают в
роутеры, а репозиторий разрезается на части, снаружи не должно меняться ничего.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
import pytest_asyncio

from libs.shared import load_policy
from libs.shared.load_policy import detect_cpu_count
from services.api.application.ports import DownstreamUnavailable
from services.api.domain.catalog import (
    FacetBucket,
    Facets,
    PriceBucket,
    RestrictiveHint,
    SimilarTender,
)
from services.api.domain.corpus import (
    CorpusOverview,
    DayBucket,
    Distribution,
    EmbeddingProgress,
    Slice,
    TodayIngest,
)
from services.api.domain.documents import (
    ChunkOutline,
    Fragment,
    FragmentPage,
    FragmentScores,
    TextLocation,
)
from services.api.domain.filters import MatchCount, SavedFilterCard
from services.api.domain.jobs import JobView
from services.api.domain.models import (
    Page,
    TenderDetail,
    TenderDocumentInfo,
    TenderFilter,
    TenderSummary,
)
from services.api.domain.monitoring import (
    CrawlerRunView,
    DeadLetter,
    PipelineFunnel,
    QueuesSnapshot,
    QueueStat,
    RetryStage,
    ServiceHealth,
    TenderEvent,
)
from services.api.domain.pagination import PageRequest
from services.api.domain.profile import RatingRecord, WinRecord, WinsSummary
from services.api.domain.research import (
    MarketBucket,
    MarketView,
    ResearchFunnel,
    ResearchHitView,
    ResearchRunCard,
    ResearchTenderRow,
)
from services.api.domain.settings import (
    CertificateInfo,
    CrawlerSettingsView,
    EffectiveSettings,
    LlmSettingsView,
    TokenState,
)
from services.api.presentation.app import create_app

REG_NUM = "0173100007724000123"
MISSING = "НЕТ-ТАКОГО"
DOCUMENT_ID = 42
MISSING_DOCUMENT_ID = 999
JOB_ID = "6f1b1e9c-0000-4000-8000-000000000000"
DIGEST_DATE = "2026-08-07"
RESEARCH_RUN_ID = 7
MISSING_DIGEST_DATE = "2000-01-01"


def _summary() -> TenderSummary:
    return TenderSummary(
        tender_id=1,
        reg_num=REG_NUM,
        name="Поставка офисной мебели",
        description="Столы и стулья",
        price=Decimal("400000.00"),
        currency="RUB",
        customer_name="Администрация",
        customer_inn="5000000001",
        okpd2_code="31.01.11",
        okpd2_name="Мебель для офисов",
        region_code="50",
        publish_date=datetime(2026, 8, 6, 9, 0),
        start_date=datetime(2026, 8, 6, 9, 0),
        end_date=datetime(2026, 8, 20, 9, 0),
        prev_end_date=datetime(2026, 8, 15, 9, 0),
        status="active",
        documents_status="done",
        document_count=1,
    )


class FakeCatalog:
    def __init__(self) -> None:
        self.seen: Any | None = None

    async def list(self, filters: Any, page: PageRequest) -> Page:
        self.seen = filters
        return Page(
            items=[_summary()],
            total=1,
            page=page.page,
            page_size=page.limit,
            next_cursor="cursor-2" if page.cursor is None else None,
        )

    async def tender_id(self, reg_num: str) -> int | None:
        return 1 if reg_num == REG_NUM else None

    async def get(self, reg_num: str) -> TenderDetail | None:
        if reg_num != REG_NUM:
            return None
        return TenderDetail(
            summary=_summary(),
            documents=[
                TenderDocumentInfo(
                    document_id=DOCUMENT_ID,
                    file_name="ТЗ.pdf",
                    doc_kind_name="Техническое задание",
                    file_size=1024,
                    extraction_status="done",
                    page_count=4,
                    ocr_used=True,
                    char_count=52,
                    has_text=True,
                )
            ],
            verdicts=[{"filter_id": 1, "match": True, "score": 0.9}],
        )


class FakeSearch:
    #: Что вернёт `matching_ids` — им должны ограничиться фасеты.
    IDS: ClassVar[list[int]] = [11, 22, 33]

    def __init__(self) -> None:
        self.seen: Any | None = None

    async def matching_ids(self, query: str, filters: Any) -> list[int]:
        return list(self.IDS)

    async def search(self, query: str, filters: Any, page: PageRequest) -> Page:
        self.seen = filters
        summary = _summary()
        summary.relevance = 0.5
        return Page(items=[summary], total=1, page=page.page, page_size=page.limit)


class FakeFacets:
    def __init__(self) -> None:
        self.seen: TenderFilter | None = None
        self.restricted_to: list[int] | None = None

    async def facets(self, filters: TenderFilter, restrict_to=None) -> Facets:
        self.seen = filters
        self.restricted_to = list(restrict_to) if restrict_to is not None else None
        return Facets(
            total=42,
            regions=[FacetBucket(key="50", label="Московская область", count=30)],
            okpd2=[FacetBucket(key="31.01.11", label="Мебель для офисов", count=12)],
            customers=[FacetBucket(key="5000000001", label="Администрация", count=7)],
            price_histogram=[
                PriceBucket(price_from=Decimal("0"), price_to=Decimal("500000"), count=42)
            ],
        )

    async def restrictive(self, filters: TenderFilter, restrict_to=None) -> RestrictiveHint | None:
        return RestrictiveHint(param="region", kept=240, dropped=198)


class FakeSimilarity:
    async def similar(self, tender_id: int, limit: int) -> list[SimilarTender]:
        return [
            SimilarTender(
                tender=_summary(), similarity=0.87, driver="совпадает ОКПД2 и тот же регион"
            )
        ]


class FakeDocuments:
    async def exists(self, document_id: int) -> bool:
        return document_id == DOCUMENT_ID

    async def chunks(self, document_id: int) -> list[ChunkOutline]:
        return [
            ChunkOutline(chunk_id=7, ordinal=0, char_start=0, char_end=51, page=2),
            # Чанк, нарезанный до появления смещений: подсвечивать нечем.
            ChunkOutline(chunk_id=8, ordinal=1, char_start=None, char_end=None, page=3),
        ]

    async def source(self, document_id: int) -> tuple[str, str | None] | None:
        if document_id != DOCUMENT_ID:
            return None
        return "https://zakupki.gov.ru/file/ТЗ.pdf", "ТЗ.pdf"

    async def text_location(self, document_id: int) -> TextLocation | None:
        if document_id != DOCUMENT_ID:
            return None
        # Неперенесённый документ: текст ещё лежит в базе, а не в хранилище.
        return TextLocation(inline="Мебель должна выдерживать обработку хлоргексидином.")


class FakeDigests:
    async def dates(self, since: date, until: date) -> list[date]:
        return [date.fromisoformat(DIGEST_DATE)]

    async def get(self, digest_date: date) -> dict | None:
        if digest_date.isoformat() != DIGEST_DATE:
            return None
        return {
            "digest_date": DIGEST_DATE,
            "summary_md": "# Сводка",
            "sections": {},
            "tender_count": 3,
            "model": "test",
            "generated_at": "2026-08-08T07:00:00+00:00",
        }


class FakeJobs:
    """Задание в середине второй фазы: обход корпуса позади, судья работает."""

    def __init__(self, total: int | None = 10, phase: str | None = "судья читает документы"):
        self.total = total
        self.phase = phase

    async def get(self, job_id: str) -> JobView | None:
        if job_id != JOB_ID:
            return None
        return JobView(
            job_id=JOB_ID,
            kind="research",
            status="running",
            phase=self.phase,
            total=self.total,
            processed=4,
            result=None,
            error=None,
            created_at=datetime(2026, 8, 8, 7, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 8, 7, 1, tzinfo=UTC),
        )


class FakeFragments:
    def __init__(self) -> None:
        self.mode: str | None = None

    async def search(self, query: str, mode: str, page: int, page_size: int) -> FragmentPage:
        self.mode = mode
        return FragmentPage(
            items=[
                Fragment(
                    chunk_id=7,
                    document_id=DOCUMENT_ID,
                    tender_id=1,
                    reg_num=REG_NUM,
                    tender_name="Поставка офисной мебели",
                    tender_price=Decimal("400000.00"),
                    document_name="ТЗ.pdf",
                    text="Мебель должна выдерживать обработку хлоргексидином.",
                    char_start=0,
                    char_end=51,
                    scores=FragmentScores(lexical=0.42, vector=0.81, rrf=0.031),
                    highlights=[(0, 6)],
                )
            ],
            total=1,
            page=page,
            page_size=page_size,
        )


class FakeFilters:
    async def list(self, history_days: int) -> list[SavedFilterCard]:
        return [_filter_card()]

    async def get(self, filter_id: int, history_days: int) -> SavedFilterCard | None:
        return _filter_card() if filter_id == 1 else None


def _filter_card() -> SavedFilterCard:
    return SavedFilterCard(
        filter_id=1,
        name="Мебель",
        query="поставка офисной мебели",
        spec={"name": "Мебель", "terms": [{"name": "мебель", "pattern": r"мебел\w*"}]},
        in_digest=True,
        notify=False,
        is_active=True,
        created_at=datetime(2026, 8, 1, 9, 0),
        last_run_at=datetime(2026, 8, 8, 7, 0),
        match_counts=[MatchCount(day=date(2026, 8, 7), count=3)],
    )


class FakeProbe:
    async def probe_all(self) -> list[ServiceHealth]:
        return [
            ServiceHealth(name="api", status="ok", port=8000, p95_ms=3.1, facts={}),
            ServiceHealth(
                name="embedding-service",
                status="ok",
                port=8020,
                p95_ms=12.0,
                facts={"device": "cpu", "dim": 1024},
            ),
            # Упавший сосед — это факт о нём, а не ошибка страницы.
            ServiceHealth(name="llm-service", status="down", port=8010),
        ]


class FakeQueues:
    def __init__(self) -> None:
        self.requeued: str | None = None

    async def snapshot(self) -> QueuesSnapshot:
        return QueuesSnapshot(
            queues=[
                QueueStat(name="docs-worker.tender-ingested", depth=4, consumers=1, dead_letters=2)
            ],
            retry_ladder=[RetryStage(stage="5с", depth=1), RetryStage(stage="30с", depth=0)],
            dead_letters=[
                DeadLetter(
                    message_id="m-1",
                    event="tender.ingested",
                    error="таймаут",
                    retry_stage="1ч",
                    failed_at=datetime(2026, 8, 9, 6, 0),
                )
            ],
        )

    async def requeue_dead_letter(self, message_id: str) -> bool:
        self.requeued = message_id
        return message_id == "m-1"


class FakeCrawlerRuns:
    async def recent(self, limit: int) -> list[CrawlerRunView]:
        return [
            CrawlerRunView(
                run_id=1,
                target_date="2026-08-08",
                status="failed",
                fetched=0,
                saved=0,
                error_code=34,
                error_message="Организация заблокирована",
                raw={"errorInfo": {"code": 34}},
                started_at=datetime(2026, 8, 8, 20, 59),
                finished_at=datetime(2026, 8, 8, 20, 59, 56),
            )
        ]


class FakePipeline:
    async def funnel(self) -> PipelineFunnel:
        return PipelineFunnel(
            downloaded=100,
            extracted=80,
            ocr=12,
            chunked=78,
            embedded=70,
            failures=[("failed", 15), ("deferred", 40)],
            skip_reasons=[("tender_budget", 30), ("multivolume", 10)],
        )


class FakeCorpus:
    """Корпус из двух дней: один выгружен, второй — дыра в покрытии."""

    async def overview(self, since, until, limit) -> CorpusOverview:
        return CorpusOverview(
            since=since,
            until=until,
            total=30,
            total_all_time=900,
            earliest=date(2026, 1, 1),
            latest=until,
            by_day=[
                DayBucket(day=since, count=0, crawled=False),
                DayBucket(day=until, count=30, crawled=True),
            ],
            by_region=Distribution(
                top=[Slice(key="77", label="Москва", count=18)],
                others=7,
                total=30,
                unknown=5,
            ),
            by_okpd2=Distribution(
                top=[Slice(key="26.20.11", label="Компьютеры", count=12)],
                others=10,
                total=30,
                unknown=8,
            ),
        )

    async def embeddings(self) -> EmbeddingProgress:
        return EmbeddingProgress(
            chunks_total=2000,
            chunks_embedded=500,
            tenders_total=900,
            tenders_embedded=300,
        )

    async def today(self, day) -> TodayIngest:
        return TodayIngest(
            day=day,
            runs_succeeded=42,
            runs_failed=1,
            runs_running=2,
            saved=310,
            published_today=298,
            last_run_at=datetime(2026, 8, 15, 9, 30),
        )


class FakeEvents:
    async def for_tender(self, tender_id: int) -> list[TenderEvent]:
        return [
            TenderEvent(
                message_id="e-1",
                event="tender.ingested",
                occurred_at=datetime(2026, 8, 8, 21, 0),
                status="consumed",
                attempt=0,
                retry_stage=None,
                error=None,
            ),
            TenderEvent(
                message_id="e-2",
                event="embedding.requested",
                occurred_at=datetime(2026, 8, 8, 21, 1),
                status="retry",
                attempt=2,
                retry_stage="30с",
                error="эмбеддер недоступен",
            ),
        ]


class FakeAppState:
    def __init__(self) -> None:
        self.stored: dict[str, dict] = {}

    async def get(self, key: str) -> dict | None:
        return self.stored.get(key)

    async def set(self, key: str, value: dict) -> None:
        self.stored[key] = value


class FakeRuntimeSettings:
    def effective(self) -> EffectiveSettings:
        return EffectiveSettings(
            llm=LlmSettingsView(
                base_url="http://llm:8080/v1",
                model="qwen3.6",
                auth_scheme="Bearer",
                reasoning_effort="none",
                judge_reasoning_effort="low",
            ),
            crawler=CrawlerSettingsView(
                regions=["77"], document_types=["epNotificationEF2020"], interval_minutes=60
            ),
            embedding={"model": "bge-m3", "dim": 1024, "device": "cpu"},
            certificates=[
                CertificateInfo(
                    subject="Russian Trusted Root CA",
                    fingerprint="root",
                    not_after=date(2032, 2, 27),
                )
            ],
            eis_token=TokenState(masked="••••••••cd12", rotated_at=None),
            restart_required_keys=["EIS_TOKEN"],
        )


class FakeProfileHistory:
    async def ratings(self, page: int, page_size: int):
        return [
            RatingRecord(
                signal_id=5,
                tender_id=1,
                reg_num=REG_NUM,
                name="Поставка офисной мебели",
                signal="like",
                created_at=datetime(2026, 8, 7, 12, 0),
            )
        ], 1

    async def wins(self) -> WinsSummary:
        return WinsSummary(
            items=[
                WinRecord(
                    tender_id=1,
                    reg_num=REG_NUM,
                    name="Поставка офисной мебели",
                    won_at=date(2026, 7, 1),
                    contract_price=Decimal("390000.00"),
                    notes=None,
                )
            ],
            total_value=Decimal("390000.00"),
        )


class FakeReadiness:
    async def check(self) -> None:
        return None


class FakeStorage:
    def presigned_url(self, key: str, expires: int) -> str:
        return f"http://minio.test/{key}?expires={expires}"


class FakeLlm:
    """Отдаёт успех; тест недоступности подменяет отдельные методы."""

    async def compile_filter(self, query: str) -> dict:
        return {"spec": {"keywords": ["мебель"]}}

    def __init__(self) -> None:
        self.saved_spec: dict | None = None
        self.patched: dict | None = None
        self.deleted: int | None = None

    async def save_filter(self, name: str, query: str, spec: dict | None = None) -> dict:
        self.saved_spec = spec
        return {"filter_id": 1, "spec": spec or {"keywords": ["мебель"]}}

    async def patch_filter(self, filter_id: int, patch: dict) -> dict:
        self.patched = patch
        return {"filter_id": filter_id, **patch}

    async def delete_filter(self, filter_id: int) -> None:
        self.deleted = filter_id

    async def duplicate_filter(self, filter_id: int) -> dict:
        return {"filter_id": 99, "name": "Мебель (копия)"}

    async def test_filter(self, filter_id: int, days: int) -> dict:
        return {"job_id": JOB_ID, "days": days}

    async def run_filter(
        self,
        filter_id: int,
        since: date | None,
        until: date | None,
        regions: list[str],
    ) -> dict:
        self.run_seen = {"since": since, "until": until, "regions": regions}
        return {"job_id": JOB_ID}

    async def request_digest(self, digest_date: date, force: bool) -> dict:
        return {"job_id": JOB_ID}


class FakeCrawl:
    def __init__(self) -> None:
        self.requested: list[dict] = []

    async def request(self, job_id, regions, date_from, date_to) -> None:
        self.requested.append(
            {
                "job_id": str(job_id),
                "regions": list(regions),
                "since": date_from,
                "until": date_to,
            }
        )


class FakeRecsys:
    async def recommendations(self, limit: int) -> list[dict]:
        return [{"tender_id": 1, "score": 0.8, "explanation": {}}]

    async def feedback(self, tender_id: int, signal: str, reason: str | None) -> dict:
        return {"status": "accepted"}

    async def view(self, tender_id: int, dwell_ms: int | None) -> dict:
        return {"status": "accepted"}

    async def win(self, tender_id: int, payload: dict) -> dict:
        return {"status": "accepted"}

    async def profile(self) -> dict:
        return {"signal_count": 12, "has_embedding": True, "is_usable": False}

    async def profile_weights(self) -> list[dict]:
        return [
            {
                "facet": "okpd2",
                "key": "32.50",
                "label": "32.50",
                "weight": 0.8,
                "source": "manual",
            }
        ]

    async def set_profile_weight(self, facet: str, key: str, weight: float | None) -> list[dict]:
        return []

    async def ranker(self) -> dict:
        return {"kind": "linear", "signals": 12, "threshold": 500}

    async def delete_rating(self, signal_id: int) -> None:
        return None


class FakeResearch:
    """Отдаёт **доменные** объекты, а не SimpleNamespace.

    Разница не косметическая: доменные модели объявлены со `slots=True`, у них
    нет `__dict__`, и перенос полей через `vars()` на них падает. Заглушка с
    `__dict__` этого бы не показала — маршрут `/research/runs/{id}/tenders`
    отдавал 500 на живой базе, пока все тесты были зелёными.
    """

    async def runs(self, limit: int) -> list[ResearchRunCard]:
        return [self._card()]

    async def run(self, run_id: int) -> ResearchRunCard | None:
        return self._card() if run_id == RESEARCH_RUN_ID else None

    async def tenders(
        self, run_id: int, confidence: str | None, limit: int, offset: int
    ) -> tuple[list[ResearchTenderRow], int]:
        if run_id != RESEARCH_RUN_ID:
            return [], 0
        return [self._row()], 1

    async def market(self, run_id: int) -> MarketView:
        if run_id != RESEARCH_RUN_ID:
            return MarketView()
        return MarketView(
            total_count=2,
            priced_count=2,
            total_value=Decimal("900000.00"),
            median_price=Decimal("450000.00"),
            average_price=Decimal("450000.00"),
            top_share=0.55,
            by_region=[
                MarketBucket(
                    key="50",
                    label="Московская область",
                    count=2,
                    total=Decimal("900000.00"),
                    average=Decimal("450000.00"),
                )
            ],
        )

    @staticmethod
    def _card() -> ResearchRunCard:
        return ResearchRunCard(
            run_id=RESEARCH_RUN_ID,
            name="ХПК и БПК, август",
            criteria_version="hpk-v3",
            status="done",
            regions=["50"],
            funnel=ResearchFunnel(
                tenders_total=600,
                tenders_candidate=76,
                documents_scanned=300,
                documents_pending=12,
                hits_found=333,
                confirmed_by_rules=56,
                rejected_by_rules=20,
                disputed=8,
            ),
            confirmed=56,
            rejected=20,
        )

    @staticmethod
    def _row() -> ResearchTenderRow:
        return ResearchTenderRow(
            tender_id=1,
            reg_num=REG_NUM,
            name="Поставка мебели",
            price=Decimal("450000.00"),
            region_code="50",
            customer_name="Администрация",
            customer_inn="5000000001",
            okpd2_code="31.01.11",
            confidence="confirmed",
            reason="прямое указание в ТЗ",
            decided_by="rules",
            score=0.91,
            hits=[
                ResearchHitView(
                    term="хлоргексидин",
                    role="confirm",
                    quote="Мебель должна выдерживать обработку хлоргексидином.",
                    match_start=36,
                    match_end=50,
                    file_name="ТЗ.pdf",
                    page=2,
                )
            ],
        )


@pytest.fixture
def container() -> SimpleNamespace:
    return SimpleNamespace(
        research=FakeResearch(),
        catalog=FakeCatalog(),
        search=FakeSearch(),
        facets=FakeFacets(),
        similarity=FakeSimilarity(),
        documents=FakeDocuments(),
        digest=FakeDigests(),
        jobs=FakeJobs(),
        filters=FakeFilters(),
        fragments=FakeFragments(),
        probe=FakeProbe(),
        queues=FakeQueues(),
        crawler_runs=FakeCrawlerRuns(),
        pipeline=FakePipeline(),
        corpus=FakeCorpus(),
        events=FakeEvents(),
        app_state=FakeAppState(),
        runtime_settings=FakeRuntimeSettings(),
        profile_history=FakeProfileHistory(),
        readiness=FakeReadiness(),
        storage=FakeStorage(),
        crawl=FakeCrawl(),
        llm=FakeLlm(),
        recsys=FakeRecsys(),
    )


@pytest_asyncio.fixture
async def client(container) -> AsyncIterator[httpx.AsyncClient]:
    """Приложение без lifespan: порты подставляются напрямую в состояние."""
    app = create_app()
    app.state.ports = container
    # raise_app_exceptions=False: Starlette отдаёт клиенту 500 и всё равно
    # пробрасывает исключение наверх, чтобы его залогировал сервер. Нам нужен
    # именно клиентский взгляд — то, что увидит браузер.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        yield client


# ─── Каталог ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tenders_returns_page_envelope(client) -> None:
    response = await client.get("/tenders", params={"page": 0, "page_size": 20})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size", "total_pages", "next_cursor"}
    assert body["items"][0]["reg_num"] == REG_NUM
    # deadline_changed вычисляется из prev_end_date, а не приходит из БД.
    assert body["items"][0]["deadline_changed"] is True


@pytest.mark.asyncio
async def test_list_tenders_rejects_oversized_page(client) -> None:
    assert (await client.get("/tenders", params={"page_size": 10_000})).status_code == 422


@pytest.mark.asyncio
async def test_search_requires_query_of_two_characters(client) -> None:
    assert (await client.get("/tenders/search", params={"q": "а"})).status_code == 422

    response = await client.get("/tenders/search", params={"q": "мебель"})
    assert response.status_code == 200
    assert response.json()["items"][0]["relevance"] is not None


@pytest.mark.asyncio
async def test_search_carries_the_saved_filter(client, container) -> None:
    """Раньше роут подставлял `filter_id=None`, и фильтр молча переставал действовать."""
    response = await client.get(
        "/tenders/search", params={"q": "мебель", "filter_id": 7}
    )

    assert response.status_code == 200
    assert container.search.seen.filter_id == 7


@pytest.mark.asyncio
async def test_catalog_defaults_to_matched_only(client, container) -> None:
    await client.get("/tenders", params={"filter_id": 7})
    assert container.catalog.seen.filter_verdicts == ("confirmed",)


@pytest.mark.asyncio
async def test_catalog_can_ask_for_rejected(client, container) -> None:
    await client.get(
        "/tenders", params={"filter_id": 7, "filter_verdict": ["rejected", "disputed"]}
    )
    assert container.catalog.seen.filter_verdicts == ("rejected", "disputed")


@pytest.mark.asyncio
async def test_unknown_verdict_is_refused(client) -> None:
    response = await client.get(
        "/tenders", params={"filter_id": 7, "filter_verdict": "почти"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_tender_detail_and_missing(client) -> None:
    response = await client.get(f"/tenders/{REG_NUM}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"tender", "documents", "verdicts"}
    assert body["documents"][0]["has_text"] is True

    assert (await client.get(f"/tenders/{MISSING}")).status_code == 404


# ─── Документы ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_document_download_link(client) -> None:
    response = await client.get(f"/documents/{DOCUMENT_ID}/download")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"url", "file_name", "expires_in"}
    # Копии файла у системы нет — ссылка ведёт в ЕИС и не протухает.
    assert body["url"].startswith("https://zakupki.gov.ru/")
    assert body["expires_in"] == 0

    assert (await client.get(f"/documents/{MISSING_DOCUMENT_ID}/download")).status_code == 404


@pytest.mark.asyncio
async def test_document_text(client) -> None:
    response = await client.get(f"/documents/{DOCUMENT_ID}/text")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"document_id", "content", "char_count"}
    assert body["char_count"] == len(body["content"])

    assert (await client.get(f"/documents/{MISSING_DOCUMENT_ID}/text")).status_code == 404


# ─── Фильтры ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compile_filter(client) -> None:
    response = await client.post("/filters/compile", json={"query": "поставка мебели"})
    assert response.status_code == 200
    assert "spec" in response.json()

    # Слишком короткий запрос отсекается схемой, а не сервисом.
    assert (await client.post("/filters/compile", json={"query": "ме"})).status_code == 422


@pytest.mark.asyncio
async def test_save_and_run_filter(client) -> None:
    saved = await client.post("/filters", json={"name": "Мебель", "query": "поставка мебели"})
    assert saved.status_code == 201
    assert saved.json()["filter_id"] == 1

    run = await client.post("/filters/1/run", json={"since": None})
    assert run.status_code == 202
    assert run.json()["job_id"] == JOB_ID


@pytest.mark.asyncio
async def test_run_carries_regions_and_period(client, container) -> None:
    """Охват выбирают в форме — он обязан доехать до движка целиком."""
    response = await client.post(
        "/filters/1/run",
        json={"since": "2026-07-01", "until": "2026-07-31", "regions": ["77", "78"]},
    )

    assert response.status_code == 202
    assert container.llm.run_seen == {
        "since": date(2026, 7, 1),
        "until": date(2026, 7, 31),
        "regions": ["77", "78"],
    }


@pytest.mark.asyncio
async def test_downstream_failure_becomes_503(client, container) -> None:
    """Недоступность соседа — это 503, а не 500: клиент повторит запрос."""

    async def unavailable(query: str) -> dict:
        raise DownstreamUnavailable("llm-service недоступен")

    container.llm.compile_filter = unavailable

    response = await client.post("/filters/compile", json={"query": "поставка мебели"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_job_status(client) -> None:
    response = await client.get(f"/jobs/{JOB_ID}")
    assert response.status_code == 200
    assert response.json()["status"] == "running"

    assert (await client.get("/jobs/нет-такого")).status_code == 404


@pytest.mark.asyncio
async def test_job_names_its_phase_and_start(client) -> None:
    """По этому ответу рисуется шкала: нужны фаза, счётчик и время старта.

    Фаза — потому что операция состоит из этапов с разной ценой единицы работы;
    время старта — потому что без него «идёт столько-то» и оценка остатка
    считаются не из чего.
    """
    body = (await client.get(f"/jobs/{JOB_ID}")).json()

    assert body["phase"] == "судья читает документы"
    assert body["total"] == 10
    assert body["processed"] == 4
    assert body["created_at"].startswith("2026-08-08T07:00")


@pytest.mark.asyncio
async def test_job_is_typed_in_the_schema(client) -> None:
    """Клиент обязан брать тип задания из схемы, а не переписывать руками."""
    schema = (await client.get("/openapi.json")).json()
    job = schema["paths"]["/jobs/{job_id}"]["get"]["responses"]["200"]
    ref = job["content"]["application/json"]["schema"]["$ref"]

    assert ref.endswith("/JobOut")
    properties = schema["components"]["schemas"]["JobOut"]["properties"]
    assert {"phase", "total", "processed", "created_at"} <= set(properties)


# ─── Сводка ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_digest_read_and_request(client) -> None:
    response = await client.get(f"/digest/{DIGEST_DATE}")
    assert response.status_code == 200
    assert response.json()["summary_md"].startswith("#")

    assert (await client.get(f"/digest/{MISSING_DIGEST_DATE}")).status_code == 404

    requested = await client.post(f"/digest/{DIGEST_DATE}", params={"force": True})
    assert requested.status_code == 202


# ─── Рекомендации ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommendations_and_signals(client) -> None:
    assert (await client.get("/recommendations", params={"limit": 5})).status_code == 200

    feedback = await client.post(
        "/feedback", json={"tender_id": 1, "signal": "like", "reason": None}
    )
    assert feedback.status_code == 202

    # Сигнал вне перечня отсекается схемой.
    bad = await client.post("/feedback", json={"tender_id": 1, "signal": "маybe"})
    assert bad.status_code == 422

    assert (await client.post("/views", json={"tender_id": 1, "dwell_ms": 900})).status_code == 202
    assert (
        await client.post("/wins", json={"tender_id": 1, "contract_price": "390000.00"})
    ).status_code == 202
    assert (await client.get("/profile")).status_code == 200


# ─── Служебное ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoints(client) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/health/ready")).json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_unready_container_returns_503() -> None:
    """До завершения lifespan шлюз обязан отвечать 503, а не падать."""
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        assert (await client.get("/tenders")).status_code == 503


@pytest.mark.asyncio
async def test_every_response_carries_request_id(client) -> None:
    ok = await client.get("/health")
    assert ok.headers["x-request-id"]

    # Свой идентификатор клиента не перетирается — иначе след рвётся на границе.
    mine = "cafe-1234"
    echoed = await client.get("/health", headers={"X-Request-Id": mine})
    assert echoed.headers["x-request-id"] == mine


@pytest.mark.asyncio
async def test_error_body_keeps_detail_and_adds_code(client) -> None:
    """`detail` читает web-клиент, поэтому форма не меняется; `code` — сверху."""
    response = await client.get(f"/tenders/{MISSING}")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"] == f"Закупка {MISSING} не найдена"
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_unexpected_exception_becomes_500_not_a_crash(client, container) -> None:
    async def boom(filters, page, page_size):
        raise ValueError("репозиторий сломался")

    container.catalog.list = boom

    response = await client.get("/tenders")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    # Текст исключения наружу не течёт.
    assert "репозиторий сломался" not in response.text


@pytest.mark.asyncio
async def test_crawl_defaults_to_yesterday_and_today(client, container) -> None:
    """ЕИС публикует с задержкой: вчерашний архив к утру ещё дописывается."""
    response = await client.post("/crawl", json={})

    assert response.status_code == 202
    assert response.json()["job_id"]
    asked = container.crawl.requested[0]
    assert asked["until"] == date.today()
    assert asked["since"] == date.today() - timedelta(days=1)
    assert asked["regions"] == []


@pytest.mark.asyncio
async def test_crawl_carries_the_chosen_scope(client, container) -> None:
    response = await client.post(
        "/crawl",
        json={"since": "2026-07-01", "until": "2026-07-05", "regions": ["77", "078"]},
    )

    assert response.status_code == 202
    asked = container.crawl.requested[0]
    assert asked["since"] == date(2026, 7, 1)
    assert asked["until"] == date(2026, 7, 5)
    # Код приводится к двузначному виду: ЕИС шлёт то `77`, то `077`.
    assert asked["regions"] == ["77", "78"]


@pytest.mark.asyncio
async def test_crawl_refuses_a_reversed_period(client, container) -> None:
    response = await client.post(
        "/crawl", json={"since": "2026-07-05", "until": "2026-07-01"}
    )

    assert response.status_code == 422
    assert container.crawl.requested == []


@pytest.mark.asyncio
async def test_crawl_refuses_a_year(client, container) -> None:
    """Заявка на год из интерфейса — способ случайно устроить себе бан."""
    response = await client.post(
        "/crawl", json={"since": "2026-01-01", "until": "2026-12-31"}
    )

    assert response.status_code == 422
    assert container.crawl.requested == []


@pytest.mark.asyncio
async def test_crawl_refuses_an_unknown_region(client, container) -> None:
    """Опечатка в коде дала бы выгрузку, которая молча ничего не привезёт."""
    response = await client.post("/crawl", json={"regions": ["77", "99"]})

    assert response.status_code == 422
    assert "99" in response.json()["detail"]
    assert container.crawl.requested == []


# ─── Вкладка «Данные» ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_data_overview_carries_its_denominators(client) -> None:
    """Разрез без хвоста и итога читается как весь корпус."""
    body = (await client.get("/data/overview")).json()

    for section in ("by_region", "by_okpd2"):
        cut = body[section]
        shown = sum(item["count"] for item in cut["top"])
        assert shown + cut["others"] + cut["unknown"] == cut["total"]

    # Сколько корпуса вообще видно на экране — отдельным числом.
    assert body["total_all_time"] >= body["total"]


@pytest.mark.asyncio
async def test_data_overview_marks_days_without_a_crawl(client) -> None:
    """День без выгрузки обязан быть отличим от дня без закупок."""
    body = (await client.get("/data/overview")).json()

    assert {day["crawled"] for day in body["by_day"]} == {True, False}


@pytest.mark.asyncio
async def test_data_overview_rejects_an_impossible_window(client) -> None:
    """Недопустимый период — 422 с сообщением, а не молчаливое приведение."""
    assert (await client.get("/data/overview", params={"days": 0})).status_code == 422
    assert (await client.get("/data/overview", params={"days": 5000})).status_code == 422
    assert (await client.get("/data/overview", params={"limit": 0})).status_code == 422


@pytest.mark.asyncio
async def test_data_processing_never_calls_today_final(client) -> None:
    """Суточный архив ЕИС дописывается до полуночи.

    Поэтому «выгружено 42 из 42» за сегодня не означает «за сегодня всё», и
    сервер сообщает это полем, а не оставляет клиенту выводить правило самому.
    """
    body = (await client.get("/data/processing")).json()

    assert body["today"]["final"] is False
    assert body["today"]["runs_succeeded"] == 42


@pytest.mark.asyncio
async def test_data_processing_reports_both_embedding_denominators(client) -> None:
    body = (await client.get("/data/processing")).json()

    embeddings = body["embeddings"]
    assert embeddings["chunks_embedded"] < embeddings["chunks_total"]
    assert embeddings["tenders_embedded"] < embeddings["tenders_total"]
    # Воронка документов не пересчитывается здесь заново — она приходит из
    # того же порта, что и мониторинг.
    assert body["documents_downloaded"] == 100
    assert body["documents_extracted"] == 80


@pytest.mark.asyncio
async def test_data_processing_admits_the_broker_is_silent(client) -> None:
    """Брокер не ответил — это факт о брокере, а не ноль работы в очереди."""
    body = (await client.get("/data/processing")).json()

    # Очереди эмбеддингов у заглушки нет: значит «не знаю», а не ноль.
    assert body["embeddings"]["queue_depth"] is None


@pytest.mark.asyncio
async def test_route_table(client) -> None:
    """Снимок путей: маршрут появляется только вместе с правкой этого списка."""
    schema = (await client.get("/openapi.json")).json()

    assert set(schema["paths"]) == {
        "/tenders",
        "/tenders/search",
        "/tenders/facets",
        "/tenders/groups",
        "/tenders/{reg_num}",
        "/tenders/{reg_num}/similar",
        "/crawl",
        "/documents/{document_id}/download",
        "/documents/{document_id}/text",
        "/documents/{document_id}/chunks",
        "/search/fragments",
        "/filters/compile",
        "/filters",
        "/filters/{filter_id}",
        "/filters/{filter_id}/duplicate",
        "/filters/{filter_id}/run",
        "/filters/{filter_id}/test",
        "/jobs/{job_id}",
        "/digest",
        "/digest/{digest_date}",
        "/monitoring/health",
        "/monitoring/queues",
        "/monitoring/queues/dead-letters/{message_id}/retry",
        "/monitoring/crawler/runs",
        "/monitoring/documents",
        "/data/overview",
        "/data/processing",
        "/settings",
        "/settings/eis-token/rotated",
        "/tenders/{reg_num}/events",
        "/profile/weights",
        "/profile/ranker",
        "/profile/history",
        "/profile/history/{signal_id}",
        "/profile/wins",
        "/recommendations",
        "/feedback",
        "/views",
        "/wins",
        "/profile",
        "/research/runs",
        "/research/runs/{run_id}",
        "/research/runs/{run_id}/tenders",
        "/research/runs/{run_id}/market",
        "/system/load-level",
        "/health",
        "/health/ready",
    }


# ─── Волна 1: фасеты, сортировка, курсор, похожие ─────────────────────────────


@pytest.mark.asyncio
async def test_facets_count_whole_result_not_page(client) -> None:
    response = await client.get("/tenders/facets", params={"region": ["50"]})

    assert response.status_code == 200
    body = response.json()
    # Счётчик фасета относится ко всей выдаче, а не к 20 строкам страницы.
    assert body["total"] == 42
    assert body["regions"][0] == {"key": "50", "label": "Московская область", "count": 30}
    assert body["price_histogram"][0]["count"] == 42
    # Подсказку не просили — считать её незачем.
    assert body["restrictive"] is None


@pytest.mark.asyncio
async def test_facets_explain_empty_names_the_costly_condition(client) -> None:
    response = await client.get("/tenders/facets", params={"explain_empty": True})

    assert response.json()["restrictive"] == {"param": "region", "kept": 240, "dropped": 198}


@pytest.mark.asyncio
async def test_facets_reuse_catalog_filters(client, container) -> None:
    """Фасеты обязаны описывать ту же выдачу, что и список."""
    await client.get(
        "/tenders/facets",
        params={"price_min": 100, "okpd2": "31.01", "only_active": True},
    )

    seen = container.facets.seen
    assert seen.price_min == 100
    assert seen.okpd2_prefix == "31.01"
    assert seen.only_active is True


@pytest.mark.asyncio
async def test_sort_and_order_reach_the_repository(client, container) -> None:
    captured = {}

    async def spy(filters, page):
        captured["sort"] = page.sort
        return Page(items=[], total=0, page=page.page, page_size=page.limit)

    container.catalog.list = spy

    await client.get("/tenders", params={"sort": "price", "order": "asc"})
    assert captured["sort"].field == "price"
    assert captured["sort"].ascending is True


@pytest.mark.asyncio
async def test_unknown_sort_is_rejected(client) -> None:
    assert (await client.get("/tenders", params={"sort": "популярность"})).status_code == 422


@pytest.mark.asyncio
async def test_offset_mode_reports_page_and_cursor_mode_does_not(client) -> None:
    offset = (await client.get("/tenders", params={"page": 2, "page_size": 10})).json()
    assert offset["page"] == 2
    assert offset["next_cursor"] == "cursor-2"

    # В курсорном режиме номера страницы не существует — и врать про него нельзя.
    cursor = await client.get(
        "/tenders", params={"cursor": _cursor_for("published"), "limit": 10}
    )
    assert cursor.json()["page"] is None


@pytest.mark.asyncio
async def test_cursor_from_another_sort_is_rejected(client) -> None:
    """Иначе догрузка пришила бы к списку строки, отсортированные иначе."""
    response = await client.get(
        "/tenders", params={"cursor": _cursor_for("price"), "sort": "published"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_broken_cursor_is_a_client_error(client) -> None:
    response = await client.get("/tenders", params={"cursor": "не-курсор"})
    assert response.status_code == 422


def _cursor_for(field: str) -> str:
    from services.api.domain.pagination import Cursor, SortSpec, encode_cursor

    sort = SortSpec(field=field)
    value = Decimal("1000") if field == "price" else datetime(2026, 8, 6, 9, 0)
    return encode_cursor(Cursor(sort=sort, values=(value,), tender_id=7))


@pytest.mark.asyncio
async def test_similar_tenders(client) -> None:
    response = await client.get(f"/tenders/{REG_NUM}/similar", params={"limit": 3})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["similarity"] == 0.87
    # Объяснение проверяемое, а не пересказ модели.
    assert item["driver"] == "совпадает ОКПД2 и тот же регион"

    assert (await client.get(f"/tenders/{MISSING}/similar")).status_code == 404


@pytest.mark.asyncio
async def test_digest_dates_for_calendar(client) -> None:
    response = await client.get("/digest", params={"from": "2026-08-01", "to": "2026-08-31"})

    assert response.status_code == 200
    assert response.json()["dates"] == [DIGEST_DATE]


@pytest.mark.asyncio
async def test_digest_dates_reject_inverted_period(client) -> None:
    response = await client.get("/digest", params={"from": "2026-08-31", "to": "2026-08-01"})
    assert response.status_code == 422


# ─── Волна 2: фильтры ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filters_list_comes_with_match_history(client) -> None:
    response = await client.get("/filters")

    assert response.status_code == 200
    card = response.json()[0]
    assert card["filter_id"] == 1
    assert card["in_digest"] is True and card["notify"] is False
    # Спарклайн «сколько совпало» — часть карточки, а не отдельный запрос.
    assert card["match_counts"] == [{"day": "2026-08-07", "count": 3}]


@pytest.mark.asyncio
async def test_single_filter_and_missing(client) -> None:
    assert (await client.get("/filters/1")).json()["name"] == "Мебель"

    missing = await client.get("/filters/404")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_saving_edited_spec_does_not_recompile(client, container) -> None:
    """Правки конструктора обязаны сохраниться, а не потеряться при компиляции."""
    edited = {"name": "Мебель", "terms": [{"name": "мебель", "pattern": "мебель"}]}

    response = await client.post(
        "/filters", json={"name": "Мебель", "query": "поставка мебели", "spec": edited}
    )

    assert response.status_code == 201
    assert container.llm.saved_spec == edited


@pytest.mark.asyncio
async def test_saving_without_spec_leaves_compilation_to_the_service(client, container) -> None:
    await client.post("/filters", json={"name": "Мебель", "query": "поставка мебели"})
    assert container.llm.saved_spec is None


@pytest.mark.asyncio
async def test_patch_sends_only_touched_fields(client, container) -> None:
    """Не переданное поле не должно превратиться в null на той стороне."""
    response = await client.patch("/filters/1", json={"notify": True})

    assert response.status_code == 200
    assert container.llm.patched == {"notify": True}


@pytest.mark.asyncio
async def test_delete_returns_204_without_body(client, container) -> None:
    response = await client.delete("/filters/1")

    assert response.status_code == 204
    assert response.content == b""
    assert container.llm.deleted == 1


@pytest.mark.asyncio
async def test_duplicate_and_test(client) -> None:
    copy = await client.post("/filters/1/duplicate")
    assert copy.status_code == 201
    assert copy.json()["name"] == "Мебель (копия)"

    started = await client.post("/filters/1/test", json={"days": 14})
    assert started.status_code == 202
    assert started.json() == {"job_id": JOB_ID, "days": 14}


@pytest.mark.asyncio
async def test_test_period_is_bounded(client) -> None:
    assert (await client.post("/filters/1/test", json={"days": 0})).status_code == 422
    assert (await client.post("/filters/1/test", json={"days": 5000})).status_code == 422


# ─── Волна 3: границы чанков и поиск по фрагментам ────────────────────────────


@pytest.mark.asyncio
async def test_document_chunks_expose_offsets(client) -> None:
    response = await client.get(f"/documents/{DOCUMENT_ID}/chunks")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == DOCUMENT_ID
    assert body["chunks"][0] == {
        "chunk_id": 7,
        "ordinal": 0,
        "char_start": 0,
        "char_end": 51,
        "page": 2,
    }


@pytest.mark.asyncio
async def test_chunk_without_offsets_reports_null_not_zero(client) -> None:
    """Ноль означал бы «начало документа» — это была бы ложная подсветка."""
    chunks = (await client.get(f"/documents/{DOCUMENT_ID}/chunks")).json()["chunks"]

    assert chunks[1]["char_start"] is None
    assert chunks[1]["char_end"] is None


@pytest.mark.asyncio
async def test_chunks_of_missing_document(client) -> None:
    response = await client.get(f"/documents/{MISSING_DOCUMENT_ID}/chunks")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_fragment_search_returns_fragments_not_tenders(client) -> None:
    response = await client.get("/search/fragments", params={"q": "хлоргексидин"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    # Карточка фрагмента: сам текст, его место и разложение оценки.
    assert item["text"].startswith("Мебель")
    assert item["char_start"] == 0
    assert item["highlights"] == [[0, 6]]
    assert item["scores"] == {"lexical": 0.42, "vector": 0.81, "rrf": 0.031}
    # И привязка к закупке, чтобы было куда перейти.
    assert item["reg_num"] == REG_NUM
    assert item["document_name"] == "ТЗ.pdf"


@pytest.mark.asyncio
async def test_fragment_search_modes(client, container) -> None:
    for mode in ("lexical", "semantic", "rrf"):
        assert (
            await client.get("/search/fragments", params={"q": "гарантия", "mode": mode})
        ).status_code == 200
        assert container.fragments.mode == mode

    # По умолчанию — гибридный режим.
    await client.get("/search/fragments", params={"q": "гарантия"})
    assert container.fragments.mode == "rrf"


@pytest.mark.asyncio
async def test_unknown_search_mode_is_rejected(client) -> None:
    response = await client.get("/search/fragments", params={"q": "гарантия", "mode": "магия"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_fragment_search_needs_a_real_query(client) -> None:
    assert (await client.get("/search/fragments", params={"q": "а"})).status_code == 422


# ─── Волна 4: мониторинг, настройки, профиль, события ─────────────────────────


@pytest.mark.asyncio
async def test_health_reports_a_down_service_without_failing(client) -> None:
    """Упавший сосед не должен прятать состояние остальных."""
    response = await client.get("/monitoring/health")

    assert response.status_code == 200
    services = {s["name"]: s for s in response.json()["services"]}
    assert services["llm-service"]["status"] == "down"
    assert services["api"]["status"] == "ok"
    # Факты у каждого свои — это карточка, а не строка таблицы.
    assert services["embedding-service"]["facts"]["device"] == "cpu"


@pytest.mark.asyncio
async def test_queues_expose_depth_ladder_and_dead_letters(client) -> None:
    body = (await client.get("/monitoring/queues")).json()

    assert body["queues"][0] == {
        "name": "docs-worker.tender-ingested",
        "depth": 4,
        "consumers": 1,
        "dead_letters": 2,
    }
    # Ступени берутся из топологии, а не выписаны строками в мониторинге.
    assert [s["stage"] for s in body["retry_ladder"]] == ["5с", "30с"]
    assert body["dead_letters"][0]["message_id"] == "m-1"


@pytest.mark.asyncio
async def test_dead_letter_retry(client, container) -> None:
    accepted = await client.post("/monitoring/queues/dead-letters/m-1/retry")
    assert accepted.status_code == 202
    assert container.queues.requeued == "m-1"

    missing = await client.post("/monitoring/queues/dead-letters/нет-такого/retry")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_crawler_runs_carry_the_error_code_and_raw_answer(client) -> None:
    """По одному тексту не отличить блокировку организации от обрыва сети."""
    run = (await client.get("/monitoring/crawler/runs")).json()["items"][0]

    assert run["status"] == "failed"
    assert run["error_code"] == 34
    assert run["raw"] == {"errorInfo": {"code": 34}}


@pytest.mark.asyncio
async def test_document_pipeline_funnel_keeps_stage_order(client) -> None:
    body = (await client.get("/monitoring/documents")).json()

    # Порядок этапов — часть смысла воронки, поэтому список, а не объект.
    assert [s["stage"] for s in body["funnel"]] == [
        "downloaded",
        "extracted",
        "ocr",
        "chunked",
        "embedded",
    ]
    assert body["funnel"][0]["count"] == 100
    # Отложенное отделено от сбоя: оно ждёт более щедрого прогона, а не сломалось.
    assert body["failures"] == [
        {"stage": "failed", "count": 15},
        {"stage": "deferred", "count": 40},
    ]
    # Разбивка причин объясняет разрыв между «скачано» и «извлечён текст».
    assert body["skip_reasons"] == [
        {"stage": "tender_budget", "count": 30},
        {"stage": "multivolume", "count": 10},
    ]


@pytest.mark.asyncio
async def test_tender_events_show_delivery_and_retries(client) -> None:
    items = (await client.get(f"/tenders/{REG_NUM}/events")).json()["items"]

    assert items[0]["status"] == "consumed"
    retried = items[1]
    assert retried["status"] == "retry"
    assert retried["attempt"] == 2
    assert retried["retry_stage"] == "30с"

    assert (await client.get(f"/tenders/{MISSING}/events")).status_code == 404


@pytest.mark.asyncio
async def test_settings_are_masked_and_flag_restart(client) -> None:
    body = (await client.get("/settings")).json()

    # Токен наружу не выходит: только хвост, чтобы отличить один от другого.
    assert body["eis_token"]["masked"].startswith("•")
    assert "cd12" in body["eis_token"]["masked"]
    assert body["llm"]["model"] == "qwen3.6"
    assert body["certificates"][0]["subject"] == "Russian Trusted Root CA"
    # Правка этих ключей без перезапуска ничего не изменит.
    assert body["restart_required_keys"] == ["EIS_TOKEN"]


@pytest.mark.asyncio
async def test_token_rotation_is_recorded_and_shown(client, container) -> None:
    assert (await client.get("/settings")).json()["eis_token"]["rotated_at"] is None

    assert (await client.post("/settings/eis-token/rotated")).status_code == 204

    rotated = (await client.get("/settings")).json()["eis_token"]["rotated_at"]
    assert rotated is not None
    assert container.app_state.stored["eis_token.rotated_at"]["at"] == rotated


@pytest.mark.asyncio
async def test_load_level_defaults_to_balanced(client) -> None:
    """Настройки ещё нет — система обязана назвать уровень, а не промолчать."""
    body = (await client.get("/system/load-level")).json()

    assert body["level"] == 2
    assert body["extraction_workers"] >= 1
    # Параллелизм берётся процессами: потоки внутри делили бы ядра дважды.
    assert body["omp_threads"] == 1


@pytest.mark.asyncio
async def test_load_level_is_stored_and_read_back(client, container) -> None:
    changed = (await client.patch("/system/load-level", json={"level": 1})).json()

    assert changed["level"] == 1
    # Фоновый уровень — ровно один разборщик, сколько бы ядер ни было.
    assert changed["extraction_workers"] == 1
    assert container.app_state.stored["system.load_level"] == {"level": 1}
    assert (await client.get("/system/load-level")).json()["level"] == 1


@pytest.mark.asyncio
async def test_load_level_grows_with_the_level(client) -> None:
    background = (await client.patch("/system/load-level", json={"level": 1})).json()
    full = (await client.patch("/system/load-level", json={"level": 3})).json()

    assert full["extraction_workers"] >= background["extraction_workers"]
    assert full["llm_concurrency"] > background["llm_concurrency"]
    assert full["eis_rps"] > background["eis_rps"]


@pytest.mark.asyncio
async def test_reported_pool_ignores_the_gateway_memory_limit(
    client, monkeypatch
) -> None:
    """Справка о пуле не должна упираться в память шлюза.

    Шлюз намеренно тесен (448 МиБ) и не разбирает документы — пул живёт в
    docs-worker с лимитом втрое больше. Пока ответ считался по памяти шлюза,
    он отдавал один разборщик на всех трёх уровнях: переключатель выглядел
    ни на что не влияющим, хотя воркер поднимал пять.

    Лимит подставлен: на хосте, где тесты идут без cgroup, поправка по памяти
    не срабатывает вовсе и подмены бы не было видно.
    """
    monkeypatch.setattr(load_policy, "detect_memory_mb", lambda: 448)

    full = (await client.patch("/system/load-level", json={"level": 3})).json()

    assert full["extraction_workers"] == detect_cpu_count()


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [0, 4, -1, "полный", None])
async def test_unknown_load_level_is_refused(client, level: object) -> None:
    """Попросили седьмой уровень — получите отказ, а не молчаливый средний.

    Приведение к среднему уместно при чтении настройки, где альтернатива —
    не подняться вовсе. В ответ на явную заявку оно скрывало бы опечатку.
    """
    response = await client.patch("/system/load-level", json={"level": level})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_profile_history_and_wins(client) -> None:
    history = (await client.get("/profile/history")).json()
    assert history["items"][0]["signal"] == "like"
    assert history["total"] == 1

    wins = (await client.get("/profile/wins")).json()
    # Итог считается по цене контракта, а не по НМЦК.
    assert wins["total_value"] == "390000.00"


@pytest.mark.asyncio
async def test_weight_reset_sends_null_not_zero(client, container) -> None:
    """Ноль означал бы «этот код мне не нужен» — это другое утверждение."""
    captured = {}

    async def spy(facet, key, weight):
        captured.update(facet=facet, key=key, weight=weight)
        return []

    container.recsys.set_profile_weight = spy

    await client.patch("/profile/weights", json={"facet": "okpd2", "key": "32.50", "weight": None})
    assert captured == {"facet": "okpd2", "key": "32.50", "weight": None}


@pytest.mark.asyncio
async def test_rating_deletion_goes_to_the_owner(client, container) -> None:
    deleted = {}

    async def spy(signal_id):
        deleted["id"] = signal_id

    container.recsys.delete_rating = spy

    response = await client.delete("/profile/history/5")
    assert response.status_code == 204
    assert deleted["id"] == 5


# ─── Отбор: значение параметра нельзя перепутать ──────────────────────────────


@pytest.mark.asyncio
async def test_documents_status_rejects_unknown_value(client) -> None:
    """Неизвестное значение — ошибка, а не пустая выдача.

    Интерфейс полгода слал `extracted`, которого в системе нет: параметр принят
    как свободная строка, условие не совпало ни разу, экран показывал ноль.
    Молчаливый ноль неотличим от «ничего не найдено» — отсюда и баг.
    """
    for value in ("extracted", "мусор", "DONE"):
        response = await client.get("/tenders", params={"documents_status": value})
        assert response.status_code == 422, f"«{value}» принято молча"

    assert (await client.get("/tenders", params={"documents_status": "done"})).status_code == 200


@pytest.mark.asyncio
async def test_has_text_is_a_separate_filter(client, container) -> None:
    """«Распознан текст» — про наличие текста, а не про статус обработки.

    Статус агрегирует состояние вложений: у части закупок текст есть при
    статусе, отличном от `done`, и наоборот.
    """
    captured = {}

    async def spy(filters, page):
        captured["has_text"] = filters.has_text
        return Page(items=[], total=0, page=page.page, page_size=page.limit)

    container.catalog.list = spy

    await client.get("/tenders", params={"has_text": "true"})
    assert captured["has_text"] is True


@pytest.mark.asyncio
async def test_facets_count_the_search_result_not_predicates(client, container) -> None:
    """При текстовом запросе фасеты считаются по выдаче поиска.

    Предикатами это множество не воспроизвести: часть поиска векторная. Пока
    фасеты считались своими условиями, запрос «мебель» давал 302 в списке и 0
    в счётчиках — экран противоречил сам себе.
    """
    await client.get("/tenders/facets", params={"q": "мебель"})
    assert container.facets.restricted_to == FakeSearch.IDS

    # Без текста ограничивать нечем: предикаты и есть выдача.
    await client.get("/tenders/facets", params={"region": ["50"]})
    assert container.facets.restricted_to is None


# ─── Исследования ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_research_runs_carry_their_funnel(client) -> None:
    response = await client.get("/research/runs")

    assert response.status_code == 200
    card = response.json()[0]
    assert card["run_id"] == RESEARCH_RUN_ID
    assert card["confirmed"] == 56
    # Знаменатель обязателен: «находок 333» без «не прочитано 12» читается как
    # исчерпывающий ответ, хотя часть корпуса ещё не разобрана.
    assert card["funnel"]["documents_pending"] == 12
    assert card["funnel"]["hits_found"] == 333


@pytest.mark.asyncio
async def test_research_tenders_come_with_highlightable_quotes(client) -> None:
    """Цитата и границы совпадения обязаны доехать до клиента целиком.

    Перенос полей здесь однажды делался через `vars()`, и на доменной модели со
    `slots=True` маршрут отдавал 500. Заглушка возвращает настоящий доменный
    объект, поэтому такая правка снова не пройдёт молча.
    """
    response = await client.get(f"/research/runs/{RESEARCH_RUN_ID}/tenders")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    hit = body["items"][0]["hits"][0]
    assert hit["quote"][hit["match_start"] : hit["match_end"]] == "хлоргексидином"
    assert hit["file_name"] == "ТЗ.pdf"
    assert hit["page"] == 2


@pytest.mark.asyncio
async def test_research_tenders_refuse_an_unknown_confidence(client) -> None:
    response = await client.get(
        f"/research/runs/{RESEARCH_RUN_ID}/tenders", params={"confidence": "хорошие"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_research_market_gives_the_median_next_to_the_mean(client) -> None:
    response = await client.get(f"/research/runs/{RESEARCH_RUN_ID}/market")

    assert response.status_code == 200
    body = response.json()
    # У НМЦК тяжёлый правый хвост: одно среднее описывает рынок, которого нет.
    assert body["median_price"] is not None
    assert body["average_price"] is not None
    assert body["by_region"][0]["label"] == "Московская область"

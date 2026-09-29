"""Физическая схема БД — единый источник правды для Alembic.

Схема общая, потому что база одна. Доменные модели у каждого сервиса свои: сервис
читает отсюда строки и собирает из них собственные объекты, а не таскает ORM-сущности
через слои. Так `domain` остаётся свободным от SQLAlchemy (DIP).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from libs.shared.db.base import Base

EMBEDDING_DIM = 1024  # deepvk/USER-bge-m3


class Tender(Base):
    """Извещение о закупке. Ядро системы, наполняется краулером."""

    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reg_num: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(Text, default="RUB")

    publish_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    direct_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_publish_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Предыдущий дедлайн — заполняется при upsert, если дата приёма заявок сдвинулась.
    prev_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bidding_date: Mapped[date | None] = mapped_column(Date)
    summarizing_date: Mapped[date | None] = mapped_column(Date)
    contract_end_date: Mapped[date | None] = mapped_column(Date)

    customer_name: Mapped[str | None] = mapped_column(Text)
    customer_inn: Mapped[str | None] = mapped_column(Text)
    customer_region: Mapped[str | None] = mapped_column(Text)
    region_code: Mapped[str | None] = mapped_column(String(8))

    okpd2_code: Mapped[str | None] = mapped_column(Text)
    okpd2_name: Mapped[str | None] = mapped_column(Text)
    # Все коды ОКПД2 извещения, а не только первый объект закупки.
    okpd2_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    law_type: Mapped[str | None] = mapped_column(Text)
    # `purchaseStatus` в epNotificationEF2020 не приходит, поэтому статус вычисляемый.
    status: Mapped[str | None] = mapped_column(Text)
    raw_xml: Mapped[str | None] = mapped_column(Text)

    documents_status: Mapped[str] = mapped_column(String(16), server_default="pending", index=True)
    # Генерируемый столбец: индекс полнотекстового поиска не может разъехаться с данными.
    # Двухаргументный to_tsvector(regconfig, text) IMMUTABLE — это условие GENERATED.
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('russian', coalesce(name, '') || ' ' || coalesce(description, ''))",
            persisted=True,
        ),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("tenders_publish_date_idx", publish_date.desc()),
        Index("tenders_okpd2_idx", "okpd2_code"),
        Index("tenders_inn_idx", "customer_inn"),
        Index("tenders_end_date_idx", "end_date"),
        Index("tenders_search_tsv_idx", "search_tsv", postgresql_using="gin"),
        Index("tenders_okpd2_codes_idx", "okpd2_codes", postgresql_using="gin"),
    )


class CrawlerRun(Base):
    """Лог запусков краулера. Единственный способ понять, что выгрузка не встала."""

    __tablename__ = "crawler_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(8))
    document_type: Mapped[str | None] = mapped_column(Text)
    target_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched: Mapped[int] = mapped_column(Integer, server_default="0")
    saved: Mapped[int] = mapped_column(Integer, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(Text, server_default="running")
    error_message: Mapped[str | None] = mapped_column(Text)
    # Код отказа ЕИС и сырой dataInfo/errorInfo: по одному тексту не отличить
    # «организация заблокирована» от «сеть не ответила».
    error_code: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class TenderDocument(Base):
    """Вложение извещения: метаданные + местоположение файла в MinIO."""

    __tablename__ = "tender_documents"
    __table_args__ = (
        UniqueConstraint("tender_id", "attachment_id", name="uq_tender_attachment"),
        Index("tender_documents_status_idx", "extraction_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    attachment_id: Mapped[str] = mapped_column(Text)  # publishedContentId
    file_name: Mapped[str | None] = mapped_column(Text)
    doc_kind_code: Mapped[str | None] = mapped_column(Text)
    doc_kind_name: Mapped[str | None] = mapped_column(Text)
    doc_description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(Text)

    minio_key: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)

    # pending → downloading → stored → extracting → done | skipped | failed
    extraction_status: Mapped[str] = mapped_column(String(16), server_default="pending")
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_used: Mapped[bool] = mapped_column(Boolean, server_default="false")
    error_message: Mapped[str | None] = mapped_column(Text)
    #: Порядок разбора: 0 — ТЗ, 1 — обоснование НМЦК, 2 — приложения,
    #: 3 — контракты, 9 — прочее. Считается по имени файла и виду документа.
    priority: Mapped[int | None] = mapped_column(SmallInteger, index=True)
    #: Почему вложение не взяли: том многотомного архива, не влезло в бюджет
    #: закупки, слишком крупное, подпись. Отдельно от `error_message`: отказ по
    #: правилу — это решение, а не сбой, и в воронке они не должны смешиваться.
    skip_reason: Mapped[str | None] = mapped_column(String(24))
    # Глубина вложенности, если файл извлечён из архива внутри архива.
    nesting_depth: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    parent_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tender_documents.id", ondelete="CASCADE")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentText(Base):
    """Метаданные извлечённого текста. Сам текст лежит в объектном хранилище.

    Строка здесь означает «текст у документа есть» и говорит, где он и насколько
    велик. Раньше в `content` лежал и сам текст — он и был главным источником
    роста операционной базы, при том что читают его двое: просмотрщик документа
    и выравниватель смещений чанков. Полнотекстовый поиск идёт по
    `document_chunks`, а не отсюда.

    См. `libs/shared/text_objects.py` — там же объяснено, почему `chunks.text`
    остаётся в базе и перенесён быть не может.
    """

    __tablename__ = "document_texts"

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tender_documents.id", ondelete="CASCADE"), primary_key=True
    )
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    #: Ключ объекта с текстом. NULL у строк, ещё не перенесённых в хранилище.
    text_key: Mapped[str | None] = mapped_column(Text)
    #: sha256 текста. Одинаковый текст лежит в хранилище один раз, поэтому по
    #: этому полю видно, сколько документов делят один объект.
    text_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    #: Прежнее место текста. Заполнено только у неперенесённых строк и удаляется
    #: отдельной миграцией после сверки — снос данных и их копирование в одной
    #: транзакции не оставили бы возможности откатиться.
    content: Mapped[str | None] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, server_default="0")
    lang: Mapped[str | None] = mapped_column(String(8))
    extractor: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentChunk(Base):
    """Чанк документа с эмбеддингом — единица retrieval для LLM-фильтрации."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk"),
        # HNSW вместо ivfflat: не требует обучения на данных и не деградирует
        # по мере роста таблицы.
        Index(
            "document_chunks_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("document_chunks_tsv_idx", "search_tsv", postgresql_using="gin"),
        Index("document_chunks_document_order_idx", "document_id", "chunk_index"),
        # Счётчик векторизованных фрагментов для вкладки «Данные». Без него
        # число, лежащее в двадцати тысячах строк, стоило двух секунд
        # последовательного чтения двух миллионов — а опрашивается оно раз в
        # пятнадцать секунд. Частичный: полный индекс по колонке векторов был
        # бы размером с таблицу.
        Index(
            "document_chunks_embedded_idx",
            "id",
            postgresql_where=text("embedding IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tender_documents.id", ondelete="CASCADE"), index=True
    )
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # Место чанка в document_texts.content: text == content[char_start:char_end].
    # NULL у чанков, нарезанных до появления смещений и не поддавшихся
    # выравниванию, — клиент по этому признаку не рисует ложную подсветку.
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian', text)", persisted=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TenderEmbedding(Base):
    """«Карточный» эмбеддинг тендера: название + описание + ключевые чанки."""

    __tablename__ = "tender_embeddings"
    __table_args__ = (
        Index(
            "tender_embeddings_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    model: Mapped[str] = mapped_column(String(64))
    source_text_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SavedFilter(Base):
    """Сохранённый фильтр: детерминированная часть (`spec`) + критерий для LLM."""

    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    nl_query: Mapped[str | None] = mapped_column(Text)
    spec: Mapped[dict] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", index=True)
    # Тумблеры страницы фильтров: попадает ли в ежедневную сводку и нужно ли
    # уведомлять о новых совпадениях.
    in_digest: Mapped[bool] = mapped_column(Boolean, server_default="true")
    notify: Mapped[bool] = mapped_column(Boolean, server_default="false")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LlmVerdict(Base):
    """Кэш решений LLM-судьи.

    Ключ включает `prompt_version`: смена промпта автоматически инвалидирует кэш,
    а не тихо смешивает вердикты разных версий.
    """

    __tablename__ = "llm_verdicts"
    __table_args__ = (
        UniqueConstraint(
            "tender_id", "filter_id", "prompt_version", name="uq_llm_verdict"
        ),
        Index("llm_verdicts_filter_match_idx", "filter_id", "match"),
        # Спарклайн «сколько совпало по дням» на странице фильтров.
        Index("llm_verdicts_filter_created_idx", "filter_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    filter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("saved_filters.id", ondelete="CASCADE"), index=True
    )
    match: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    reasoning: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list | None] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TenderView(Base):
    """Факт просмотра тендера — слабый положительный сигнал для рекомендаций."""

    __tablename__ = "tender_views"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    dwell_ms: Mapped[int | None] = mapped_column(Integer)


class TenderFeedback(Base):
    """Явная оценка тендера. Один активный сигнал на тендер — перезаписывается."""

    __tablename__ = "tender_feedback"
    __table_args__ = (UniqueConstraint("tender_id", name="uq_tender_feedback"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    signal: Mapped[str] = mapped_column(String(16))  # like|dislike|hide|shortlist
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WonTender(Base):
    """Выигранный тендер — сильнейший положительный сигнал для профиля."""

    __tablename__ = "won_tenders"
    __table_args__ = (UniqueConstraint("tender_id", name="uq_won_tender"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    won_at: Mapped[date | None] = mapped_column(Date)
    contract_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DailyDigest(Base):
    """ИИ-сводка за день. Один готовый документ на дату."""

    __tablename__ = "daily_digests"

    digest_date: Mapped[date] = mapped_column(Date, primary_key=True)
    summary_md: Mapped[str] = mapped_column(Text)
    sections: Mapped[dict | None] = mapped_column(JSONB)
    tender_count: Mapped[int] = mapped_column(Integer, server_default="0")
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    """Статус длительной операции, запущенной через API (202 + job_id)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), server_default="queued", index=True)
    #: Какой этап операции идёт сейчас: «обход корпуса», «судья читает
    #: документы». Долгие операции состоят из фаз с разной ценой единицы
    #: работы, и `processed`/`total` считаются **внутри фазы** — сквозной
    #: процент по разнородным фазам был бы выдуманным числом. Без имени фазы
    #: шкала, дошедшая до конца обхода, выглядела бы завершённой посреди
    #: работы судьи.
    phase: Mapped[str | None] = mapped_column(String(64))
    total: Mapped[int] = mapped_column(Integer, server_default="0")
    processed: Mapped[int] = mapped_column(Integer, server_default="0")
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RecommendationProfile(Base):
    """Профиль интересов: центроид эмбеддингов + статистика предпочтений.

    Одна строка (однопользовательский режим), но с `id` — чтобы переход
    на многопользовательский режим был миграцией, а не переписыванием.
    """

    __tablename__ = "recommendation_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default="1")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    okpd2_weights: Mapped[dict | None] = mapped_column(JSONB)
    price_stats: Mapped[dict | None] = mapped_column(JSONB)
    customer_weights: Mapped[dict | None] = mapped_column(JSONB)
    # Ручные правки весов. Отдельно от вычисленных: пересборка профиля обязана
    # их уважать, а не затирать.
    manual_weights: Mapped[dict | None] = mapped_column(JSONB)
    signal_count: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RecommendationImpression(Base):
    """Что уже показывали в рекомендациях — чтобы не показывать одно и то же."""

    __tablename__ = "recommendation_impressions"
    __table_args__ = (UniqueConstraint("tender_id", name="uq_recommendation_impression"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    shown_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    score: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[dict | None] = mapped_column(JSONB)


class AppSetting(Base):
    """Состояние интерфейса, которое некому хранить, кроме шлюза.

    Единственная таблица, в которую пишет `api`: у неё нет других писателей,
    поэтому правило «один агрегат — один писатель» не нарушается.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ResearchRun(Base):
    """Один прогон исследования: критерий, период, регионы и воронка.

    Прогон — единица работы и единица наблюдаемости. Воронка хранится прямо
    здесь, потому что без знаменателей её числа не значат ничего: «находок
    нет» — это вывод только тогда, когда известно, сколько документов при этом
    прочитано. В прогоне ХПК/БПК вывод «в приоритетах 3 и 9 находок нет»
    оказался пустым ровно по этой причине.
    """

    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    #: Версия критериев. Меняется вместе с шаблонами и обесценивает кэш вердиктов.
    criteria_version: Mapped[str] = mapped_column(String(32), index=True)
    #: Полное описание критерия — чтобы прогон можно было объяснить задним числом.
    criteria: Mapped[dict] = mapped_column(JSONB)

    regions: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)

    status: Mapped[str] = mapped_column(String(16), server_default="running")
    error_message: Mapped[str | None] = mapped_column(Text)

    # ─── Воронка ────────────────────────────────────────────────────────────
    tenders_total: Mapped[int] = mapped_column(Integer, server_default="0")
    tenders_candidate: Mapped[int] = mapped_column(Integer, server_default="0")
    documents_scanned: Mapped[int] = mapped_column(Integer, server_default="0")
    #: Документы, до которых не дошли. Тот самый знаменатель.
    documents_pending: Mapped[int] = mapped_column(Integer, server_default="0")
    hits_found: Mapped[int] = mapped_column(Integer, server_default="0")
    tenders_confirmed: Mapped[int] = mapped_column(Integer, server_default="0")
    tenders_rejected: Mapped[int] = mapped_column(Integer, server_default="0")
    tenders_disputed: Mapped[int] = mapped_column(Integer, server_default="0")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchHit(Base):
    """Упоминание с контекстом — то, по чему принимается решение.

    Хранится цитата, а не ссылка на место в тексте: документ переразбирают,
    смещения уезжают, а цитата остаётся проверяемой. `match_start`/`match_end`
    позволяют показать её с подсветкой — без неё видно только левый контекст.
    """

    __tablename__ = "research_hits"
    __table_args__ = (
        Index("research_hits_run_tender_idx", "run_id", "tender_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tender_documents.id", ondelete="SET NULL")
    )

    term: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    quote: Mapped[str] = mapped_column(Text)
    match_start: Mapped[int] = mapped_column(Integer, server_default="0")
    match_end: Mapped[int] = mapped_column(Integer, server_default="0")
    file_name: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    source_offset: Mapped[int] = mapped_column(Integer, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ResearchVerdict(Base):
    """Решение по закупке — правилами или моделью.

    Ключ не включает прогон: решение принадлежит паре «закупка + критерий», а
    не конкретному запуску. Поэтому повторный прогон с теми же критериями не
    тратит токенов, а правка шаблонов обесценивает кэш сама собой — через
    версию.
    """

    __tablename__ = "research_verdicts"
    __table_args__ = (
        UniqueConstraint(
            "tender_id",
            "criteria_version",
            "prompt_version",
            name="uq_research_verdict",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    criteria_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(32))

    confidence: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, server_default="0")
    #: `rules` или `model` — видно, во что обошёлся прогон.
    decided_by: Mapped[str] = mapped_column(String(16), server_default="rules")
    evidence: Mapped[list | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

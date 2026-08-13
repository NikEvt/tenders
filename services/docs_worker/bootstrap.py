"""Composition root docs-worker."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aio_pika.abc import AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from libs.shared.config import DatabaseSettings, EisSettings, MinioSettings, RabbitSettings
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.load_control import LoadController
from libs.shared.load_policy import LoadBudget
from libs.shared.load_store import LoadLevelWatcher, SqlLoadLevelStore
from libs.shared.messaging.outbox import OutboxRelay, SqlIdempotencyStore
from libs.shared.messaging.publisher import RabbitPublisher
from libs.shared.messaging.topology import connect
from services.docs_worker.application.ports import TextExtractionPort
from services.docs_worker.application.use_cases.process_documents import (
    ProcessTenderDocumentsUseCase,
)
from services.docs_worker.infrastructure.chunking import RecursiveChunker
from services.docs_worker.infrastructure.db.document_repository import SqlDocumentRepository
from services.docs_worker.infrastructure.eis.attachment_downloader import EisAttachmentDownloader
from services.docs_worker.infrastructure.extraction.archives import (
    RarExtractor,
    SevenZipExtractor,
    ZipExtractor,
)
from services.docs_worker.infrastructure.extraction.base import (
    ExtractorRegistry,
    SkippedExtractor,
)
from services.docs_worker.infrastructure.extraction.documents import (
    DocxExtractor,
    LegacyOfficeExtractor,
    PdfExtractor,
    PlainTextExtractor,
    RtfExtractor,
    XlsxExtractor,
)
from services.docs_worker.infrastructure.extraction.ocr import (
    OcrImageExtractor,
    OcrPdfExtractor,
    PdfWithOcrFallback,
)
from services.docs_worker.infrastructure.extraction.pool import ProcessPoolExtraction
from services.docs_worker.infrastructure.storage.minio_storage import MinioObjectStorage


def build_extraction(ocr_languages: str = "rus+eng") -> TextExtractionPort:
    """Собирает цепочку стратегий.

    Порядок значим: подписи отсеиваются первыми, PDF идёт через декоратор с OCR,
    архивы — до общих текстовых форматов.
    """
    return ExtractorRegistry(
        [
            SkippedExtractor(),
            PdfWithOcrFallback(PdfExtractor(), OcrPdfExtractor(languages=ocr_languages)),
            DocxExtractor(),
            XlsxExtractor(),
            RtfExtractor(),
            LegacyOfficeExtractor(),
            ZipExtractor(),
            SevenZipExtractor(),
            RarExtractor(),
            OcrImageExtractor(languages=ocr_languages),
            PlainTextExtractor(),
        ]
    )


@dataclass
class DocsWorkerContainer:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    connection: AbstractRobustConnection
    relay: OutboxRelay
    idempotency: SqlIdempotencyStore
    use_case: ProcessTenderDocumentsUseCase
    #: Уровень нагрузки и подписчики на его смену.
    controller: LoadController
    #: Пул разбора — единственное, что здесь по-настоящему ест машину.
    extraction: ProcessPoolExtraction
    #: Сверка с записанной настройкой уровня.
    load_watcher: LoadLevelWatcher


@asynccontextmanager
async def build_container(
    db: DatabaseSettings,
    rabbit: RabbitSettings,
    minio: MinioSettings,
    eis: EisSettings,
) -> AsyncIterator[DocsWorkerContainer]:
    engine = create_engine(db.async_dsn)
    session_factory = create_session_factory(engine)
    connection = await connect(rabbit.dsn)

    publisher = RabbitPublisher(connection)
    await publisher.setup()

    storage = MinioObjectStorage(minio)
    storage.ensure_bucket()

    controller = LoadController()
    # Разбор идёт процессами, а не потоками: pypdfium2 не потокобезопасен и на
    # параллельных PDF убивает процесс нативным сигналом. См. `extraction/pool.py`.
    extraction = ProcessPoolExtraction(controller.budget.extraction_workers)
    controller.subscribe(_resize_pool(extraction))

    use_case = ProcessTenderDocumentsUseCase(
        repository=SqlDocumentRepository(session_factory),
        downloader=EisAttachmentDownloader(token=eis.token.get_secret_value()),
        storage=storage,
        extraction=extraction,
        chunker=RecursiveChunker(),
        # Публикуем напрямую: обработка документов идёт вне одной транзакции,
        # а повторная выдача события безопасна — потребители идемпотентны.
        publisher=publisher,
    )

    container = DocsWorkerContainer(
        engine=engine,
        session_factory=session_factory,
        connection=connection,
        relay=OutboxRelay(session_factory, publisher),
        idempotency=SqlIdempotencyStore(session_factory),
        use_case=use_case,
        controller=controller,
        extraction=extraction,
        load_watcher=LoadLevelWatcher(SqlLoadLevelStore(session_factory), controller),
    )

    try:
        yield container
    finally:
        container.load_watcher.stop()
        container.relay.stop()
        extraction.shutdown()
        await connection.close()
        await engine.dispose()


def _resize_pool(extraction: ProcessPoolExtraction):
    """Подписчик на смену уровня: меняет размер пула разбора.

    Пересборка происходит на границе задач — уже начатый разбор доводится до
    конца, новые документы уходят в пул нового размера.
    """

    async def apply(budget: LoadBudget) -> None:
        extraction.resize(budget.extraction_workers)

    return apply

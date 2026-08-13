"""Сценарии обработки документов тендера."""

from __future__ import annotations

import asyncio
import hashlib

from libs.shared.contracts.events import (
    DocumentExtracted,
    EmbeddingRequested,
    TenderEnriched,
    TenderIngested,
)
from libs.shared.contracts.ports import EventPublisher, ObjectStoragePort
from libs.shared.logging import get_logger
from libs.shared.text_objects import (
    TEXT_CONTENT_TYPE,
    decode_text,
    encode_text,
    text_digest,
    text_key,
)
from services.docs_worker.application.ports import (
    AttachmentDownloaderPort,
    ChunkerPort,
    DocumentRepositoryPort,
    TextExtractionPort,
)
from services.docs_worker.domain.admission import AdmissionPolicy, Candidate
from services.docs_worker.domain.models import (
    DocumentRef,
    DocumentsStatus,
    ExtractedPage,
    ExtractedText,
    ExtractionStatus,
    StoredFile,
)

log = get_logger(__name__)

# Архив внутри архива внутри архива — дальше почти наверняка мусор,
# а рекурсия без потолка легко становится бесконечной.
MAX_NESTING_DEPTH = 2


class ProcessTenderDocumentsUseCase:
    """Обрабатывает все вложения одного тендера: скачать → сохранить → извлечь → нарезать.

    Controller сценария. Порядок и обработка сбоев здесь; как именно качать, где
    хранить и чем парсить — за портами.
    """

    def __init__(
        self,
        repository: DocumentRepositoryPort,
        downloader: AttachmentDownloaderPort,
        storage: ObjectStoragePort,
        extraction: TextExtractionPort,
        chunker: ChunkerPort,
        publisher: EventPublisher,
        admission: AdmissionPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._downloader = downloader
        self._storage = storage
        self._extraction = extraction
        self._chunker = chunker
        self._publisher = publisher
        self._admission = admission or AdmissionPolicy()

    async def execute(self, event: TenderIngested) -> None:
        attachments = await self._repository.attachments_for_tender(event.tender_id)
        decisions = self._admission.plan(
            [
                Candidate(
                    document_id=ref.document_id,
                    file_name=ref.file_name,
                    doc_kind_name=ref.doc_kind_name,
                    file_size=ref.file_size,
                    source_url=ref.source_url,
                    processed=ref.processed,
                )
                for ref in attachments
            ]
        )
        by_id = {ref.document_id: ref for ref in attachments}

        # Приоритет проставляется всем вложениям, а не только взятым в работу:
        # по нему обзорные проходы отбирают «только ТЗ и обоснования».
        await self._repository.save_priorities(
            {d.candidate.document_id: d.priority for d in decisions}
        )

        if not decisions:
            log.info("docs.nothing_to_do", tender_id=event.tender_id)

        for decision in decisions:
            ref = by_id[decision.candidate.document_id]
            if not decision.accepted:
                # Отказ фиксируется до скачивания: смысл политики как раз в том,
                # чтобы не тратить сеть на том архива, который не распакуется.
                await self._repository.mark_skipped(
                    ref.document_id, str(decision.reason), decision.reason.is_final
                )
                continue
            await self._process_one(ref)

        status = await self._repository.refresh_tender_status(event.tender_id)

        # Эмбеддинг карточки строится всегда: он не зависит от успеха документов,
        # иначе тендер без вложений не попадёт ни в поиск, ни в рекомендации.
        await self._publisher.publish(
            EmbeddingRequested(target="tender", tender_id=event.tender_id)
        )

        if status is not DocumentsStatus.PENDING:
            await self._publisher.publish(
                TenderEnriched(
                    tender_id=event.tender_id,
                    reg_num=event.reg_num,
                    documents_status=(
                        status.value if status.value in {"done", "partial", "failed"} else "partial"
                    ),
                )
            )

    async def _process_one(self, ref: DocumentRef) -> None:
        try:
            stored = await self._store(ref)
            if stored is None:
                return
            await self._extract(ref, stored)
        except Exception as exc:
            # Сбой на одном вложении не должен обрывать обработку остальных:
            # у извещения их бывает до нескольких десятков.
            log.warning(
                "docs.document_failed",
                document_id=ref.document_id,
                file_name=ref.file_name,
                error=str(exc),
            )
            await self._repository.mark_status(
                ref.document_id, ExtractionStatus.FAILED, str(exc)[:500]
            )

    async def _store(self, ref: DocumentRef) -> StoredFile | None:
        if not ref.source_url:
            await self._repository.mark_status(
                ref.document_id, ExtractionStatus.SKIPPED, "нет ссылки на файл"
            )
            return None

        await self._repository.mark_status(ref.document_id, ExtractionStatus.DOWNLOADING)

        content, content_type = await asyncio.to_thread(self._downloader.download, ref.source_url)

        # Сам файл в хранилище не кладётся. Ценность вложения — в тексте, а не
        # в исходном pdf: текст ищется, цитируется и уходит судье, тогда как
        # оригинал за всё время нужен один раз — когда человек открывает
        # документ, чтобы проверить цитату. Ради этого случая остаётся
        # `source_url`: файл лежит в ЕИС и никуда оттуда не денется, а хранить
        # десятки гигабайт копий — платить за то, чем не пользуются.
        stored = StoredFile(
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_type=content_type,
            content=content,
        )
        await self._repository.save_stored_file(ref.document_id, stored)
        return stored

    async def _extract(self, ref: DocumentRef, stored: StoredFile) -> None:
        await self._repository.mark_status(ref.document_id, ExtractionStatus.EXTRACTING)

        # Тот же файл уже разбирали — байты совпали, значит и текст совпадёт.
        # Экономится самое дорогое: OCR скана и запуск LibreOffice. Чанки при
        # этом нарезаются заново, потому что они принадлежат документу, а не
        # файлу, и на них ссылаются эмбеддинги и цитаты вердиктов.
        reused = await self._reuse_text(ref, stored)
        if reused:
            return

        extracted: ExtractedText = await asyncio.to_thread(
            self._extraction.extract,
            stored.content,
            ref.file_name or ref.attachment_id,
            stored.content_type,
        )

        if extracted.embedded_files:
            await self._process_archive(ref, extracted)
            return

        if extracted.is_empty:
            await self._repository.mark_status(
                ref.document_id,
                ExtractionStatus.SKIPPED,
                f"текст не извлечён ({extracted.extractor})",
            )
            return

        chunks = self._chunker.split(extracted)
        text_key, text_sha256 = await self._store_text(extracted)
        chunk_ids = await self._repository.save_text_and_chunks(
            ref, extracted, chunks, text_key, text_sha256
        )
        await self._repository.mark_status(ref.document_id, ExtractionStatus.DONE)

        await self._publisher.publish(
            DocumentExtracted(
                document_id=ref.document_id,
                tender_id=ref.tender_id,
                chunk_ids=chunk_ids,
                ocr_used=extracted.ocr_used,
                char_count=extracted.char_count,
            )
        )
        log.info(
            "docs.extracted",
            document_id=ref.document_id,
            extractor=extracted.extractor,
            ocr=extracted.ocr_used,
            chars=extracted.char_count,
            chunks=len(chunks),
        )

    async def _reuse_text(self, ref: DocumentRef, stored: StoredFile) -> bool:
        """Переиспользует текст файла, который уже разбирали.

        Возвращает True, если документ дособран из готового текста. Сбой чтения
        не считается ошибкой документа: разобрать файл заново мы всё ещё умеем,
        и это лучше, чем помечать его сбойным из-за недоступного объекта.
        """
        found = await self._repository.find_extracted_text(stored.sha256)
        if found is None:
            return False

        key, digest = found
        try:
            raw = await asyncio.to_thread(self._storage.get, key)
        except Exception as exc:
            log.warning("docs.text_reuse_failed", document_id=ref.document_id, error=str(exc))
            return False

        extracted = ExtractedText(
            pages=[ExtractedPage(number=1, text=decode_text(raw))],
            extractor="reused",
        )
        chunks = self._chunker.split(extracted)
        chunk_ids = await self._repository.save_text_and_chunks(
            ref, extracted, chunks, key, digest
        )
        await self._repository.mark_status(ref.document_id, ExtractionStatus.DONE)

        await self._publisher.publish(
            DocumentExtracted(
                document_id=ref.document_id,
                tender_id=ref.tender_id,
                chunk_ids=chunk_ids,
                ocr_used=False,
                char_count=extracted.char_count,
            )
        )
        log.info("docs.text_reused", document_id=ref.document_id, sha256=stored.sha256[:16])
        return True

    async def _store_text(self, extracted: ExtractedText) -> tuple[str, str]:
        """Кладёт извлечённый текст в хранилище и возвращает ключ и хеш.

        Ключ считается от содержимого, поэтому типовые приложения — проект
        контракта, памятка участнику — физически хранятся один раз, сколько бы
        извещений их ни приложило. Проверка `exists` дешевле повторной заливки
        и на типовых документах срабатывает постоянно.
        """
        content = extracted.content
        digest = text_digest(content)
        key = text_key(digest)

        if not await asyncio.to_thread(self._storage.exists, key):
            await asyncio.to_thread(
                self._storage.put_bytes, key, encode_text(content), TEXT_CONTENT_TYPE
            )
        return key, digest

    async def _process_archive(self, ref: DocumentRef, extracted: ExtractedText) -> None:
        """Каждый файл из архива становится самостоятельным документом тендера."""
        if ref.nesting_depth >= MAX_NESTING_DEPTH:
            await self._repository.mark_status(
                ref.document_id, ExtractionStatus.SKIPPED, "превышена глубина вложенности архивов"
            )
            return

        for embedded in extracted.embedded_files:
            child = await self._repository.add_embedded_document(ref, embedded.file_name)
            # Как и у обычного вложения, наружу уходит текст, а не файл. У файла
            # из архива нет даже своего `source_url`: добраться до него можно
            # только через родительский архив, и это ещё один довод не делать
            # вид, будто копия оригинала где-то хранится.
            stored = StoredFile(
                sha256=hashlib.sha256(embedded.content).hexdigest(),
                size_bytes=len(embedded.content),
                content_type=None,
                content=embedded.content,
            )
            await self._repository.save_stored_file(child.document_id, stored)
            try:
                await self._extract(child, stored)
            except Exception as exc:
                log.warning(
                    "docs.embedded_failed", file_name=embedded.file_name, error=str(exc)
                )
                await self._repository.mark_status(
                    child.document_id, ExtractionStatus.FAILED, str(exc)[:500]
                )

        await self._repository.mark_status(ref.document_id, ExtractionStatus.DONE)

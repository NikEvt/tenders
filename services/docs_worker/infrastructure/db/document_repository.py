"""Персистентность документов, извлечённых текстов и чанков."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.db.schema import DocumentChunk, DocumentText, Tender, TenderDocument
from libs.shared.logging import get_logger
from services.docs_worker.application.ports import DocumentRepositoryPort
from services.docs_worker.domain.models import (
    Chunk,
    DocumentRef,
    DocumentsStatus,
    ExtractedText,
    ExtractionStatus,
    StoredFile,
)

log = get_logger(__name__)

# Состояния, из которых документ уже не надо обрабатывать заново.
TERMINAL_STATUSES = (
    ExtractionStatus.DONE.value,
    ExtractionStatus.SKIPPED.value,
)

# Бюджет закупки расходует только то, что действительно разобрали. Отказ по
# правилу ни сети, ни диска не стоил, и занимать место в бюджете не должен —
# иначе двадцать отклонённых томов «съедали» бы квоту техзадания.
SPENT_STATUSES = (ExtractionStatus.DONE.value,)


class SqlDocumentRepository(DocumentRepositoryPort):
    """Каждая операция — своя короткая транзакция.

    Обработка одного вложения занимает минуты (скачивание, OCR); держать всё это
    в одной транзакции значило бы держать блокировки и соединение открытыми.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def attachments_for_tender(self, tender_id: int) -> list[DocumentRef]:
        """Все вложения закупки, включая уже разобранные.

        Разобранные нужны политике допуска: бюджет веса считается по всей
        закупке, иначе возобновлённый прогон выдавал бы ей новый бюджет и
        лимит перестал бы что-либо ограничивать.
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        TenderDocument.id,
                        TenderDocument.tender_id,
                        Tender.reg_num,
                        TenderDocument.attachment_id,
                        TenderDocument.file_name,
                        TenderDocument.source_url,
                        TenderDocument.nesting_depth,
                        TenderDocument.file_size,
                        TenderDocument.doc_kind_name,
                        TenderDocument.extraction_status,
                    )
                    .join(Tender, Tender.id == TenderDocument.tender_id)
                    .where(
                        TenderDocument.tender_id == tender_id,
                        # Файлы из архивов обрабатываются в рамках родителя.
                        TenderDocument.parent_document_id.is_(None),
                    )
                    .order_by(TenderDocument.id)
                )
            ).all()

        return [
            DocumentRef(
                document_id=row.id,
                tender_id=row.tender_id,
                reg_num=row.reg_num,
                attachment_id=row.attachment_id,
                file_name=row.file_name,
                source_url=row.source_url,
                nesting_depth=row.nesting_depth,
                file_size=row.file_size,
                doc_kind_name=row.doc_kind_name,
                processed=row.extraction_status in SPENT_STATUSES,
            )
            for row in rows
        ]

    async def get(self, document_id: int) -> DocumentRef | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        TenderDocument.id,
                        TenderDocument.tender_id,
                        Tender.reg_num,
                        TenderDocument.attachment_id,
                        TenderDocument.file_name,
                        TenderDocument.source_url,
                        TenderDocument.nesting_depth,
                    )
                    .join(Tender, Tender.id == TenderDocument.tender_id)
                    .where(TenderDocument.id == document_id)
                )
            ).first()

        if row is None:
            return None
        return DocumentRef(
            document_id=row.id,
            tender_id=row.tender_id,
            reg_num=row.reg_num,
            attachment_id=row.attachment_id,
            file_name=row.file_name,
            source_url=row.source_url,
            nesting_depth=row.nesting_depth,
        )

    async def mark_status(
        self,
        document_id: int,
        status: ExtractionStatus,
        error: str | None = None,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(TenderDocument)
                .where(TenderDocument.id == document_id)
                .values(
                    extraction_status=status.value,
                    error_message=error,
                    updated_at=func.now(),
                )
            )

    async def save_priorities(self, priorities: Mapping[int, int]) -> None:
        """Запрос на каждый различный приоритет, а не на каждое вложение.

        Различных приоритетов пять, а вложений у извещения — десятки, поэтому
        группировка по значению превращает десятки UPDATE в пять. Пакетный
        UPDATE по первичному ключу здесь не годится: ORM разбирает его как
        bulk-update и требует идентификатор в самих значениях.
        """
        if not priorities:
            return

        grouped: dict[int, list[int]] = {}
        for document_id, priority in priorities.items():
            grouped.setdefault(priority, []).append(document_id)

        async with self._session_factory() as session, session.begin():
            for priority, document_ids in grouped.items():
                await session.execute(
                    update(TenderDocument)
                    .where(TenderDocument.id.in_(document_ids))
                    .values(priority=priority)
                )

    async def mark_skipped(self, document_id: int, reason: str, final: bool) -> None:
        status = ExtractionStatus.SKIPPED if final else ExtractionStatus.DEFERRED
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(TenderDocument)
                .where(TenderDocument.id == document_id)
                .values(
                    extraction_status=status.value,
                    skip_reason=reason,
                    updated_at=func.now(),
                )
            )

    async def save_stored_file(self, document_id: int, stored: StoredFile) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(TenderDocument)
                .where(TenderDocument.id == document_id)
                .values(
                    sha256=stored.sha256,
                    file_size=stored.size_bytes,
                    content_type=stored.content_type,
                    extraction_status=ExtractionStatus.STORED.value,
                    updated_at=func.now(),
                )
            )

    async def find_extracted_text(self, sha256: str) -> tuple[str, str] | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(DocumentText.text_key, DocumentText.text_sha256)
                    .join(TenderDocument, TenderDocument.id == DocumentText.document_id)
                    .where(
                        TenderDocument.sha256 == sha256,
                        DocumentText.text_key.is_not(None),
                    )
                    .limit(1)
                )
            ).first()
        return (row.text_key, row.text_sha256) if row else None

    async def save_text_and_chunks(
        self,
        ref: DocumentRef,
        text: ExtractedText,
        chunks: Sequence[Chunk],
        text_key: str,
        text_sha256: str,
    ) -> list[int]:
        async with self._session_factory() as session, session.begin():
            # Повторная обработка документа заменяет прежний текст и чанки целиком.
            # `content` затирается в NULL: строка могла остаться от прежней
            # схемы, и оставить её значило бы держать две версии одного текста,
            # расходящиеся при переразборе.
            await session.execute(
                pg_insert(DocumentText)
                .values(
                    document_id=ref.document_id,
                    tender_id=ref.tender_id,
                    text_key=text_key,
                    text_sha256=text_sha256,
                    content=None,
                    char_count=text.char_count,
                    lang=text.lang,
                    extractor=text.extractor,
                )
                .on_conflict_do_update(
                    index_elements=[DocumentText.document_id],
                    set_={
                        "text_key": text_key,
                        "text_sha256": text_sha256,
                        "content": None,
                        "char_count": text.char_count,
                        "lang": text.lang,
                        "extractor": text.extractor,
                    },
                )
            )

            await session.execute(
                update(TenderDocument)
                .where(TenderDocument.id == ref.document_id)
                .values(
                    page_count=text.page_count,
                    ocr_used=text.ocr_used,
                    updated_at=func.now(),
                )
            )

            if not chunks:
                return []

            statement = pg_insert(DocumentChunk).values(
                [
                    {
                        "document_id": ref.document_id,
                        "tender_id": ref.tender_id,
                        "chunk_index": chunk.index,
                        "text": chunk.text,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "page_from": chunk.page_from,
                        "page_to": chunk.page_to,
                        "token_estimate": chunk.token_estimate,
                    }
                    for chunk in chunks
                ]
            )
            result = await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_document_chunk",
                    set_={
                        "text": statement.excluded.text,
                        "char_start": statement.excluded.char_start,
                        "char_end": statement.excluded.char_end,
                        "page_from": statement.excluded.page_from,
                        "page_to": statement.excluded.page_to,
                        "token_estimate": statement.excluded.token_estimate,
                        # Текст изменился — прежний эмбеддинг больше не соответствует.
                        "embedding": None,
                    },
                ).returning(DocumentChunk.id)
            )
            return [row[0] for row in result.all()]

    async def add_embedded_document(self, parent: DocumentRef, file_name: str) -> DocumentRef:
        # Идентификатор вложенного файла выводим из родительского, чтобы повторная
        # распаковка того же архива не плодила дубликаты.
        attachment_id = f"{parent.attachment_id}:{file_name}"[:512]

        async with self._session_factory() as session, session.begin():
            statement = pg_insert(TenderDocument).values(
                tender_id=parent.tender_id,
                attachment_id=attachment_id,
                file_name=file_name,
                parent_document_id=parent.document_id,
                nesting_depth=parent.nesting_depth + 1,
                extraction_status=ExtractionStatus.PENDING.value,
            )
            document_id = await session.scalar(
                statement.on_conflict_do_update(
                    constraint="uq_tender_attachment",
                    set_={"file_name": statement.excluded.file_name, "updated_at": func.now()},
                ).returning(TenderDocument.id)
            )

        assert document_id is not None
        return DocumentRef(
            document_id=document_id,
            tender_id=parent.tender_id,
            reg_num=parent.reg_num,
            attachment_id=attachment_id,
            file_name=file_name,
            source_url=None,
            nesting_depth=parent.nesting_depth + 1,
        )

    async def refresh_tender_status(self, tender_id: int) -> DocumentsStatus:
        """Сводит статусы вложений в один статус тендера."""
        async with self._session_factory() as session, session.begin():
            counts = (
                await session.execute(
                    select(TenderDocument.extraction_status, func.count())
                    .where(TenderDocument.tender_id == tender_id)
                    .group_by(TenderDocument.extraction_status)
                )
            ).all()

            by_status = {status: count for status, count in counts}
            total = sum(by_status.values())
            failed = by_status.get(ExtractionStatus.FAILED.value, 0)
            finished = by_status.get(ExtractionStatus.DONE.value, 0) + by_status.get(
                ExtractionStatus.SKIPPED.value, 0
            )
            # Отложенное политикой не в работе и не потеряно — оно ждёт более
            # щедрых настроек. Тендер из-за него не должен вечно висеть в
            # «обрабатывается», но и полным его охват называть нельзя.
            deferred = by_status.get(ExtractionStatus.DEFERRED.value, 0)

            if total == 0:
                # Вложений нет вовсе — обрабатывать нечего, это не сбой.
                status = DocumentsStatus.DONE
            elif failed == total:
                status = DocumentsStatus.FAILED
            elif finished + failed + deferred == total:
                status = (
                    DocumentsStatus.PARTIAL if (failed or deferred) else DocumentsStatus.DONE
                )
            else:
                status = DocumentsStatus.PROCESSING

            await session.execute(
                update(Tender)
                .where(Tender.id == tender_id)
                .values(documents_status=status.value, updated_at=func.now())
            )

        return status

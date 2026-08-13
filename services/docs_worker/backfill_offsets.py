"""Разовый бэкфилл смещений у чанков, нарезанных до появления `char_start`.

Почему нельзя просто `content.find(chunk.text)`. Прежний чанкер собирал текст
из кусков страницы, приклеивая к каждому пробел, и делал `strip()`, а между
страницами терялся разделитель. Поэтому текст старого чанка — **не подстрока**
документа: пробелы отличаются, и точный поиск вернёт −1 практически всегда.

Почему нельзя перенарезать. Новые границы не совпадут со старыми, а к старым
привязаны уже посчитанные эмбеддинги и `chunk_id` в цитатах вердиктов. Перенарезка
обесценила бы и то и другое.

Отсюда выравнивание: обе строки приводятся к форме со схлопнутыми пробельными
сериями, поиск идёт по ней, а результат отображается обратно в исходные позиции.
Чанки одного документа обрабатываются по порядку, и поиск каждого следующего
начинается с конца предыдущего — так повторяющиеся формулировки («Приложение
№1») не притягивают чанк к первому попавшемуся вхождению.

Запуск:  python -m services.docs_worker.backfill_offsets [--dry-run]
Идемпотентен: уже заполненные строки пропускаются, прерванный прогон
продолжается с места остановки.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.config import database_settings, minio_settings
from libs.shared.contracts.ports import ObjectStoragePort
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.db.schema import DocumentChunk, DocumentText
from libs.shared.logging import configure_logging, get_logger
from libs.shared.text_objects import decode_text
from services.docs_worker.infrastructure.storage.minio_storage import MinioObjectStorage

log = get_logger(__name__)

DOCUMENT_BATCH = 200


@dataclass(slots=True)
class Stats:
    documents: int = 0
    aligned: int = 0
    failed: int = 0
    #: Документы, текст которых не удалось прочитать.
    skipped: int = 0


async def _read_text(
    storage: ObjectStoragePort | None, text_key: str | None, inline: str | None
) -> str | None:
    """Текст из хранилища, а у неперенесённых документов — из базы."""
    if text_key:
        if storage is None:
            return None
        try:
            return decode_text(await asyncio.to_thread(storage.get, text_key))
        except Exception as exc:
            log.warning("backfill_offsets.text_unavailable", key=text_key, error=str(exc))
            return None
    return inline


def _normalize(text: str) -> tuple[str, list[int]]:
    """Схлопывает пробельные серии и запоминает исходную позицию каждого символа.

    Возвращает нормализованный текст и карту «индекс в нормализованном →
    индекс в исходном». Карта длиннее текста на один элемент: последний
    указывает на конец, чтобы срез не выходил за границу.
    """
    out: list[str] = []
    positions: list[int] = []
    in_space = False

    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                out.append(" ")
                positions.append(index)
                in_space = True
            continue
        out.append(char)
        positions.append(index)
        in_space = False

    positions.append(len(text))
    return "".join(out), positions


def align(content: str, chunk_text: str, search_from: int = 0) -> tuple[int, int] | None:
    """Находит чанк в тексте документа с точностью до пробелов."""
    if not chunk_text.strip():
        return None

    normal_content, positions = _normalize(content)
    normal_chunk, _ = _normalize(chunk_text)
    normal_chunk = normal_chunk.strip()
    if not normal_chunk:
        return None

    # Позиция начала поиска тоже переводится в нормализованные координаты.
    start_hint = 0
    if search_from > 0:
        start_hint = sum(1 for position in positions[:-1] if position < search_from)

    found = normal_content.find(normal_chunk, start_hint)
    if found == -1 and start_hint > 0:
        # Порядок чанков мог быть нарушен — пробуем с начала, но один раз.
        found = normal_content.find(normal_chunk)
    if found == -1:
        return None

    return positions[found], positions[found + len(normal_chunk)]


async def _backfill_document(
    session: AsyncSession, document_id: int, content: str, dry_run: bool
) -> tuple[int, int]:
    rows = (
        await session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id, DocumentChunk.char_start.is_(None))
            .order_by(DocumentChunk.chunk_index)
        )
    ).all()

    aligned = failed = 0
    cursor = 0
    for row in rows:
        span = align(content, row.text, cursor)
        if span is None:
            failed += 1
            continue
        start, end = span
        # Следующий чанк ищем после начала текущего, а не после конца: соседи
        # намеренно перекрываются на величину overlap.
        cursor = start + 1
        aligned += 1
        if not dry_run:
            await session.execute(
                update(DocumentChunk)
                .where(DocumentChunk.id == row.id)
                .values(char_start=start, char_end=end)
            )

    return aligned, failed


async def backfill(
    session_factory: async_sessionmaker[AsyncSession],
    dry_run: bool,
    storage: ObjectStoragePort | None = None,
) -> Stats:
    stats = Stats()
    last_id = 0

    while True:
        async with session_factory() as session:
            documents = (
                await session.execute(
                    select(
                        DocumentChunk.document_id,
                        DocumentText.text_key,
                        DocumentText.content,
                    )
                    .join(DocumentText, DocumentText.document_id == DocumentChunk.document_id)
                    .where(
                        DocumentChunk.char_start.is_(None),
                        DocumentChunk.document_id > last_id,
                    )
                    .group_by(
                        DocumentChunk.document_id,
                        DocumentText.text_key,
                        DocumentText.content,
                    )
                    .order_by(DocumentChunk.document_id)
                    .limit(DOCUMENT_BATCH)
                )
            ).all()

        if not documents:
            break

        for document_id, text_key, inline in documents:
            content = await _read_text(storage, text_key, inline)
            last_id = document_id
            if content is None:
                # Текст недоступен — выравнивать не по чему. Это не повод
                # обрывать проход: смещения соседей от него не зависят.
                stats.skipped += 1
                continue

            async with session_factory() as session, session.begin():
                aligned, failed = await _backfill_document(session, document_id, content, dry_run)
            stats.documents += 1
            stats.aligned += aligned
            stats.failed += failed

        log.info(
            "backfill_offsets.progress",
            documents=stats.documents,
            aligned=stats.aligned,
            failed=stats.failed,
        )

    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(description="Заполняет char_start/char_end у чанков")
    parser.add_argument("--dry-run", action="store_true", help="Посчитать, но не писать")
    args = parser.parse_args()

    configure_logging("backfill-offsets")
    engine = create_engine(database_settings().async_dsn)
    try:
        stats = await backfill(
            create_session_factory(engine), args.dry_run, MinioObjectStorage(minio_settings())
        )
    finally:
        await engine.dispose()

    log.info(
        "backfill_offsets.done",
        documents=stats.documents,
        aligned=stats.aligned,
        # Не сошлось — это не ошибка прогона: битый OCR выравниванию не поддаётся,
        # и такие чанки остаются без смещений осознанно.
        failed=stats.failed,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())

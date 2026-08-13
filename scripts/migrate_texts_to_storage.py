"""Перенос извлечённых текстов из `document_texts.content` в объектное хранилище.

Второй шаг переезда: миграция 0006 расширила схему, этот скрипт переносит данные,
и только после сверки миграция 0007 убирает `content`. Копировать данные и сносить
источник одной операцией нельзя — при неполном переносе возвращать было бы нечего.

Свойства, без которых перенос сотен тысяч строк бессмыслен:

* **Возобновляемость.** Отбор идёт по `text_key IS NULL`, то есть по факту
  несделанной работы, а не по счётчику. Прерванный прогон продолжается той же
  командой, повторный — не делает ничего.
* **Проверка после записи.** Объект читается обратно и сверяется по хешу до
  того, как в базу попадёт ключ. Строка с ключом означает «текст в хранилище
  точно есть», иначе после сноса `content` осталась бы ссылка в никуда.
* **Дедупликация.** Ключ считается от содержимого, поэтому типовые приложения
  занимают одно место на всех. Уже лежащий объект не перезаписывается.

    python scripts/migrate_texts_to_storage.py --dry-run
    python scripts/migrate_texts_to_storage.py
    python scripts/migrate_texts_to_storage.py --verify
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.shared.config import database_settings, minio_settings
from libs.shared.contracts.ports import ObjectStoragePort
from libs.shared.db.base import create_engine, create_session_factory
from libs.shared.db.schema import DocumentText
from libs.shared.logging import configure_logging, get_logger
from libs.shared.text_objects import (
    TEXT_CONTENT_TYPE,
    decode_text,
    encode_text,
    text_digest,
    text_key,
)
from services.docs_worker.infrastructure.storage.minio_storage import MinioObjectStorage

log = get_logger(__name__)

#: Строк за проход. Тексты крупные, и держать в памяти больше нескольких сотен
#: незачем — узкое место всё равно в хранилище, а не в базе.
BATCH = 200


@dataclass(slots=True)
class Stats:
    seen: int = 0
    written: int = 0
    #: Объект с таким содержимым уже лежал — типовое приложение.
    deduplicated: int = 0
    failed: int = 0


async def _pending(session: AsyncSession, after: int) -> list[tuple[int, str | None]]:
    rows = (
        await session.execute(
            select(DocumentText.document_id, DocumentText.content)
            .where(DocumentText.text_key.is_(None), DocumentText.document_id > after)
            .order_by(DocumentText.document_id)
            .limit(BATCH)
        )
    ).all()
    return [(row.document_id, row.content) for row in rows]


def _store(storage: ObjectStoragePort, content: str) -> tuple[str, str, bool]:
    """Кладёт текст и возвращает (ключ, хеш, был ли он уже там)."""
    digest = text_digest(content)
    key = text_key(digest)

    if storage.exists(key):
        return key, digest, True

    storage.put_bytes(key, encode_text(content), TEXT_CONTENT_TYPE)

    # Читаем обратно: ключ в базе обязан означать, что объект существует и
    # совпадает с тем, что было в `content`. Иначе снос колонки оставит ссылку
    # в никуда, и заметить это будет уже не по чему.
    if text_digest(decode_text(storage.get(key))) != digest:
        raise RuntimeError(f"объект {key} прочитался не тем, чем записан")

    return key, digest, False


async def migrate(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStoragePort,
    dry_run: bool,
) -> Stats:
    stats = Stats()
    after = 0

    while True:
        async with session_factory() as session:
            batch = await _pending(session, after)
        if not batch:
            break

        for document_id, content in batch:
            after = document_id
            stats.seen += 1

            if content is None:
                # Ни ключа, ни текста: документ отмечен как разобранный, но
                # текста у него нет. Переносить нечего, чинить — не здесь.
                stats.failed += 1
                log.warning("migrate_texts.no_content", document_id=document_id)
                continue

            try:
                key, digest, existed = await asyncio.to_thread(_store, storage, content)
            except Exception as exc:
                stats.failed += 1
                log.warning(
                    "migrate_texts.failed", document_id=document_id, error=str(exc)
                )
                continue

            stats.deduplicated += existed
            if dry_run:
                continue

            async with session_factory() as session, session.begin():
                await session.execute(
                    update(DocumentText)
                    .where(DocumentText.document_id == document_id)
                    .values(text_key=key, text_sha256=digest)
                )
            stats.written += 1

        log.info(
            "migrate_texts.progress",
            seen=stats.seen,
            written=stats.written,
            deduplicated=stats.deduplicated,
            failed=stats.failed,
        )

    return stats


async def verify(
    session_factory: async_sessionmaker[AsyncSession], storage: ObjectStoragePort
) -> int:
    """Сверяет, что у каждой перенесённой строки объект на месте и тот самый.

    Запускается перед миграцией 0007: снимать `content` можно только после
    того, как проверено, что читать текст есть откуда.
    """
    broken = 0
    after = 0

    while True:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        DocumentText.document_id,
                        DocumentText.text_key,
                        DocumentText.text_sha256,
                    )
                    .where(
                        DocumentText.text_key.is_not(None),
                        DocumentText.document_id > after,
                    )
                    .order_by(DocumentText.document_id)
                    .limit(BATCH)
                )
            ).all()
        if not rows:
            break

        for row in rows:
            after = row.document_id
            try:
                raw = await asyncio.to_thread(storage.get, row.text_key)
                actual = text_digest(decode_text(raw))
            except Exception as exc:
                broken += 1
                log.error("verify.unreadable", document_id=row.document_id, error=str(exc))
                continue
            if actual != row.text_sha256:
                broken += 1
                log.error("verify.mismatch", document_id=row.document_id, key=row.text_key)

    return broken


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Записать в хранилище, но не в базу")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Только сверка: у каждой перенесённой строки объект на месте",
    )
    args = parser.parse_args()

    configure_logging("migrate-texts")
    engine = create_engine(database_settings().async_dsn)
    storage = MinioObjectStorage(minio_settings())
    storage.ensure_bucket()

    try:
        session_factory = create_session_factory(engine)

        if args.verify:
            broken = await verify(session_factory, storage)
            log.info("verify.done", broken=broken)
            if broken:
                raise SystemExit(f"сверка не прошла: {broken} строк без читаемого текста")
            return

        stats = await migrate(session_factory, storage, args.dry_run)

        async with session_factory() as session:
            left = await session.scalar(
                select(func.count())
                .select_from(DocumentText)
                .where(DocumentText.text_key.is_(None))
            )

        log.info(
            "migrate_texts.done",
            seen=stats.seen,
            written=stats.written,
            deduplicated=stats.deduplicated,
            failed=stats.failed,
            left=left,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

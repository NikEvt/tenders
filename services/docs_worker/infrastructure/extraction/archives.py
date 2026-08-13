"""Распаковка архивов-вложений.

Заказчики регулярно кладут весь комплект документации одним zip/rar. Без распаковки
теряется основная часть ТЗ.
"""

from __future__ import annotations

import io
import zipfile

from libs.shared.logging import get_logger
from services.docs_worker.domain.models import EmbeddedFile, ExtractedText
from services.docs_worker.infrastructure.extraction.base import (
    SIGNATURE_EXTENSIONS,
    ExtensionExtractor,
)

log = get_logger(__name__)

# Защита от zip-бомб: архив на 100 КБ способен развернуться в гигабайты.
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ENTRIES = 500
MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024


def _is_unsafe(name: str) -> bool:
    """Path traversal: `../../etc/passwd` внутри архива."""
    normalized = name.replace("\\", "/")
    return normalized.startswith("/") or ".." in normalized.split("/")


def _is_skippable(name: str) -> bool:
    extension = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    return extension in SIGNATURE_EXTENSIONS


class ZipExtractor(ExtensionExtractor):
    """ZIP: возвращает вложенные файлы, а не текст — их обработают как документы."""

    extensions = frozenset({"zip"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        embedded: list[EmbeddedFile] = []
        total = 0

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist()[:MAX_ENTRIES]:
                if info.is_dir() or _is_unsafe(info.filename) or _is_skippable(info.filename):
                    continue
                if info.file_size > MAX_SINGLE_FILE_BYTES:
                    log.warning("archive.entry_too_large", entry=info.filename)
                    continue
                if total + info.file_size > MAX_UNCOMPRESSED_BYTES:
                    log.warning("archive.size_limit_reached", archive=file_name)
                    break

                try:
                    data = archive.read(info)
                except Exception as exc:
                    log.warning("archive.entry_failed", entry=info.filename, error=str(exc))
                    continue

                total += len(data)
                embedded.append(EmbeddedFile(file_name=info.filename, content=data))

        log.info("archive.unpacked", archive=file_name, files=len(embedded), bytes=total)
        return ExtractedText(pages=[], extractor="zip", embedded_files=embedded)


class SevenZipExtractor(ExtensionExtractor):
    extensions = frozenset({"7z"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        import py7zr

        embedded: list[EmbeddedFile] = []
        total = 0

        with py7zr.SevenZipFile(io.BytesIO(content)) as archive:
            for name, stream in (archive.readall() or {}).items():
                if _is_unsafe(name) or _is_skippable(name) or len(embedded) >= MAX_ENTRIES:
                    continue
                data = stream.read()
                if len(data) > MAX_SINGLE_FILE_BYTES or total + len(data) > MAX_UNCOMPRESSED_BYTES:
                    log.warning("archive.size_limit_reached", archive=file_name)
                    break
                total += len(data)
                embedded.append(EmbeddedFile(file_name=name, content=data))

        return ExtractedText(pages=[], extractor="7z", embedded_files=embedded)


class RarExtractor(ExtensionExtractor):
    extensions = frozenset({"rar"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        import rarfile

        embedded: list[EmbeddedFile] = []
        total = 0

        with rarfile.RarFile(io.BytesIO(content)) as archive:
            for info in archive.infolist()[:MAX_ENTRIES]:
                if info.is_dir() or _is_unsafe(info.filename) or _is_skippable(info.filename):
                    continue
                if info.file_size > MAX_SINGLE_FILE_BYTES:
                    continue
                if total + info.file_size > MAX_UNCOMPRESSED_BYTES:
                    log.warning("archive.size_limit_reached", archive=file_name)
                    break
                data = archive.read(info)
                total += len(data)
                embedded.append(EmbeddedFile(file_name=info.filename, content=data))

        return ExtractedText(pages=[], extractor="rar", embedded_files=embedded)

"""Порты docs-worker."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence

from services.docs_worker.domain.models import (
    Chunk,
    DocumentRef,
    DocumentsStatus,
    ExtractedText,
    ExtractionStatus,
    StoredFile,
)


class AttachmentDownloaderPort(ABC):
    """Скачивание файла вложения из ЕИС."""

    @abstractmethod
    def download(self, url: str) -> tuple[bytes, str | None]:
        """Возвращает содержимое и content-type."""


class TextExtractorPort(ABC):
    """Извлечение текста из файла одного типа (Strategy).

    Новый формат добавляется новой реализацией — существующие не трогаются (OCP).
    """

    #: Расширения, которые берёт на себя эта реализация.
    extensions: frozenset[str] = frozenset()

    @abstractmethod
    def supports(self, file_name: str, content_type: str | None) -> bool: ...

    @abstractmethod
    def extract(self, content: bytes, file_name: str) -> ExtractedText: ...


class TextExtractionPort(ABC):
    """Фасад над набором стратегий: выбирает подходящую и применяет её.

    Use-case зависит только от него и не знает ни о реестре, ни о конкретных
    форматах (ISP: одна операция вместо всего API реестра).
    """

    @abstractmethod
    def extract(
        self, content: bytes, file_name: str, content_type: str | None = None
    ) -> ExtractedText: ...


class ChunkerPort(ABC):
    """Нарезка текста на фрагменты с привязкой к страницам."""

    @abstractmethod
    def split(self, text: ExtractedText) -> list[Chunk]: ...


class DocumentRepositoryPort(ABC):
    """Персистентность документов, текстов и чанков."""

    @abstractmethod
    async def attachments_for_tender(self, tender_id: int) -> list[DocumentRef]:
        """Все вложения закупки, включая разобранные.

        Отбирает не репозиторий, а политика допуска: бюджет веса общий на
        закупку, и решение по одному файлу зависит от остальных.
        """

    @abstractmethod
    async def save_priorities(self, priorities: Mapping[int, int]) -> None:
        """Проставляет порядок разбора всем вложениям закупки разом.

        Всем, а не только тем, что берут в работу: по этому полю обзорный
        проход отбирает «только ТЗ и обоснования» по всей базе, и у документа,
        оставшегося без приоритета, такой запрос его просто не найдёт.
        """

    @abstractmethod
    async def mark_skipped(self, document_id: int, reason: str, final: bool) -> None:
        """Помечает вложение непринятым с указанием причины.

        Причина хранится отдельно от текста ошибки: «не влезло в бюджет» — это
        не сбой, а решение, и в воронке эти два случая должны различаться.

        `final` разделяет отказ навсегда (том архива, подпись) и отложенное до
        следующих настроек. Отложенное остаётся в очереди — иначе обзорный
        проход сделал бы полный невозможным.
        """

    @abstractmethod
    async def get(self, document_id: int) -> DocumentRef | None: ...

    @abstractmethod
    async def mark_status(
        self,
        document_id: int,
        status: ExtractionStatus,
        error: str | None = None,
    ) -> None: ...

    @abstractmethod
    async def save_stored_file(self, document_id: int, stored: StoredFile) -> None: ...

    @abstractmethod
    async def find_extracted_text(self, sha256: str) -> tuple[str, str] | None:
        """Возвращает (`text_key`, `text_sha256`) уже разобранного файла с таким хешем.

        Один и тот же файл — типовой проект контракта, памятка участнику —
        приложен к тысячам извещений. Разбирать его каждый раз заново незачем:
        байты те же, значит и текст тот же.
        """

    @abstractmethod
    async def save_text_and_chunks(
        self,
        ref: DocumentRef,
        text: ExtractedText,
        chunks: Sequence[Chunk],
        text_key: str,
        text_sha256: str,
    ) -> list[int]:
        """Возвращает идентификаторы сохранённых чанков.

        Сам текст к этому моменту уже лежит в объектном хранилище — сюда едет
        только ссылка на него. Чанки, наоборот, сохраняются в базу: на них
        построен полнотекстовый поиск и эмбеддинги.
        """

    @abstractmethod
    async def add_embedded_document(
        self,
        parent: DocumentRef,
        file_name: str,
    ) -> DocumentRef:
        """Заводит запись для файла, извлечённого из архива."""

    @abstractmethod
    async def refresh_tender_status(self, tender_id: int) -> DocumentsStatus:
        """Пересчитывает `tenders.documents_status` по состоянию вложений."""

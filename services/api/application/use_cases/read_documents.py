"""Документы закупки: ссылка на файл и извлечённый текст."""

from __future__ import annotations

import asyncio

from libs.shared.contracts.ports import ObjectStoragePort
from libs.shared.text_objects import decode_text
from services.api.application.errors import NotFound
from services.api.application.ports.documents import DocumentReadPort, FragmentSearchPort
from services.api.domain.documents import (
    ChunkOutline,
    FragmentPage,
    SearchMode,
    TextLocation,
)
from services.api.domain.models import DocumentContent, DownloadLink

# Часа хватает, чтобы открыть файл и вернуться к нему, и мало, чтобы ссылка
# успела разойтись по переписке.
DOWNLOAD_URL_TTL_SECONDS = 3600


class IssueDownloadLinkUseCase:
    """Ссылка на оригинал вложения — в ЕИС, а не в наше хранилище.

    Копий файлов система не держит: она извлекает текст и хранит его, а
    оригинал остаётся там, откуда пришёл. Ссылка постоянная, поэтому
    `expires_in` равен нулю — временем жизни здесь распоряжается ЕИС, и
    придумывать ему срок значило бы сообщать клиенту неправду.
    """

    def __init__(self, documents: DocumentReadPort) -> None:
        self._documents = documents

    async def execute(self, document_id: int) -> DownloadLink:
        found = await self._documents.source(document_id)
        if found is None:
            raise NotFound("Ссылка на файл документа не известна", document_id=document_id)

        url, file_name = found
        return DownloadLink(url=url, file_name=file_name, expires_in=0)


class ReadDocumentTextUseCase:
    """Текст документа — из объектного хранилища, а не из базы.

    Здесь, как и у ссылки на файл, встречаются два порта: реестр знает, где
    лежит текст, хранилище умеет его отдать. Выбор источника — правило чтения,
    поэтому живёт в сценарии, а не в репозитории.
    """

    def __init__(self, documents: DocumentReadPort, storage: ObjectStoragePort) -> None:
        self._documents = documents
        self._storage = storage

    async def execute(self, document_id: int) -> DocumentContent:
        location = await self._documents.text_location(document_id)
        text = await self._resolve(location)
        if text is None:
            # Документ может существовать, но остаться нераспознанным — для
            # клиента это тот же случай «показывать нечего».
            raise NotFound("Текст документа не извлечён", document_id=document_id)
        return DocumentContent(document_id=document_id, content=text, char_count=len(text))

    async def _resolve(self, location: TextLocation | None) -> str | None:
        if location is None:
            return None
        if location.key:
            raw = await asyncio.to_thread(self._storage.get, location.key)
            return decode_text(raw)
        # Документ ещё не перенесён в хранилище — текст лежит в базе.
        return location.inline


class ListDocumentChunksUseCase:
    """Границы чанков: по ним цитата из вердикта резолвится до места в тексте."""

    def __init__(self, documents: DocumentReadPort) -> None:
        self._documents = documents

    async def execute(self, document_id: int) -> list[ChunkOutline]:
        # Пустой список у существующего документа — законный ответ (текст ещё
        # не нарезан), а вот у несуществующего это была бы неправда.
        if not await self._documents.exists(document_id):
            raise NotFound("Документ не найден", document_id=document_id)
        return await self._documents.chunks(document_id)


class SearchFragmentsUseCase:
    def __init__(self, fragments: FragmentSearchPort) -> None:
        self._fragments = fragments

    async def execute(
        self, query: str, mode: SearchMode, page: int, page_size: int
    ) -> FragmentPage:
        return await self._fragments.search(query, mode, page, page_size)

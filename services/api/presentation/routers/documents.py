"""Документы закупки: ссылка на файл и извлечённый текст."""

from __future__ import annotations

from fastapi import APIRouter

from services.api.presentation.deps import DocumentChunks, DocumentText, DownloadLink
from services.api.presentation.schemas import DocumentChunksOut, DownloadOut

router = APIRouter(tags=["Документы"])


@router.get("/documents/{document_id}/download", response_model=DownloadOut)
async def download_document(document_id: int, use_case: DownloadLink) -> DownloadOut:
    """Ссылка на скачивание. Файл идёт из MinIO напрямую, минуя шлюз."""
    return DownloadOut.of(await use_case.execute(document_id))


@router.get("/documents/{document_id}/text")
async def document_text(document_id: int, use_case: DocumentText) -> dict[str, object]:
    content = await use_case.execute(document_id)
    return {
        "document_id": content.document_id,
        "content": content.content,
        "char_count": content.char_count,
    }


@router.get("/documents/{document_id}/chunks", response_model=DocumentChunksOut)
async def document_chunks(document_id: int, use_case: DocumentChunks) -> DocumentChunksOut:
    """Границы фрагментов внутри текста документа.

    По ним `[Показать источник]` в ИИ-вердикте попадает в конкретное место, а не
    просто открывает документ. У чанков, нарезанных до появления смещений,
    `char_start`/`char_end` равны null — подсвечивать там нечего.
    """
    return DocumentChunksOut.of(document_id, await use_case.execute(document_id))

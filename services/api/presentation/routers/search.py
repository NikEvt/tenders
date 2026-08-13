"""Поиск по фрагментам документации."""

from __future__ import annotations

from fastapi import APIRouter, Query

from services.api.domain.documents import SearchMode
from services.api.domain.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from services.api.presentation.deps import SearchFragments
from services.api.presentation.schemas import FragmentPageOut

router = APIRouter(tags=["Поиск"])

# Значение по умолчанию — модульный синглтон: вызов в сигнатуре ruff запрещает.
_MODE = Query(default="rrf", description="lexical | semantic | rrf")


@router.get("/search/fragments", response_model=FragmentPageOut)
async def search_fragments(
    use_case: SearchFragments,
    q: str = Query(min_length=2, description="Запрос по тексту документации"),
    mode: SearchMode = _MODE,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> FragmentPageOut:
    """Единица выдачи — фрагмент, а не закупка.

    Режимы находят разное: лексический берёт точные термины и артикулы,
    векторный — смысл без общих слов, `rrf` объединяет их по рангам. Разложение
    оценок в ответе показывает, какая часть поиска нашла фрагмент.
    """
    return FragmentPageOut.of(await use_case.execute(q, mode, page, page_size))

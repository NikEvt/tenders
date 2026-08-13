"""Порты чтения документов закупки."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.api.domain.documents import ChunkOutline, FragmentPage, SearchMode, TextLocation


class DocumentReadPort(ABC):
    @abstractmethod
    async def source(self, document_id: int) -> tuple[str, str | None] | None:
        """Возвращает (ссылка на файл в ЕИС, имя файла).

        Копии вложений у системы нет: она хранит извлечённый текст, а оригинал
        остаётся в ЕИС. Ссылка ведёт туда же, откуда его качал `docs-worker`.
        """

    @abstractmethod
    async def text_location(self, document_id: int) -> TextLocation | None:
        """Где лежит текст документа: ключ в хранилище или сама строка.

        Два варианта, пока идёт перенос: у перенесённых документов заполнен
        ключ, у ещё не перенесённых — текст в базе. Разбирать это должен
        сценарий, а не репозиторий: выбор источника — правило чтения, а не
        свойство таблицы.
        """

    @abstractmethod
    async def exists(self, document_id: int) -> bool: ...

    @abstractmethod
    async def chunks(self, document_id: int) -> list[ChunkOutline]:
        """Границы чанков — по ним резолвится цитата из вердикта."""


class FragmentSearchPort(ABC):
    """Поиск по фрагментам документации, а не по карточкам закупок."""

    @abstractmethod
    async def search(
        self, query: str, mode: SearchMode, page: int, page_size: int
    ) -> FragmentPage: ...

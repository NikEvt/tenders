"""Доменные понятия сервиса эмбеддингов."""

from __future__ import annotations

from dataclasses import dataclass

# bge-m3 обучен на входах до 8192 токенов, но чанки у нас ~800 —
# запас нужен только для карточки тендера с длинным описанием.
MAX_INPUT_CHARS = 8000

# Асимметричная модель: запрос и документ кодируются по-разному, иначе косинусная
# близость систематически занижается. Для bge-m3 префикс нужен только запросу.
QUERY_PREFIX = ""


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    texts: tuple[str, ...]
    is_query: bool = False

    def truncated(self) -> tuple[str, ...]:
        return tuple(text[:MAX_INPUT_CHARS] for text in self.texts)


@dataclass(frozen=True, slots=True)
class TenderCardText:
    """Текст, из которого строится «карточный» эмбеддинг тендера.

    В карточку идут название, описание и несколько первых чанков документов:
    по одному названию тендеры вроде «Поставка товаров» неотличимы друг от друга.
    """

    tender_id: int
    name: str | None
    description: str | None
    okpd2_names: list[str]
    document_excerpt: str | None

    def render(self) -> str:
        parts = [
            self.name or "",
            self.description or "",
            ", ".join(self.okpd2_names),
            self.document_excerpt or "",
        ]
        return "\n".join(part.strip() for part in parts if part and part.strip())

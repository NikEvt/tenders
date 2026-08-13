"""Доменные модели обработки документов закупки."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Плотность текстового слоя, ниже которой PDF считается сканом и уходит в OCR.
# Осмысленная страница ТЗ содержит сотни символов; 80 отсекает шапки и колонтитулы,
# которые попадают в текстовый слой даже у чистых сканов.
MIN_CHARS_PER_PAGE_FOR_TEXT_LAYER = 80


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    STORED = "stored"
    EXTRACTING = "extracting"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    #: Отложено сегодняшними настройками — бюджетом закупки, потолком размера
    #: или обзорным проходом по приоритету. От `SKIPPED` отличается тем, что
    #: следующий, более щедрый прогон такое вложение подберёт: обзорный проход
    #: не имеет права сделать полный невозможным.
    DEFERRED = "deferred"


class DocumentsStatus(StrEnum):
    """Агрегированное состояние документов тендера."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DocumentRef:
    """Ссылка на подлежащий обработке документ.

    Несёт и метаданные, по которым решается судьба вложения до скачивания:
    размер и вид документа ЕИС отдаёт вместе с извещением, и политика допуска
    работает по ним, не тратя сеть.
    """

    document_id: int
    tender_id: int
    reg_num: str
    attachment_id: str
    file_name: str | None
    source_url: str | None
    nesting_depth: int = 0
    file_size: int | None = None
    doc_kind_name: str | None = None
    #: Разобранное вложение расходует бюджет закупки, но заново не решается.
    processed: bool = False

    @property
    def extension(self) -> str:
        name = (self.file_name or "").lower()
        return name.rsplit(".", 1)[-1] if "." in name else ""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Скачанное вложение в памяти.

    Именно в памяти: сам файл в объектное хранилище не попадает. Наружу от него
    остаются текст (в хранилище) и приметы — хеш, размер, тип, — по которым
    видно, что это был за файл и не приходил ли он уже. Оригинал при
    необходимости берётся из ЕИС по `source_url`.
    """

    sha256: str
    size_bytes: int
    content_type: str | None
    content: bytes


@dataclass(slots=True)
class ExtractedPage:
    number: int
    text: str


@dataclass(slots=True)
class ExtractedText:
    """Результат извлечения.

    Пустой текст — валидный результат (подписанный пустой бланк, картинка без букв),
    а не ошибка: LSP требует, чтобы все экстракторы вели себя одинаково.
    """

    pages: list[ExtractedPage] = field(default_factory=list)
    extractor: str = "unknown"
    ocr_used: bool = False
    lang: str | None = "rus"
    #: Файлы, извлечённые из архива — обрабатываются как самостоятельные документы.
    embedded_files: list[EmbeddedFile] = field(default_factory=list)

    @property
    def content(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def is_empty(self) -> bool:
        return not self.content.strip()

    def looks_like_scan(self) -> bool:
        """Мало текста на страницу — вероятно, скан, стоит попробовать OCR."""
        if not self.pages:
            return False
        return self.char_count / self.page_count < MIN_CHARS_PER_PAGE_FOR_TEXT_LAYER


@dataclass(frozen=True, slots=True)
class EmbeddedFile:
    """Файл из архива-вложения."""

    file_name: str
    content: bytes


@dataclass(frozen=True, slots=True)
class Chunk:
    """Фрагмент документа — единица retrieval для LLM."""

    index: int
    text: str
    page_from: int | None
    page_to: int | None
    # Место чанка в `document_texts.content`: text == content[char_start:char_end].
    # Без этих смещений цитату из вердикта негде подсветить в документе.
    char_start: int | None = None
    char_end: int | None = None

    @property
    def token_estimate(self) -> int:
        # Для русского текста ~3 символа на токен у BPE-токенизаторов —
        # оценка нужна лишь для бюджета контекста, точность здесь не требуется.
        return max(1, len(self.text) // 3)

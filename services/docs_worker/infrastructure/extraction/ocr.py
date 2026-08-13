"""OCR для сканов. Без него часть ТЗ вообще не попадает в поиск и в LLM."""

from __future__ import annotations

from libs.shared.logging import get_logger
from services.docs_worker.application.ports import TextExtractorPort
from services.docs_worker.domain.models import ExtractedPage, ExtractedText
from services.docs_worker.infrastructure.extraction.base import ExtensionExtractor
from services.docs_worker.infrastructure.extraction.documents import normalize

log = get_logger(__name__)

# 300 DPI — рабочий минимум для tesseract на кириллице; ниже растёт доля ошибок,
# выше — время растёт быстрее качества.
OCR_DPI = 300
OCR_SCALE = OCR_DPI / 72  # PDF задан в точках (72/дюйм)

# OCR дорог: без потолка один 800-страничный альбом чертежей займёт воркер на часы.
MAX_OCR_PAGES = 60


class OcrPdfExtractor(ExtensionExtractor):
    """Растеризует страницы PDF и распознаёт их tesseract'ом."""

    extensions = frozenset({"pdf"})

    def __init__(self, languages: str = "rus+eng", max_pages: int = MAX_OCR_PAGES) -> None:
        self._languages = languages
        self._max_pages = max_pages

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        import pypdfium2
        import pytesseract

        pages: list[ExtractedPage] = []
        document = pypdfium2.PdfDocument(content)
        try:
            total = len(document)
            if total > self._max_pages:
                log.info(
                    "ocr.truncated", file_name=file_name, pages=total, limit=self._max_pages
                )

            for number in range(min(total, self._max_pages)):
                page = document[number]
                try:
                    bitmap = page.render(scale=OCR_SCALE)
                    image = bitmap.to_pil()
                    text = pytesseract.image_to_string(image, lang=self._languages)
                    pages.append(ExtractedPage(number=number + 1, text=normalize(text)))
                finally:
                    page.close()
        finally:
            document.close()

        return ExtractedText(pages=pages, extractor="tesseract", ocr_used=True)


class OcrImageExtractor(ExtensionExtractor):
    """Отдельные картинки-сканы, которые заказчики прикладывают вместо PDF."""

    extensions = frozenset({"png", "jpg", "jpeg", "tif", "tiff", "bmp"})

    def __init__(self, languages: str = "rus+eng") -> None:
        self._languages = languages

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        import io

        import pytesseract
        from PIL import Image

        image = Image.open(io.BytesIO(content))
        text = normalize(pytesseract.image_to_string(image, lang=self._languages))
        return ExtractedText(
            pages=[ExtractedPage(number=1, text=text)] if text else [],
            extractor="tesseract",
            ocr_used=True,
        )


class PdfWithOcrFallback(TextExtractorPort):
    """PDF: сначала текстовый слой, при его отсутствии — OCR.

    Decorator над двумя экстракторами: вызывающий код про существование OCR не знает.
    """

    extensions = frozenset({"pdf"})

    def __init__(self, text_extractor: TextExtractorPort, ocr_extractor: TextExtractorPort) -> None:
        self._text = text_extractor
        self._ocr = ocr_extractor

    def supports(self, file_name: str, content_type: str | None) -> bool:
        return self._text.supports(file_name, content_type)

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        extracted = self._text.extract(content, file_name)
        if not extracted.looks_like_scan():
            return extracted

        log.info(
            "ocr.fallback",
            file_name=file_name,
            chars=extracted.char_count,
            pages=extracted.page_count,
        )
        try:
            recognized = self._ocr.extract(content, file_name)
        except Exception as exc:
            log.warning("ocr.failed", file_name=file_name, error=str(exc))
            return extracted

        # OCR мог дать меньше текста, чем слабый текстовый слой, — берём лучшее.
        return recognized if recognized.char_count > extracted.char_count else extracted

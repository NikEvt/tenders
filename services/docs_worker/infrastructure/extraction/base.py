"""Общая основа экстракторов и реестр выбора по типу файла."""

from __future__ import annotations

from libs.shared.logging import get_logger
from services.docs_worker.application.ports import TextExtractionPort, TextExtractorPort
from services.docs_worker.domain.models import ExtractedText

log = get_logger(__name__)

# Файлы крупнее этого не извлекаем: один 500-мегабайтный чертёж способен выесть
# память воркера, а полезного текста в нём нет.
MAX_EXTRACTABLE_BYTES = 200 * 1024 * 1024

# Открепленные подписи и сертификаты — не документы.
SIGNATURE_EXTENSIONS = frozenset({"sig", "p7s", "sgn", "cer", "crt", "der"})


class ExtensionExtractor(TextExtractorPort):
    """Базовая реализация выбора по расширению имени файла.

    Content-type ЕИС отдаёт ненадёжно (сплошь `application/octet-stream`),
    поэтому основной признак — расширение.
    """

    def supports(self, file_name: str, content_type: str | None) -> bool:
        name = (file_name or "").lower()
        extension = name.rsplit(".", 1)[-1] if "." in name else ""
        return extension in self.extensions


class SkippedExtractor(ExtensionExtractor):
    """Явно пропускаемые типы: криптоподписи, сертификаты."""

    extensions = SIGNATURE_EXTENSIONS

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        return ExtractedText(pages=[], extractor="skipped")


class ExtractorRegistry(TextExtractionPort):
    """Выбирает подходящий экстрактор.

    Порядок важен: первый подошедший выигрывает, поэтому специализированные
    реализации регистрируются раньше общих.
    """

    def __init__(self, extractors: list[TextExtractorPort]) -> None:
        self._extractors = extractors

    def find(self, file_name: str, content_type: str | None) -> TextExtractorPort | None:
        for extractor in self._extractors:
            if extractor.supports(file_name, content_type):
                return extractor
        return None

    def extract(
        self, content: bytes, file_name: str, content_type: str | None = None
    ) -> ExtractedText:
        if len(content) > MAX_EXTRACTABLE_BYTES:
            log.warning("extract.too_large", file_name=file_name, size=len(content))
            return ExtractedText(pages=[], extractor="too_large")

        extractor = self.find(file_name, content_type)
        if extractor is None:
            log.info("extract.unsupported", file_name=file_name)
            return ExtractedText(pages=[], extractor="unsupported")

        try:
            return extractor.extract(content, file_name)
        except Exception as exc:
            # Один нечитаемый файл не должен ронять обработку остальных вложений.
            log.warning(
                "extract.failed",
                file_name=file_name,
                extractor=type(extractor).__name__,
                error=str(exc),
            )
            return ExtractedText(pages=[], extractor="failed")

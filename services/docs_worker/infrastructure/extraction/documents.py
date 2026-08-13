"""Экстракторы офисных форматов и PDF."""

from __future__ import annotations

import io
import re
import subprocess
import tempfile
from pathlib import Path

from libs.shared.logging import get_logger
from services.docs_worker.domain.models import ExtractedPage, ExtractedText
from services.docs_worker.infrastructure.extraction.base import ExtensionExtractor

log = get_logger(__name__)

# Ячейки XLSX: сплошная таблица без разделителей нечитаема и для LLM, и для поиска.
_CELL_SEPARATOR = " | "
_WHITESPACE = re.compile(r"[ \t\xa0]+")


def normalize(text: str) -> str:
    """Схлопывает пробелы и переносы, не трогая границы абзацев."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


class PdfExtractor(ExtensionExtractor):
    """Текстовый слой PDF. Сканы отдаются наверх с пометкой — их добирает OCR."""

    extensions = frozenset({"pdf"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        import pypdfium2

        pages: list[ExtractedPage] = []
        document = pypdfium2.PdfDocument(content)
        try:
            for number, page in enumerate(document, start=1):
                textpage = page.get_textpage()
                try:
                    text = normalize(textpage.get_text_range())
                    pages.append(ExtractedPage(number=number, text=text))
                finally:
                    textpage.close()
                    page.close()
        finally:
            document.close()

        return ExtractedText(pages=pages, extractor="pdfium")


class DocxExtractor(ExtensionExtractor):
    """DOCX: абзацы и таблицы. Таблицы в ТЗ несут ключевые требования."""

    extensions = frozenset({"docx"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        import docx

        document = docx.Document(io.BytesIO(content))
        blocks = [p.text for p in document.paragraphs if p.text.strip()]

        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    blocks.append(_CELL_SEPARATOR.join(cells))

        text = normalize("\n".join(blocks))
        return ExtractedText(
            pages=[ExtractedPage(number=1, text=text)] if text else [],
            extractor="docx",
        )


class XlsxExtractor(ExtensionExtractor):
    """XLSX: каждый лист — отдельная «страница», чтобы чанки не смешивали сметы."""

    extensions = frozenset({"xlsx", "xlsm"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        import openpyxl

        workbook = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True
        )
        try:
            pages: list[ExtractedPage] = []
            for number, sheet in enumerate(workbook.worksheets, start=1):
                rows: list[str] = []
                for row in sheet.iter_rows(values_only=True):
                    cells = [str(value).strip() for value in row if value not in (None, "")]
                    if cells:
                        rows.append(_CELL_SEPARATOR.join(cells))
                if rows:
                    pages.append(
                        ExtractedPage(
                            number=number,
                            text=normalize(f"Лист: {sheet.title}\n" + "\n".join(rows)),
                        )
                    )
            return ExtractedText(pages=pages, extractor="xlsx")
        finally:
            workbook.close()


class RtfExtractor(ExtensionExtractor):
    extensions = frozenset({"rtf"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        from striprtf.striprtf import rtf_to_text

        # RTF из российских СЭД часто в CP1251, а не в UTF-8.
        raw = content.decode("utf-8", errors="ignore")
        if raw.count("\\'") > 20:
            raw = content.decode("cp1251", errors="ignore")

        text = normalize(rtf_to_text(raw, errors="ignore"))
        return ExtractedText(
            pages=[ExtractedPage(number=1, text=text)] if text else [], extractor="rtf"
        )


class PlainTextExtractor(ExtensionExtractor):
    extensions = frozenset({"txt", "csv", "xml", "json", "md", "html", "htm"})

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        for encoding in ("utf-8", "cp1251", "utf-16"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content.decode("utf-8", errors="replace")

        if file_name.lower().endswith((".html", ".htm", ".xml")):
            text = re.sub(r"<[^>]+>", " ", text)

        text = normalize(text)
        return ExtractedText(
            pages=[ExtractedPage(number=1, text=text)] if text else [], extractor="plain"
        )


class LegacyOfficeExtractor(ExtensionExtractor):
    """Старые .doc/.xls/.ppt через headless LibreOffice.

    Чистых Python-библиотек для этих форматов, которые переваривали бы реальные
    файлы из СЭД заказчиков, нет. Конвертация идёт во временном каталоге и
    ограничена по времени — LibreOffice умеет зависать на битых файлах.
    """

    extensions = frozenset({"doc", "xls", "ppt", "odt", "ods"})
    CONVERT_TIMEOUT_SECONDS = 120

    def __init__(self, soffice: str = "soffice") -> None:
        self._soffice = soffice

    def extract(self, content: bytes, file_name: str) -> ExtractedText:
        suffix = Path(file_name).suffix or ".doc"
        target = "csv" if suffix.lower() in {".xls", ".ods"} else "txt:Text (encoded):UTF8"

        with tempfile.TemporaryDirectory() as workdir:
            source = Path(workdir) / f"input{suffix}"
            source.write_bytes(content)

            try:
                subprocess.run(
                    [
                        self._soffice,
                        "--headless",
                        "--norestore",
                        f"-env:UserInstallation=file://{workdir}/profile",
                        "--convert-to",
                        target,
                        "--outdir",
                        workdir,
                        str(source),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=self.CONVERT_TIMEOUT_SECONDS,
                )
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
            ) as exc:
                log.warning("legacy_office.convert_failed", file_name=file_name, error=str(exc))
                return ExtractedText(pages=[], extractor="libreoffice_failed")

            converted = [p for p in Path(workdir).iterdir() if p.suffix in {".txt", ".csv"}]
            if not converted:
                return ExtractedText(pages=[], extractor="libreoffice_empty")

            text = normalize(converted[0].read_text(encoding="utf-8", errors="replace"))

        return ExtractedText(
            pages=[ExtractedPage(number=1, text=text)] if text else [],
            extractor="libreoffice",
        )

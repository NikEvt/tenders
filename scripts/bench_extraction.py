"""Замер пропускной способности извлечения текста.

Ретроспектива прогона ХПК/БПК: переход с пула потоков на пул процессов дал
0.6 → 13 файл/с, в двадцать раз. Причина — `pypdfium2` не потокобезопасен, и
параллельные PDF под GIL либо сериализуются, либо роняют процесс нативным
сигналом без traceback.

Скрипт меряет то же самое на синтетическом наборе, чтобы «стало быстрее» было
числом, а не впечатлением. Набор синтетический намеренно: настоящие вложения
ЕИС в репозиторий не положишь, а для сравнения режимов между собой важна
воспроизводимость, а не реалистичность.

    python scripts/bench_extraction.py --mode sequential --docs 60
    python scripts/bench_extraction.py --mode threads --workers 8
"""

from __future__ import annotations

import argparse
import io
import time
from concurrent.futures import ThreadPoolExecutor

from services.docs_worker.bootstrap import build_extraction
from services.docs_worker.infrastructure.extraction.pool import ProcessPoolExtraction

#: Абзац с лексикой, характерной для документации по качеству воды: замер должен
#: гонять экстракторы по тексту, похожему на настоящий, а не по «lorem ipsum».
PARAGRAPH = (
    "Определение химического потребления кислорода в пробах сточных вод "
    "по методике ПНД Ф 14.1:2.100-97, диапазон измерений от 5 до 800 мг/дм3. "
    "Контроль показателей БПК5 и взвешенных веществ согласно СанПиН 1.2.3685-21. "
)


#: Тот же абзац латиницей. Встроенных шрифтов с кириллицей в собранном вручную
#: PDF нет, а замеряется скорость разбора, а не качество кодировки.
PARAGRAPH_LATIN = (
    "Opredelenie himicheskogo potrebleniya kisloroda v probah stochnyh vod "
    "po metodike PND F 14.1:2.100-97, diapazon izmerenij ot 5 do 800 mg/dm3. "
)


def make_pdf(pages: int) -> bytes:
    """PDF с настоящим текстовым слоем, собранный вручную.

    `pypdfium2` умеет создавать только пустые страницы, а пустая страница — это
    скан с точки зрения `looks_like_scan()`: она уходит в OCR и замеряет совсем
    другой тракт. Текстовый слой нужен, чтобы мерить именно разбор PDF.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    for page in range(pages):
        lines = b"\n".join(
            b"("
            + f"{page + 1}.{line} {PARAGRAPH_LATIN}".encode("ascii", "replace")
            .replace(b"\\", b"")
            .replace(b"(", b"")
            .replace(b")", b"")
            + b") Tj 0 -14 Td"
            for line in range(40)
        )
        stream = b"BT /F1 11 Tf 40 800 Td\n" + lines + b"\nET"
        contents = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(
            add(
                b"<< /Type /Page /Parent 999 0 R /MediaBox [0 0 595 842] "
                b"/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>"
                % (contents, font)
            )
        )

    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    pages_id = add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids)))
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    # Ссылку на родителя проставляем задним числом: номер объекта /Pages
    # становится известен только после того, как созданы все страницы.
    parent = b"/Parent %d 0 R" % pages_id
    objects[:] = [body.replace(b"/Parent 999 0 R", parent) for body in objects]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)

    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets[1:]:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref_at,
    )
    return bytes(out)


def make_docx(paragraphs: int) -> bytes:
    import docx

    document = docx.Document()
    for index in range(paragraphs):
        document.add_paragraph(f"{index}. {PARAGRAPH}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_xlsx(rows: int) -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for index in range(rows):
        sheet.append([index, PARAGRAPH, index * 3.14])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_corpus(count: int, weight: int = 1) -> list[tuple[bytes, str]]:
    """Смесь форматов в пропорции, близкой к вложениям ЕИС.

    PDF преобладает — именно он и есть узкое место, и именно он не терпит
    параллельного доступа из потоков.

    `weight` задаёт «тяжесть» документа. Он важнее, чем кажется: на документах
    по 10 мс пул процессов **медленнее** последовательного разбора, потому что
    запуск процессов и копирование содержимого через pickle стоят дороже самой
    работы. Настоящее вложение ЕИС — это десятки страниц и сотни миллисекунд
    разбора, и выигрыш появляется только на такой единице работы. Замер на
    игрушечных документах ответил бы на вопрос, которого никто не задавал.
    """
    corpus: list[tuple[bytes, str]] = []
    for index in range(count):
        slot = index % 5
        if slot < 3:
            corpus.append((make_pdf(pages=8 * weight), f"тз-{index}.pdf"))
        elif slot == 3:
            corpus.append((make_docx(paragraphs=120 * weight), f"обоснование-{index}.docx"))
        else:
            corpus.append((make_xlsx(rows=400 * weight), f"смета-{index}.xlsx"))
    return corpus


def run_sequential(corpus: list[tuple[bytes, str]]) -> int:
    extraction = build_extraction()
    return sum(extraction.extract(data, name, None).char_count for data, name in corpus)


def run_threads(corpus: list[tuple[bytes, str]], workers: int) -> int:
    """Прежняя форма продакшена: `asyncio.to_thread` поверх общего реестра.

    Ожидаемо падает нативным сигналом на двух и более потоках — ради этого
    режим и сохранён.
    """
    extraction = build_extraction()
    with ThreadPoolExecutor(workers) as pool:
        results = pool.map(lambda item: extraction.extract(item[0], item[1], None), corpus)
        return sum(result.char_count for result in results)


def run_processes(corpus: list[tuple[bytes, str]], workers: int) -> int:
    """Новая форма: тот же порт, но разбор в отдельных процессах."""
    extraction = ProcessPoolExtraction(workers=workers)
    try:
        # Вызовы из потоков — так их делает сценарий через `asyncio.to_thread`.
        with ThreadPoolExecutor(workers) as threads:
            results = threads.map(
                lambda item: extraction.extract(item[0], item[1], None), corpus
            )
            return sum(result.char_count for result in results)
    finally:
        extraction.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("sequential", "threads", "processes"), default="processes"
    )
    parser.add_argument("--docs", type=int, default=60)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--weight",
        type=int,
        default=1,
        help="тяжесть документа: 1 — игрушечный, 10 — близко к вложению ЕИС",
    )
    args = parser.parse_args()

    print(f"готовим {args.docs} документов…", flush=True)
    corpus = build_corpus(args.docs, args.weight)
    volume = sum(len(data) for data, _ in corpus)

    started = time.monotonic()
    if args.mode == "sequential":
        chars = run_sequential(corpus)
    elif args.mode == "threads":
        chars = run_threads(corpus, args.workers)
    else:
        chars = run_processes(corpus, args.workers)
    elapsed = time.monotonic() - started

    workers = 1 if args.mode == "sequential" else args.workers
    print(
        f"режим {args.mode} (воркеров {workers}): "
        f"{len(corpus)} док. за {elapsed:.1f} с — "
        f"{len(corpus) / elapsed:.2f} файл/с, "
        f"{volume / elapsed / 1e6:.1f} МБ/с, символов {chars}"
    )


if __name__ == "__main__":
    main()

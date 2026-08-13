"""Пайплайн документов целиком: скачать → сохранить → извлечь → нарезать."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence

import pytest
from sqlalchemy import delete, func, select

from libs.shared.contracts.events import (
    DocumentExtracted,
    EmbeddingRequested,
    Event,
    TenderEnriched,
    TenderIngested,
)
from libs.shared.contracts.ports import EventPublisher, ObjectStoragePort
from libs.shared.db.schema import DocumentChunk, DocumentText, Tender, TenderDocument
from services.docs_worker.application.use_cases.process_documents import (
    ProcessTenderDocumentsUseCase,
)
from services.docs_worker.domain.admission import AdmissionPolicy
from services.docs_worker.domain.models import DocumentsStatus, ExtractionStatus
from services.docs_worker.infrastructure.chunking import RecursiveChunker
from services.docs_worker.infrastructure.db.document_repository import SqlDocumentRepository
from services.docs_worker.infrastructure.extraction.archives import ZipExtractor
from services.docs_worker.infrastructure.extraction.base import ExtractorRegistry, SkippedExtractor
from services.docs_worker.infrastructure.extraction.documents import PlainTextExtractor

REG_NUM = "TEST-DOCS-0000000001"


class InMemoryStorage(ObjectStoragePort):
    """MinIO здесь не проверяется — только оркестрация. Хранилище своё, в памяти."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key, data, size, content_type=None) -> None:
        self.objects[key] = data.read()

    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> None:
        self.objects[key] = content

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def exists(self, key: str) -> bool:
        return key in self.objects

    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        return f"memory://{key}"


class RecordingPublisher(EventPublisher):
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)

    async def publish_many(self, events: Sequence[Event]) -> None:
        self.events.extend(events)

    def of(self, event_type: type[Event]) -> list[Event]:
        return [e for e in self.events if isinstance(e, event_type)]


class StubDownloader:
    """Отдаёт заранее заданное содержимое по URL и считает обращения."""

    def __init__(self, files: dict[str, bytes], failing: set[str] | None = None) -> None:
        self._files = files
        self._failing = failing or set()
        self.calls: list[str] = []

    def download(self, url: str) -> tuple[bytes, str | None]:
        self.calls.append(url)
        if url in self._failing:
            raise RuntimeError("сеть ЕИС недоступна")
        return self._files[url], "application/octet-stream"


def build_extraction() -> ExtractorRegistry:
    return ExtractorRegistry([SkippedExtractor(), ZipExtractor(), PlainTextExtractor()])


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
async def tender_with_attachments(session_factory):
    """Создаёт тендер с вложениями и убирает их за собой."""

    async def create(attachments: list[dict]) -> int:
        async with session_factory() as session, session.begin():
            tender_id = await session.scalar(
                Tender.__table__.insert()
                .values(reg_num=REG_NUM, name="Поставка газа", law_type="44-FZ")
                .returning(Tender.id)
            )
            for attachment in attachments:
                await session.execute(
                    TenderDocument.__table__.insert().values(tender_id=tender_id, **attachment)
                )
        return tender_id

    created: list[int] = []

    async def factory(attachments: list[dict]) -> int:
        tender_id = await create(attachments)
        created.append(tender_id)
        return tender_id

    yield factory

    async with session_factory() as session, session.begin():
        for tender_id in created:
            await session.execute(delete(Tender).where(Tender.id == tender_id))


def build_use_case(session_factory, downloader, storage, publisher, admission=None):
    return ProcessTenderDocumentsUseCase(
        repository=SqlDocumentRepository(session_factory),
        downloader=downloader,
        storage=storage,
        extraction=build_extraction(),
        chunker=RecursiveChunker(chunk_chars=200, overlap_chars=20),
        publisher=publisher,
        admission=admission,
    )


class CountingDownloader:
    """Загрузчик, который помнит, к чему его вообще просили обратиться.

    Политика допуска обязана отсекать **до** скачивания, и проверить это можно
    только так: не по итоговому статусу документа, а по тому, что сети не
    коснулись.
    """

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self._bodies = bodies
        self.requested: list[str] = []

    def download(self, url: str) -> tuple[bytes, str | None]:
        self.requested.append(url)
        if url not in self._bodies:
            raise AssertionError(f"скачивание {url} не должно было случиться")
        return self._bodies[url], None


@pytest.mark.asyncio
async def test_happy_path_stores_extracts_and_chunks(
    session_factory, tender_with_attachments
) -> None:
    url = "https://zakupki.gov.ru/file?uid=AAA"
    body = ("Поставщик обязан поставить кислород технический в баллонах. " * 20).encode()

    tender_id = await tender_with_attachments(
        [{"attachment_id": "AAA", "file_name": "ТЗ.txt", "source_url": url}]
    )

    storage = InMemoryStorage()
    publisher = RecordingPublisher()
    use_case = build_use_case(session_factory, StubDownloader({url: body}), storage, publisher)

    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=1)
    )

    async with session_factory() as session:
        document = await session.scalar(
            select(TenderDocument).where(TenderDocument.tender_id == tender_id)
        )
        assert document.extraction_status == ExtractionStatus.DONE.value
        # Копия файла не хранится: у документа остаются приметы и ссылка в ЕИС.
        assert document.minio_key is None
        assert document.sha256 is not None

        text = await session.scalar(
            select(DocumentText).where(DocumentText.document_id == document.id)
        )
        # В базе — только ключ; сам текст лежит в объектном хранилище.
        assert text.content is None
        assert text.text_key in storage.objects
        assert "кислород технический" in storage.objects[text.text_key].decode()

        chunk_count = await session.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.document_id == document.id
            )
        )
        assert chunk_count > 1

        tender = await session.scalar(select(Tender).where(Tender.id == tender_id))
        assert tender.documents_status == DocumentsStatus.DONE.value

    assert len(publisher.of(DocumentExtracted)) == 1
    assert len(publisher.of(EmbeddingRequested)) == 1
    assert publisher.of(TenderEnriched)[0].documents_status == "done"


@pytest.mark.asyncio
async def test_one_failed_attachment_does_not_block_the_others(
    session_factory, tender_with_attachments
) -> None:
    good_url = "https://zakupki.gov.ru/file?uid=GOOD"
    bad_url = "https://zakupki.gov.ru/file?uid=BAD"

    tender_id = await tender_with_attachments(
        [
            {"attachment_id": "GOOD", "file_name": "ТЗ.txt", "source_url": good_url},
            {"attachment_id": "BAD", "file_name": "Смета.txt", "source_url": bad_url},
        ]
    )

    downloader = StubDownloader({good_url: "Поставка газа.".encode()}, failing={bad_url})
    publisher = RecordingPublisher()
    use_case = build_use_case(session_factory, downloader, InMemoryStorage(), publisher)

    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=2)
    )

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(TenderDocument).where(TenderDocument.tender_id == tender_id)
            )
        ).all()
        by_id = {r.attachment_id: r for r in rows}
        assert by_id["GOOD"].extraction_status == ExtractionStatus.DONE.value
        assert by_id["BAD"].extraction_status == ExtractionStatus.FAILED.value

        tender = await session.scalar(select(Tender).where(Tender.id == tender_id))
        assert tender.documents_status == DocumentsStatus.PARTIAL.value

    assert publisher.of(TenderEnriched)[0].documents_status == "partial"


@pytest.mark.asyncio
async def test_archive_is_unpacked_into_child_documents(
    session_factory, tender_with_attachments
) -> None:
    url = "https://zakupki.gov.ru/file?uid=ZIP"
    archive = make_zip(
        {
            "ТЗ.txt": "Поставка кислорода в баллонах объёмом 40 литров.".encode(),
            "Смета.txt": "Итого 950000 рублей.".encode(),
            "подпись.sig": b"\x00",
        }
    )

    tender_id = await tender_with_attachments(
        [{"attachment_id": "ZIP", "file_name": "Комплект.zip", "source_url": url}]
    )

    publisher = RecordingPublisher()
    storage = InMemoryStorage()
    use_case = build_use_case(
        session_factory, StubDownloader({url: archive}), storage, publisher
    )

    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=1)
    )

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(TenderDocument).where(TenderDocument.tender_id == tender_id)
            )
        ).all()
        children = [r for r in rows if r.parent_document_id is not None]

        assert {r.file_name for r in children} == {"ТЗ.txt", "Смета.txt"}
        assert all(r.nesting_depth == 1 for r in children)
        assert all(r.extraction_status == ExtractionStatus.DONE.value for r in children)

        keys = (
            await session.scalars(
                select(DocumentText.text_key).where(DocumentText.tender_id == tender_id)
            )
        ).all()
        texts = [storage.objects[key].decode() for key in keys]
        assert any("кислорода" in t for t in texts)
        assert any("950000" in t for t in texts)


@pytest.mark.asyncio
async def test_identical_file_is_stored_once(session_factory, tender_with_attachments) -> None:
    """Типовые документы приложены к тысячам извещений — дублировать их в MinIO незачем."""
    url_a = "https://zakupki.gov.ru/file?uid=A"
    url_b = "https://zakupki.gov.ru/file?uid=B"
    body = "Памятка участнику закупки.".encode()

    tender_id = await tender_with_attachments(
        [
            {"attachment_id": "A", "file_name": "Памятка.txt", "source_url": url_a},
            {"attachment_id": "B", "file_name": "Памятка копия.txt", "source_url": url_b},
        ]
    )

    storage = InMemoryStorage()
    use_case = build_use_case(
        session_factory,
        StubDownloader({url_a: body, url_b: body}),
        storage,
        RecordingPublisher(),
    )

    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=2)
    )

    assert len(storage.objects) == 1, "одинаковый текст должен храниться одним объектом"

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(DocumentText.text_key, DocumentText.text_sha256).where(
                    DocumentText.tender_id == tender_id
                )
            )
        ).all()

        # Два документа, один объект: ключ считается от содержимого текста.
        assert len(rows) == 2
        assert len({row.text_key for row in rows}) == 1
        assert len({row.text_sha256 for row in rows}) == 1
        assert rows[0].text_key in storage.objects


@pytest.mark.asyncio
async def test_identical_file_is_extracted_once(
    session_factory, tender_with_attachments
) -> None:
    """Второй такой же файл текст переиспользует, а не разбирается заново.

    Экономится самое дорогое — OCR скана и запуск LibreOffice. Проверяется по
    экстрактору: у переиспользованного документа он `reused`, а не `plain`.
    """
    url_a = "https://zakupki.gov.ru/file?uid=SAME-A"
    url_b = "https://zakupki.gov.ru/file?uid=SAME-B"
    body = "Типовой проект контракта. Раздел 1.".encode()

    tender_id = await tender_with_attachments(
        [
            {"attachment_id": "SA", "file_name": "Проект.txt", "source_url": url_a},
            {"attachment_id": "SB", "file_name": "Проект (копия).txt", "source_url": url_b},
        ]
    )

    use_case = build_use_case(
        session_factory,
        StubDownloader({url_a: body, url_b: body}),
        InMemoryStorage(),
        RecordingPublisher(),
    )
    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=2)
    )

    async with session_factory() as session:
        extractors = (
            await session.scalars(
                select(DocumentText.extractor).where(DocumentText.tender_id == tender_id)
            )
        ).all()

    assert sorted(extractors) == ["plain", "reused"]


@pytest.mark.asyncio
async def test_rerun_skips_already_processed_documents(
    session_factory, tender_with_attachments
) -> None:
    url = "https://zakupki.gov.ru/file?uid=ONCE"
    tender_id = await tender_with_attachments(
        [{"attachment_id": "ONCE", "file_name": "ТЗ.txt", "source_url": url}]
    )

    downloader = StubDownloader({url: "Поставка газа.".encode()})
    use_case = build_use_case(
        session_factory, downloader, InMemoryStorage(), RecordingPublisher()
    )
    event = TenderIngested(
        tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=1
    )

    await use_case.execute(event)
    await use_case.execute(event)

    assert len(downloader.calls) == 1, "обработанный документ не должен качаться повторно"


@pytest.mark.asyncio
async def test_tender_without_attachments_is_marked_done(
    session_factory, tender_with_attachments
) -> None:
    tender_id = await tender_with_attachments([])

    publisher = RecordingPublisher()
    use_case = build_use_case(
        session_factory, StubDownloader({}), InMemoryStorage(), publisher
    )

    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=0)
    )

    async with session_factory() as session:
        tender = await session.scalar(select(Tender).where(Tender.id == tender_id))
        assert tender.documents_status == DocumentsStatus.DONE.value

    # Эмбеддинг карточки нужен даже без вложений, иначе тендер выпадет из поиска.
    assert len(publisher.of(EmbeddingRequested)) == 1


# ─── Политика допуска ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multivolume_archive_is_never_downloaded(
    session_factory, tender_with_attachments
) -> None:
    """Четыре закупки в прогоне принесли 84 ГБ томами по 50 МБ.

    Каждый том аккуратно под лимитом на файл, и распаковать его отдельно нельзя:
    `rarfile` требует все тома сразу. Поэтому тома обязаны отсекаться по имени
    и до обращения к сети.
    """
    tz_url = "https://zakupki.gov.ru/file?uid=TZ"
    attachments = [
        {
            "attachment_id": f"V{i}",
            "file_name": f"Проектная документация.part{i:03d}.rar",
            "source_url": f"https://zakupki.gov.ru/file?uid=V{i}",
            "file_size": 50 * 1024 * 1024,
        }
        for i in range(1, 21)
    ]
    attachments.append(
        {
            "attachment_id": "TZ",
            "file_name": "Техническое задание.txt",
            "source_url": tz_url,
            "file_size": 1024,
        }
    )
    tender_id = await tender_with_attachments(attachments)

    downloader = CountingDownloader({tz_url: "Определение ХПК в стоках.".encode()})
    use_case = build_use_case(
        session_factory, downloader, InMemoryStorage(), RecordingPublisher()
    )
    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=21)
    )

    # Сети коснулись ровно один раз — ради ТЗ.
    assert downloader.requested == [tz_url]

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(TenderDocument.file_name, TenderDocument.skip_reason).where(
                    TenderDocument.tender_id == tender_id
                )
            )
        ).all()

    skipped = {r.file_name: r.skip_reason for r in rows if r.skip_reason}
    assert len(skipped) == 20
    assert set(skipped.values()) == {"multivolume"}


@pytest.mark.asyncio
async def test_budget_is_spent_on_the_valuable_documents_first(
    session_factory, tender_with_attachments
) -> None:
    """ТЗ и обоснование проходят, тяжёлый хвост обрезается бюджетом закупки."""
    tz_url = "https://zakupki.gov.ru/file?uid=B-TZ"
    nmck_url = "https://zakupki.gov.ru/file?uid=B-NMCK"

    tender_id = await tender_with_attachments(
        [
            {
                "attachment_id": "ALBUM",
                "file_name": "Альбом чертежей.txt",
                "source_url": "https://zakupki.gov.ru/file?uid=B-ALBUM",
                "file_size": 25 * 1024 * 1024,
            },
            {
                "attachment_id": "TZ",
                "file_name": "Техническое задание.txt",
                "source_url": tz_url,
                "file_size": 10 * 1024 * 1024,
            },
            {
                "attachment_id": "NMCK",
                "file_name": "Обоснование НМЦК.txt",
                "source_url": nmck_url,
                "file_size": 10 * 1024 * 1024,
            },
        ]
    )

    downloader = CountingDownloader(
        {tz_url: "Требования к ХПК.".encode(), nmck_url: "Расчёт цены.".encode()}
    )
    use_case = build_use_case(
        session_factory,
        downloader,
        InMemoryStorage(),
        RecordingPublisher(),
        admission=AdmissionPolicy(max_tender_bytes=30 * 1024 * 1024),
    )
    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=3)
    )

    assert sorted(downloader.requested) == sorted([tz_url, nmck_url])

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    TenderDocument.attachment_id,
                    TenderDocument.priority,
                    TenderDocument.skip_reason,
                ).where(TenderDocument.tender_id == tender_id)
            )
        ).all()

    by_id = {r.attachment_id: r for r in rows}
    assert by_id["TZ"].priority == 0
    assert by_id["NMCK"].priority == 1
    assert by_id["ALBUM"].skip_reason == "tender_budget"


@pytest.mark.asyncio
async def test_resumed_run_does_not_grant_a_fresh_budget(
    session_factory, tender_with_attachments
) -> None:
    """Уже разобранное продолжает занимать бюджет.

    Иначе перезапуск обнулял бы счёт, и лимит на закупку становился бы
    декоративным — именно так он однажды и не сработал.
    """
    url = "https://zakupki.gov.ru/file?uid=R-APP"
    tender_id = await tender_with_attachments(
        [
            {
                "attachment_id": "BIG",
                "file_name": "Техническое задание.txt",
                "source_url": "https://zakupki.gov.ru/file?uid=R-BIG",
                "file_size": 28 * 1024 * 1024,
                # Разобрано в прошлый прогон.
                "extraction_status": "done",
            },
            {
                "attachment_id": "APP",
                "file_name": "Приложение.txt",
                "source_url": url,
                "file_size": 10 * 1024 * 1024,
            },
        ]
    )

    downloader = CountingDownloader({})
    use_case = build_use_case(
        session_factory,
        downloader,
        InMemoryStorage(),
        RecordingPublisher(),
        admission=AdmissionPolicy(max_tender_bytes=30 * 1024 * 1024),
    )
    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=2)
    )

    assert downloader.requested == []

    async with session_factory() as session:
        reason = await session.scalar(
            select(TenderDocument.skip_reason).where(
                TenderDocument.tender_id == tender_id,
                TenderDocument.attachment_id == "APP",
            )
        )
    assert reason == "tender_budget"


@pytest.mark.asyncio
async def test_overview_pass_leaves_the_rest_for_later(
    session_factory, tender_with_attachments
) -> None:
    """Обзорный проход не имеет права сделать полный невозможным."""
    tz_url = "https://zakupki.gov.ru/file?uid=O-TZ"
    contract_url = "https://zakupki.gov.ru/file?uid=O-CONTRACT"
    bodies = {tz_url: "ХПК в стоках.".encode(), contract_url: "Проект контракта.".encode()}

    tender_id = await tender_with_attachments(
        [
            {
                "attachment_id": "TZ",
                "file_name": "Техническое задание.txt",
                "source_url": tz_url,
                "file_size": 1024,
            },
            {
                "attachment_id": "CONTRACT",
                "file_name": "Проект контракта.txt",
                "source_url": contract_url,
                "file_size": 1024,
            },
        ]
    )

    overview = build_use_case(
        session_factory,
        CountingDownloader({tz_url: bodies[tz_url]}),
        InMemoryStorage(),
        RecordingPublisher(),
        admission=AdmissionPolicy(max_priority=1),
    )
    await overview.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=2)
    )

    # Второй проход — без ограничения приоритета: контракт должен дойти.
    full_downloader = CountingDownloader(bodies)
    full = build_use_case(
        session_factory, full_downloader, InMemoryStorage(), RecordingPublisher()
    )
    await full.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=2)
    )

    assert full_downloader.requested == [contract_url]


@pytest.mark.asyncio
async def test_deferred_and_final_skips_are_distinguishable(
    session_factory, tender_with_attachments
) -> None:
    """В воронке видно, что отброшено навсегда, а что ждёт своей очереди."""
    tz_url = "https://zakupki.gov.ru/file?uid=D-TZ"
    tender_id = await tender_with_attachments(
        [
            {
                "attachment_id": "TZ",
                "file_name": "Техническое задание.txt",
                "source_url": tz_url,
                "file_size": 1024,
            },
            {
                "attachment_id": "VOL",
                "file_name": "ПСД.part01.rar",
                "source_url": "https://zakupki.gov.ru/file?uid=D-VOL",
                "file_size": 1024,
            },
            {
                "attachment_id": "CONTRACT",
                "file_name": "Проект контракта.txt",
                "source_url": "https://zakupki.gov.ru/file?uid=D-CONTRACT",
                "file_size": 1024,
            },
        ]
    )

    use_case = build_use_case(
        session_factory,
        CountingDownloader({tz_url: "ХПК.".encode()}),
        InMemoryStorage(),
        RecordingPublisher(),
        admission=AdmissionPolicy(max_priority=1),
    )
    await use_case.execute(
        TenderIngested(tender_id=tender_id, reg_num=REG_NUM, is_new=True, attachment_count=3)
    )

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    TenderDocument.attachment_id,
                    TenderDocument.extraction_status,
                    TenderDocument.skip_reason,
                ).where(TenderDocument.tender_id == tender_id)
            )
        ).all()

    by_id = {r.attachment_id: r for r in rows}

    # Том архива не станет пригодным от смены настроек — отказ навсегда.
    assert by_id["VOL"].extraction_status == ExtractionStatus.SKIPPED.value
    assert by_id["VOL"].skip_reason == "multivolume"

    # Контракт отсечён обзорным проходом и обязан дождаться полного.
    assert by_id["CONTRACT"].extraction_status == ExtractionStatus.DEFERRED.value
    assert by_id["CONTRACT"].skip_reason == "low_priority"

    assert by_id["TZ"].extraction_status == ExtractionStatus.DONE.value

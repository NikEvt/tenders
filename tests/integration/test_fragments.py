"""Границы чанков и поиск по фрагментам документации."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from libs.shared.db.schema import DocumentChunk, DocumentText, Tender, TenderDocument
from services.api.infrastructure.db.document_repository import SqlDocumentRepository
from services.api.infrastructure.db.fragment_repository import SqlFragmentRepository
from services.docs_worker.backfill_offsets import backfill

PREFIX = "TEST-FRAG-"

# Слово-маркер в тексте фикстуры. Раньше тесты искали «хлоргексидин» — слово
# редкое, но настоящее: в выгрузке его набралось 25 чанков, выдача ограничена
# размером страницы, и фикстура перестала в неё попадать. Тест падал от роста
# данных, а не от поломки. Маркер вымышленный, встретиться в ЕИС не может.
#
# В запросе он в именительном, в тексте — в творительном: морфология остаётся
# частью проверки. Русский стеммер сводит обе формы к «хлоргексидинтестфраг».
MARKER = "хлоргексидинтестфраг"
MARKER_FORM = "хлоргексидинтестфрагом"

CONTENT = (
    f"Мебель  должна выдерживать обработку {MARKER_FORM}.\n\n"
    "Гарантия на изделия составляет не менее трёх лет."
)
# Первый чанк записан так, как его нарезал прежний чанкер: пробелы схлопнуты,
# и подстрокой документа он не является.
OLD_STYLE_CHUNK = f"Мебель должна выдерживать обработку {MARKER_FORM}."
SECOND_CHUNK = "Гарантия на изделия составляет не менее трёх лет."


@pytest.fixture
async def document(session_factory):
    async with session_factory() as session, session.begin():
        tender_id = await session.scalar(
            Tender.__table__.insert()
            .values(reg_num=f"{PREFIX}1", name="Поставка офисной мебели")
            .returning(Tender.id)
        )
        document_id = await session.scalar(
            TenderDocument.__table__.insert()
            .values(
                tender_id=tender_id,
                attachment_id="TZ",
                file_name="ТЗ.pdf",
                extraction_status="done",
            )
            .returning(TenderDocument.id)
        )
        await session.execute(
            DocumentText.__table__.insert().values(
                document_id=document_id,
                tender_id=tender_id,
                content=CONTENT,
                char_count=len(CONTENT),
            )
        )
        for index, text in enumerate([OLD_STYLE_CHUNK, SECOND_CHUNK]):
            await session.execute(
                DocumentChunk.__table__.insert().values(
                    document_id=document_id,
                    tender_id=tender_id,
                    chunk_index=index,
                    text=text,
                    page_from=index + 1,
                )
            )

    yield {"tender_id": tender_id, "document_id": document_id}

    async with session_factory() as session, session.begin():
        await session.execute(delete(Tender).where(Tender.reg_num.like(f"{PREFIX}%")))


@pytest.mark.asyncio
async def test_chunks_without_offsets_report_null(session_factory, document) -> None:
    chunks = await SqlDocumentRepository(session_factory).chunks(document["document_id"])

    assert len(chunks) == 2
    # До бэкфилла смещений нет — и это видно, а не замаскировано нулями.
    assert all(c.char_start is None for c in chunks)
    assert [c.ordinal for c in chunks] == [0, 1]


@pytest.mark.asyncio
async def test_backfill_aligns_old_chunks_to_the_document(session_factory, document) -> None:
    """Точный поиск подстроки здесь вернул бы −1: у старого чанка другие пробелы."""
    assert OLD_STYLE_CHUNK not in CONTENT

    stats = await backfill(session_factory, dry_run=False)
    assert stats.aligned >= 2

    chunks = await SqlDocumentRepository(session_factory).chunks(document["document_id"])
    assert all(c.char_start is not None for c in chunks)

    # Границы указывают на настоящий текст документа.
    first = chunks[0]
    assert CONTENT[first.char_start : first.char_end].startswith("Мебель")
    assert CONTENT[first.char_start : first.char_end].endswith(f"{MARKER_FORM}.")

    second = chunks[1]
    assert CONTENT[second.char_start : second.char_end] == SECOND_CHUNK


@pytest.mark.asyncio
async def test_backfill_is_idempotent(session_factory, document) -> None:
    await backfill(session_factory, dry_run=False)
    again = await backfill(session_factory, dry_run=False)

    # Второй прогон не находит работы: заполненные строки пропускаются.
    assert again.aligned == 0
    assert again.documents == 0


@pytest.mark.asyncio
async def test_dry_run_changes_nothing(session_factory, document) -> None:
    stats = await backfill(session_factory, dry_run=True)
    assert stats.aligned >= 2

    chunks = await SqlDocumentRepository(session_factory).chunks(document["document_id"])
    assert all(c.char_start is None for c in chunks)


def fragments(session_factory) -> SqlFragmentRepository:
    # Без эмбеддера: проверяем лексическую часть и слияние.
    return SqlFragmentRepository(session_factory, embedder=None)


@pytest.mark.asyncio
async def test_lexical_search_returns_the_fragment_itself(session_factory, document) -> None:
    page = await fragments(session_factory).search(MARKER, "lexical", 0, 20)

    ours = [f for f in page.items if f.reg_num.startswith(PREFIX)]
    assert len(ours) == 1
    found = ours[0]
    # Единица выдачи — фрагмент, а не закупка: есть сам текст и его источник.
    assert MARKER_FORM in found.text
    assert found.document_name == "ТЗ.pdf"
    assert found.tender_name == "Поставка офисной мебели"
    assert found.scores.lexical is not None
    assert found.scores.vector is None


@pytest.mark.asyncio
async def test_highlights_point_inside_the_fragment_text(session_factory, document) -> None:
    """Запрос в начальной форме, в тексте — падеж: подсветка обязана попасть."""
    page = await fragments(session_factory).search(MARKER, "lexical", 0, 20)

    ours = [f for f in page.items if f.reg_num.startswith(PREFIX)]
    assert ours
    found = ours[0]
    assert found.highlights
    start, end = found.highlights[0]
    assert found.text[start:end].lower().startswith(MARKER)


@pytest.mark.asyncio
async def test_semantic_mode_without_embedder_yields_nothing(session_factory, document) -> None:
    """Деградация честная: пустая выдача, а не подмена лексическим поиском."""
    page = await fragments(session_factory).search(MARKER, "semantic", 0, 20)
    assert page.total == 0


@pytest.mark.asyncio
async def test_rrf_mode_works_with_lexical_source_alone(session_factory, document) -> None:
    page = await fragments(session_factory).search(MARKER, "rrf", 0, 20)

    ours = [f for f in page.items if f.reg_num.startswith(PREFIX)]
    assert len(ours) == 1
    assert ours[0].scores.rrf > 0


@pytest.mark.asyncio
async def test_search_survives_operator_characters(session_factory, document) -> None:
    page = await fragments(session_factory).search("мебель &&& !!! ()", "rrf", 0, 20)
    assert isinstance(page.total, int)


@pytest.mark.asyncio
async def test_backfilled_offsets_reach_the_search_result(session_factory, document) -> None:
    """Сквозное свойство: найденный фрагмент можно показать в документе."""
    await backfill(session_factory, dry_run=False)

    page = await fragments(session_factory).search(MARKER, "lexical", 0, 20)
    found = next(f for f in page.items if f.reg_num.startswith(PREFIX))

    async with session_factory() as session:
        content = await session.scalar(
            select(DocumentText.content).where(
                DocumentText.document_id == document["document_id"]
            )
        )

    assert found.char_start is not None
    assert content[found.char_start : found.char_end].endswith(f"{MARKER_FORM}.")

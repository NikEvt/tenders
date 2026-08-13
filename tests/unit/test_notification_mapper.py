"""Разбор реального извещения ЕИС."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import xmltodict

from services.crawler.domain.models import TenderStatus
from services.crawler.infrastructure.eis.notification_mapper import (
    NotificationMapper,
    strip_namespaces,
)

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample.xml"


@pytest.fixture(scope="module")
def sample_document() -> dict:
    return xmltodict.parse(SAMPLE.read_bytes())


@pytest.fixture(scope="module")
def tender(sample_document: dict):
    mapped = NotificationMapper(region_code="77").map_document(sample_document)
    assert mapped is not None
    return mapped


def test_basic_fields(tender) -> None:
    assert tender.reg_num == "0373200006226000852"
    assert tender.price == Decimal("151200")
    assert tender.currency == "RUB"
    assert tender.law_type == "44-FZ"
    assert tender.region_code == "77"
    assert tender.customer_inn == "7718690579"
    assert "светодиодных ламп" in (tender.description or "")


def test_dates_keep_calendar_day_despite_offset(tender) -> None:
    # «2026-06-09+03:00» — календарная дата заказчика; перевод в UTC сдвинул бы её.
    assert tender.planned_publish_date == date(2026, 6, 9)
    assert tender.bidding_date == date(2026, 6, 17)
    assert tender.summarizing_date == date(2026, 6, 19)
    assert tender.end_date is not None
    assert tender.end_date.date() == date(2026, 6, 17)


def test_okpd2_is_read_from_ktru(tender) -> None:
    """Регрессия: код ОКПД2 лежит внутри KTRU, а не прямо в purchaseObject.

    Прежний парсер искал только `purchaseObject/OKPD2` и молча писал NULL.
    """
    assert tender.okpd2_codes == ["27.40.15.150"]
    assert tender.okpd2_code == "27.40.15.150"
    assert tender.okpd2_name == "Лампы светодиодные"


def test_attachments_are_extracted(tender) -> None:
    assert len(tender.attachments) == 8
    assert len(tender.downloadable_attachments) == 8

    by_name = {a.file_name: a for a in tender.attachments}
    tz = by_name["Техническое_задание_17160266-1.pdf"]
    assert tz.attachment_id == "C5754F42D66341D2B6364E0F8EAB013D"
    assert tz.doc_kind_code == "POD"
    assert tz.url is not None and tz.url.startswith("https://zakupki.gov.ru/44fz/filestore/")

    # Криптоподписи документами не являются и в список попасть не должны.
    assert all(a.attachment_id for a in tender.attachments)


def test_status_is_derived_from_dates(tender) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    msk = ZoneInfo("Europe/Moscow")
    assert tender.status_at(datetime(2026, 6, 10, 12, 0, tzinfo=msk)) == TenderStatus.COLLECTING
    assert tender.status_at(datetime(2026, 6, 18, 12, 0, tzinfo=msk)) == TenderStatus.BIDDING
    assert tender.status_at(datetime(2026, 6, 25, 12, 0, tzinfo=msk)) == TenderStatus.FINISHED
    assert tender.status_at(datetime(2026, 6, 1, 12, 0, tzinfo=msk)) == TenderStatus.PLANNED


def test_mapper_is_prefix_agnostic(sample_document: dict) -> None:
    """Сервер раздаёт префиксы namespace произвольно — разбор не должен от них зависеть."""

    def requalify(key: str) -> str:
        if ":" not in key or key.startswith("@"):
            return key
        return f"zz9:{key.rsplit(':', 1)[-1]}"

    def rename(obj):
        if isinstance(obj, dict):
            return {requalify(k): rename(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [rename(v) for v in obj]
        return obj

    shuffled = rename(sample_document)
    mapped = NotificationMapper(region_code="77").map_document(shuffled)
    assert mapped is not None
    assert mapped.reg_num == "0373200006226000852"
    assert len(mapped.attachments) == 8


def test_non_notification_document_is_skipped() -> None:
    assert NotificationMapper().map_document({"export": {"someOtherDoc": {"id": "1"}}}) is None


def test_strip_namespaces_keeps_attributes() -> None:
    assert strip_namespaces({"ns3:export": {"@schemeVersion": "16.1"}}) == {
        "export": {"@schemeVersion": "16.1"}
    }

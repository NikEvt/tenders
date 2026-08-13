"""Разбор ответов SOAP-интеграции ЕИС."""

from __future__ import annotations

import pytest
import xmltodict

from services.crawler.infrastructure.eis.soap_client import (
    EisRejectedError,
    SoapTransportError,
    ZakupkiSoapClient,
)


def envelope(body: str) -> dict:
    return xmltodict.parse(
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{body}</soap:Body></soap:Envelope>"
    )


RESPONSE_OPEN = (
    '<ns2:getDocsByOrgRegionResponse xmlns:ns2="http://zakupki.gov.ru/fz44/get-docs-ip/ws">'
)
RESPONSE_CLOSE = "</ns2:getDocsByOrgRegionResponse>"


def test_single_archive_url_is_wrapped_in_list() -> None:
    parsed = envelope(
        f"{RESPONSE_OPEN}<dataInfo><archiveUrl>https://x/1.zip</archiveUrl></dataInfo>"
        f"{RESPONSE_CLOSE}"
    )
    assert ZakupkiSoapClient._archive_urls(parsed) == ["https://x/1.zip"]


def test_multiple_archive_urls() -> None:
    parsed = envelope(
        f"{RESPONSE_OPEN}<dataInfo>"
        "<archiveUrl>https://x/1.zip</archiveUrl>"
        "<archiveUrl>https://x/2.zip</archiveUrl>"
        f"</dataInfo>{RESPONSE_CLOSE}"
    )
    assert ZakupkiSoapClient._archive_urls(parsed) == ["https://x/1.zip", "https://x/2.zip"]


def test_blocked_token_is_reported_not_silently_empty() -> None:
    """Регрессия: отказ ЕИС приходит внутри HTTP 200.

    Раньше заблокированный токен выглядел как «за этот день закупок нет»,
    и краулер месяцами рапортовал бы об успехе с нулём записей.
    """
    parsed = envelope(
        f"{RESPONSE_OPEN}<dataInfo><errorInfo>"
        "<code>34</code>"
        "<message>Организация с токеном 2b93177f заблокирована в ЛК ПМД</message>"
        f"</errorInfo></dataInfo>{RESPONSE_CLOSE}"
    )

    with pytest.raises(EisRejectedError) as exc:
        ZakupkiSoapClient._archive_urls(parsed)

    assert exc.value.code == "34"
    assert "заблокирована" in str(exc.value)
    # Отказ по существу — частный случай транспортной ошибки, чтобы
    # вызывающий код мог ловить оба одним except.
    assert isinstance(exc.value, SoapTransportError)


def test_genuinely_empty_day_is_not_an_error() -> None:
    parsed = envelope(f"{RESPONSE_OPEN}<dataInfo></dataInfo>{RESPONSE_CLOSE}")
    assert ZakupkiSoapClient._archive_urls(parsed) == []


def test_soap_fault_is_raised() -> None:
    parsed = envelope(
        "<soap:Fault><faultstring>Internal error</faultstring></soap:Fault>"
    )
    with pytest.raises(SoapTransportError, match="Fault"):
        ZakupkiSoapClient._archive_urls(parsed)


def test_unexpected_shape_returns_empty() -> None:
    assert ZakupkiSoapClient._archive_urls({"something": "else"}) == []

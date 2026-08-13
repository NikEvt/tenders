"""Транспорт к SOAP-интеграции ЕИС.

Перенесён из прежнего `crawler/soap_client.py`. TLS-послабления, без которых
эндпоинт ЕИС не отвечает, переехали в `libs.shared.http.eis_session` — они нужны
ещё и docs-worker для файлового хранилища.
"""

from __future__ import annotations

import datetime
import io
import uuid
import zipfile
from collections.abc import Iterator

import requests
import xmltodict

from libs.shared.http.eis_session import build_session
from libs.shared.logging import get_logger

log = get_logger(__name__)

DEFAULT_URL = "https://int.zakupki.gov.ru/eis-integration/services/getDocsIP"

XML_BY_REGION = """
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ws="http://zakupki.gov.ru/fz44/get-docs-ip/ws">
  <soapenv:Header>
    <individualPerson_token>{token}</individualPerson_token>
  </soapenv:Header>
  <soapenv:Body>
    <ws:getDocsByOrgRegionRequest>
      <index>
        <id>{uid}</id>
        <createDateTime>{dt}</createDateTime>
        <mode>PROD</mode>
      </index>
      <selectionParams>
        <orgRegion>{region}</orgRegion>
        <subsystemType>{subsystem}</subsystemType>
        <documentType44>{doc_type}</documentType44>
        <periodInfo>
          <exactDate>{date}</exactDate>
        </periodInfo>
      </selectionParams>
    </ws:getDocsByOrgRegionRequest>
  </soapenv:Body>
</soapenv:Envelope>
"""

XML_BY_REESTR = """
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ws="http://zakupki.gov.ru/fz44/get-docs-ip/ws">
  <soapenv:Header>
    <individualPerson_token>{token}</individualPerson_token>
  </soapenv:Header>
  <soapenv:Body>
    <ws:getDocsByReestrNumberRequest>
      <index>
        <id>{uid}</id>
        <createDateTime>{dt}</createDateTime>
        <mode>PROD</mode>
      </index>
      <selectionParams>
        <subsystemType>{subsystem}</subsystemType>
        <reestrNumber>{reestr_number}</reestrNumber>
      </selectionParams>
    </ws:getDocsByReestrNumberRequest>
  </soapenv:Body>
</soapenv:Envelope>
"""


class SoapTransportError(RuntimeError):
    """Ошибка обращения к ЕИС — имеет смысл повторить позже."""


class EisRejectedError(SoapTransportError):
    """ЕИС принял запрос, но отказал по существу.

    Приходит внутри HTTP 200 в `dataInfo/errorInfo`: заблокированный токен,
    неверные параметры выборки, превышение лимитов. Отдельный тип нужен, чтобы
    такой отказ не выглядел как «данных за день нет» — иначе выгрузка месяцами
    рапортует об успехе с нулём записей.
    """

    def __init__(self, code: str | None, message: str) -> None:
        self.code = code
        super().__init__(f"ЕИС отклонил запрос (код {code}): {message}")


class ZakupkiSoapClient:
    """Клиент `getDocsIP`: SOAP-запрос → ссылки на архивы → распакованные XML."""

    def __init__(
        self,
        token: str,
        url: str = DEFAULT_URL,
        session: requests.Session | None = None,
        request_timeout: int = 60,
        download_timeout: int = 300,
    ) -> None:
        self._token = token
        self._url = url
        self._session = session or build_session()
        self._session.headers.update({"Content-Type": "text/xml; charset=utf-8"})
        self._request_timeout = request_timeout
        self._download_timeout = download_timeout

    def _index(self) -> dict[str, str]:
        return {
            "uid": str(uuid.uuid4()),
            "dt": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "token": self._token,
        }

    def _post(self, xml: str) -> dict:
        try:
            response = self._session.post(
                self._url, data=xml.encode("utf-8"), timeout=self._request_timeout
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SoapTransportError(f"Запрос к ЕИС не удался: {exc}") from exc
        return xmltodict.parse(response.content)

    @staticmethod
    def _archive_urls(parsed: dict) -> list[str]:
        """Достаёт `dataInfo/archiveUrl`; ЕИС отдаёт либо строку, либо список."""
        envelope = next(
            (value for key, value in parsed.items() if key.endswith("Envelope")), None
        )
        if not isinstance(envelope, dict):
            log.warning("eis.no_envelope", response=str(parsed)[:500])
            return []
        body = next((value for key, value in envelope.items() if key.endswith("Body")), None)
        if not isinstance(body, dict):
            log.warning("eis.no_body", response=str(parsed)[:500])
            return []

        fault = next((value for key, value in body.items() if key.endswith("Fault")), None)
        if fault is not None:
            raise SoapTransportError(f"ЕИС вернул SOAP Fault: {str(fault)[:500]}")

        response = next((value for key, value in body.items() if "Response" in key), None)
        data_info = (response or {}).get("dataInfo") or {}

        # ЕИС сообщает об отказе внутри HTTP 200. Без этой ветки заблокированный
        # токен выглядел бы как «за этот день закупок не было».
        error_info = data_info.get("errorInfo")
        if error_info:
            raise EisRejectedError(
                code=error_info.get("code"),
                message=str(error_info.get("message", ""))[:500],
            )

        urls = data_info.get("archiveUrl")
        if urls is None:
            log.info("eis.empty_result", data_info=str(data_info)[:300])
            return []
        return urls if isinstance(urls, list) else [urls]

    def _download_archive(self, url: str) -> Iterator[dict]:
        try:
            response = self._session.get(
                url,
                headers={"individualPerson_token": self._token},
                timeout=self._download_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SoapTransportError(f"Не удалось скачать архив {url}: {exc}") from exc

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist():
                if not name.lower().endswith(".xml"):
                    continue
                try:
                    with archive.open(name) as handle:
                        yield xmltodict.parse(handle.read())
                except Exception as exc:
                    # Один битый файл не должен ронять всю выгрузку за день.
                    log.warning("eis.bad_archive_entry", entry=name, error=str(exc))

    def get_by_region(
        self,
        region: str,
        document_type: str,
        target_date: datetime.date,
        subsystem: str = "PRIZ",
    ) -> Iterator[dict]:
        today = datetime.date.today()
        if target_date > today:
            log.warning("eis.future_date", requested=target_date.isoformat())
            target_date = today

        xml = XML_BY_REGION.format(
            **self._index(),
            region=region,
            subsystem=subsystem,
            doc_type=document_type,
            date=target_date.isoformat(),
        )
        log.info(
            "eis.request",
            region=region,
            document_type=document_type,
            date=target_date.isoformat(),
        )
        for url in self._archive_urls(self._post(xml)):
            yield from self._download_archive(url)

    def get_by_reestr(self, reestr_number: str, subsystem: str = "PRIZ") -> Iterator[dict]:
        xml = XML_BY_REESTR.format(
            **self._index(), subsystem=subsystem, reestr_number=reestr_number
        )
        log.info("eis.request_by_reestr", reestr_number=reestr_number)
        for url in self._archive_urls(self._post(xml)):
            yield from self._download_archive(url)

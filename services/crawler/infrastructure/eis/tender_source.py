"""Адаптер `TenderSourcePort` над SOAP-клиентом ЕИС."""

from __future__ import annotations

from collections.abc import Sequence

from libs.shared.logging import get_logger
from services.crawler.application.ports import TenderSourcePort
from services.crawler.domain.models import CrawlRequest, Tender
from services.crawler.infrastructure.eis.notification_mapper import NotificationMapper
from services.crawler.infrastructure.eis.soap_client import ZakupkiSoapClient

log = get_logger(__name__)


class EisTenderSource(TenderSourcePort):
    """Склеивает транспорт и маппер: запрос → XML-документы → доменные тендеры."""

    def __init__(self, client: ZakupkiSoapClient) -> None:
        self._client = client

    def fetch(self, request: CrawlRequest) -> Sequence[Tender]:
        mapper = NotificationMapper(region_code=request.region)

        tenders: list[Tender] = []
        skipped = 0
        for document in self._client.get_by_region(
            region=request.region,
            document_type=request.document_type,
            target_date=request.target_date,
            subsystem=request.subsystem,
        ):
            tender = mapper.map_document(document)
            if tender is None:
                skipped += 1
                continue
            tenders.append(tender)

        if skipped:
            log.info("eis.documents_skipped", count=skipped, region=request.region)
        return tenders
